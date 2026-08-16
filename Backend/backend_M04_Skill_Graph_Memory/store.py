"""`MemoryStore.record()` — the only way mastery changes.

Spec: §6.2 (the write path), §6.4, FR-4.4, FR-4.5, FR-4.20, FR-4.25, FR-4.26,
AC-4.1, AC-4.3, AC-4.11.

Trap 2 is the reason this file is small and severe: the moment M06 does
`mastery.dp += 0.1`, the graph stops being traceable and Rule 3 is dead. So
there is exactly one function that writes a belief, an observation without a
resolvable evidence reference is rejected by the type system before it gets
there, and the mutation helper refuses to run outside this path at runtime —
not just in a CI grep, because a grep cannot see into the eighteen repos that
write here.

Four things happen in a deliberate order, and three of them moved OUT of the
transaction because each was a real bug:

    in tx   insert the observation (uuid5 PK, so a replay is a no-op)
    in tx   compare-and-swap the posterior, 3 attempts
    in tx   propagate, writing derived observations
    in tx   enqueue the outbox event as a ROW
    after   invalidate the cached summary
    after   drain the outbox

Invalidating a cache inside the transaction leaves it invalidated for a write
that may roll back. Emitting an event inside it is a dual write: the event
fires for work that may never land. And the summary goes stale for the NEXT
session rather than this one — see FR-4.23.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime

from ai_core.evidence import (
    ArtifactState,
    EvidenceRef,
    UnresolvableEvidence,
)
from ai_core.evidence import (
    resolve as resolve_evidence,
)
from ai_core.mastery import SE_PRIOR, STATE_THRESHOLDS_VERSION, evaluate
from ai_core.timeutil import utcnow
from pydantic import BaseModel, Field
from sqlalchemy import update as sql_update
from sqlmodel import Session, select

from . import propagation
from .estimators import ESTIMATOR_VERSION, LOCAL_DEPENDENCE_CAP, Response, update
from .models import (
    Artifact,
    ConsentRecord,
    Mastery,
    Observation,
    ObservationKind,
    OutboxEvent,
    ProfileSummary,
    RecordResult,
    ResponseModel,
    RetestQueueItem,
    RetestReason,
    VersionStamp,
)
from .ontology import Ontology, UnknownConcept, load

log = logging.getLogger(__name__)

#: The namespace lives HERE and in the spec, so every caller derives the same
#: id for the same answer. A caller that invents its own namespace produces
#: a "new" observation on every replay, which is the corruption FR-4.25 exists
#: to prevent.
OBS_NAMESPACE = uuid.UUID("6f1c1d3e-0000-4000-8000-000000000004")

MAX_CAS_ATTEMPTS = 3


# ─────────────────────────────────────────────────────────────
#  ERRORS
# ─────────────────────────────────────────────────────────────


class NoConsent(PermissionError):
    """FR-4.20 / AC-4.11. No active consent record, no write. Not a warning."""

    def __init__(self, candidate_id: uuid.UUID) -> None:
        super().__init__(f"no active consent for candidate {candidate_id}")
        self.candidate_id = candidate_id


class ContendedMastery(RuntimeError):
    """Three compare-and-swap attempts lost. EC-4.15.

    Raised rather than swallowed: the caller queues the observation for replay
    and the uuid5 primary key makes that safe. A silent lost update is the one
    outcome that is worse than an error, because nothing downstream can tell
    it happened.
    """


class MasteryWriteOutsideRecordPath(RuntimeError):
    """AC-4.3's runtime half. See `_persist_mastery`."""


# ─────────────────────────────────────────────────────────────
#  THE RUNTIME GUARD  (AC-4.3)
# ─────────────────────────────────────────────────────────────

_write_path_open: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "m04_write_path_open", default=False
)


@contextmanager
def _write_path():
    token = _write_path_open.set(True)
    try:
        yield
    finally:
        _write_path_open.reset(token)


def _persist_mastery(session: Session, statement) -> int:
    """Every mutation of `m04_concept_mastery` goes through here, and here
    refuses to run outside `record()`.

    A contextvar rather than a flag on an object: FastAPI runs sync endpoints
    in a threadpool, so a module-level boolean would leak one request's
    permission into another's.
    """
    if not _write_path_open.get():
        raise MasteryWriteOutsideRecordPath(
            "mastery is only writable inside MemoryStore.record() — see spec §6.2, AC-4.3"
        )
    return session.execute(statement).rowcount


# ─────────────────────────────────────────────────────────────
#  INPUT CONTRACT
# ─────────────────────────────────────────────────────────────


class ObservationIn(BaseModel):
    """What a producer sends. Everything derived is derived here, not there.

    `theta_after`, `se_after`, `theta_eligible` and the id are deliberately NOT
    settable: a caller that could set them could write a belief without
    evidence, which is the whole thing this module prevents.
    """

    candidate_id: uuid.UUID
    concept_id: str
    concept_weight: float = 1.0
    session_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    kind: ObservationKind = ObservationKind.answer_scored

    response_model: ResponseModel = ResponseModel.none
    raw_category: int | None = None
    n_categories: int | None = None
    outcome: float = 0.0
    item: dict | None = None
    source_dimension_key: str | None = None
    weight: float = Field(default=1.0, gt=0.0, le=1.0)

    versions: VersionStamp = Field(default_factory=VersionStamp)
    consent_id: uuid.UUID
    observed_at: datetime = Field(default_factory=utcnow)

    # propagation provenance — set by this module, not by callers
    source_concept_id: str | None = None
    hops: int = 0
    counts_toward_n_direct: bool = True


def observation_id(obs: ObservationIn) -> uuid.UUID:
    """A content hash, so replaying an answer is an insert conflict (FR-4.25).

    Keyed on the turn (falling back to the session), the concept, the kind and
    the rubric version — the rubric because a re-score under a new rubric is
    genuinely a different observation about the same answer, and must not
    collide with the old one.
    """
    anchor = obs.turn_id or obs.session_id
    key = f"{anchor}|{obs.concept_id}|{obs.kind}|{obs.versions.rubric_version}"
    if obs.source_concept_id:
        # Derived rows are one per (source, target) pair, or two prerequisites
        # of the same concept would collide onto one id and the second would
        # silently vanish.
        key = f"{key}|from={obs.source_concept_id}"
    return uuid.uuid5(OBS_NAMESPACE, key)


# ─────────────────────────────────────────────────────────────
#  EVIDENCE  (§5.1 resolution, over M04's own episodic tier)
# ─────────────────────────────────────────────────────────────


class DbArtifactStore:
    """The Phase-1 `ArtifactStore`: M04's episodic tier.

    §5.1 says the resolver reads this until M19's ledger exists, which is what
    makes AC-4.1 testable now rather than after another module ships.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def _row(self, artifact_id: uuid.UUID) -> Artifact | None:
        return self.session.get(Artifact, artifact_id)

    def status(self, artifact_id: uuid.UUID) -> ArtifactState:
        row = self._row(artifact_id)
        if row is None:
            return ArtifactState.absent
        if row.tombstoned_at is not None:
            return ArtifactState.tombstoned
        return ArtifactState.present

    def load(self, artifact_id: uuid.UUID) -> str | None:
        row = self._row(artifact_id)
        return None if row is None or row.tombstoned_at else row.content


def assert_evidence_resolves(session: Session, refs: list[EvidenceRef]) -> list[str]:
    """Hard fail on an unresolvable ref; accept a tombstoned one (EC-4.9).

    Returns the display notes for refs that no longer render — "evidence
    expired" — so the caller can store them rather than discovering the gap in
    the drawer six months later.
    """
    store = DbArtifactStore(session)
    notes: list[str] = []
    for ref in refs:
        result = resolve_evidence(ref, store)
        if not result.storable:
            raise UnresolvableEvidence(ref, result)
        if result.display_note:
            notes.append(result.display_note)
    return notes


def consent_active(session: Session, candidate_id: uuid.UUID, consent_id: uuid.UUID) -> bool:
    record = session.get(ConsentRecord, consent_id)
    return bool(
        record and record.candidate_id == candidate_id and record.revoked_at is None
    )


# ─────────────────────────────────────────────────────────────
#  THE WRITE PATH
# ─────────────────────────────────────────────────────────────


def record(
    session: Session, obs: ObservationIn, *, ontology: Ontology | None = None
) -> RecordResult:
    """Record one observation. The only function that moves a belief."""
    return record_batch(session, [obs], ontology=ontology)[0]


def record_batch(
    session: Session,
    observations: list[ObservationIn],
    *,
    ontology: Ontology | None = None,
) -> list[RecordResult]:
    """M13 emits several observations per turn, so the batch is the real path.

    One transaction for the list — which is what §11's 60 ms budget refers to:
    per call, not per observation. Validation happens for all of them BEFORE
    anything is written, so a bad third observation cannot leave the first two
    committed and the caller unsure what landed.
    """
    graph = ontology or load()
    results: list[RecordResult] = []

    for obs in observations:
        if obs.concept_id not in graph:
            # An FK SQLite does not enforce is not a check. Validated in memory,
            # against the graph the whole module already holds.
            raise UnknownConcept(obs.concept_id)
        if not consent_active(session, obs.candidate_id, obs.consent_id):
            raise NoConsent(obs.candidate_id)
        assert_evidence_resolves(session, obs.evidence)

    with _write_path():
        touched: set[uuid.UUID] = set()
        for obs in observations:
            results.append(_apply(session, obs, graph))
            touched.add(obs.candidate_id)
        session.commit()

    # --- after commit, and in this order ---
    for candidate_id in sorted(touched, key=str):
        mark_profile_stale(session, candidate_id)
    drain_outbox(session)
    return results


def _apply(session: Session, obs: ObservationIn, graph: Ontology) -> RecordResult:
    obs_id = observation_id(obs)

    if session.get(Observation, obs_id) is not None:
        # EC-4.14: a replay from `observations_pending` is a no-op. Mastery
        # moves once, however many times the queue retries.
        return RecordResult(applied=False, observation_id=obs_id, reason="duplicate")

    theta_eligible = _is_theta_eligible(obs)
    mastery = _get_or_create_mastery(session, obs, graph)

    posterior_theta, posterior_se, capped = mastery.theta, mastery.se, False
    if theta_eligible:
        response = _response_from(obs)
        prior_count = _theta_eligible_count_this_session(session, obs)
        posterior = update(
            mastery.theta, mastery.se, response, responses_this_session=prior_count
        )
        posterior_theta, posterior_se = posterior.theta, posterior.se
        capped = posterior.local_dependence_capped

    _write_observation(
        session,
        obs,
        obs_id,
        theta_eligible=theta_eligible,
        theta_after=posterior_theta,
        se_after=posterior_se,
        ontology_version=graph.version,
    )

    _swap_mastery(
        session,
        mastery,
        theta=posterior_theta,
        se=posterior_se,
        observed_at=obs.observed_at,
        direct=obs.counts_toward_n_direct,
    )

    propagated_to = _propagate(session, obs, graph, theta_eligible=theta_eligible)

    session.add(
        OutboxEvent(
            topic="mastery.updated",
            payload={
                "candidate_id": str(obs.candidate_id),
                "concept_id": obs.concept_id,
                "theta": posterior_theta,
                "se": posterior_se,
                "observation_id": str(obs_id),
                "ontology_version": graph.version,
            },
        )
    )

    if capped:
        # Reported, not hidden (§6.3): an unreported correction is
        # indistinguishable from a bug the next time someone reads the SEs.
        log.info(
            "local dependence cap applied: %s/%s is past %d scored answers this session, "
            "so this one moved theta but bought no certainty",
            obs.candidate_id,
            obs.concept_id,
            LOCAL_DEPENDENCE_CAP,
        )

    return RecordResult(
        applied=True,
        observation_id=obs_id,
        theta_after=posterior_theta,
        se_after=posterior_se,
        theta_eligible=theta_eligible,
        propagated_to=propagated_to,
    )


def _is_theta_eligible(obs: ObservationIn) -> bool:
    """EC-4.17. No item, no likelihood — recorded, counted, but not estimated.

    Free-form probes, self-reports, drills and every M05 *grounded* item land
    here (M05 §3.2.5: grounded items "never enter the IRT bank... not for
    ability estimation"). They still update `n_direct`, `last_evidence_at` and
    the episodic tier, and the drawer marks them "not used for the estimate" —
    which is a more honest screen than silently weighting them at zero.
    """
    if obs.kind == ObservationKind.propagated:
        return False
    if obs.response_model == ResponseModel.none or obs.item is None:
        return False
    return obs.item.get("a") is not None and obs.item.get("b") is not None


def _response_from(obs: ObservationIn) -> Response:
    item = obs.item or {}
    if obs.response_model == ResponseModel.grm:
        category = obs.raw_category if obs.raw_category is not None else 0
        n_categories = obs.n_categories or 2
    else:
        # 2PL/3PL want a binary category; `outcome` is the display scalar and
        # is explicitly NOT the likelihood input, so it is thresholded here
        # rather than being fed in as a probability.
        category = 1 if obs.outcome >= 0.5 else 0
        n_categories = 2
    return Response(
        model=str(obs.response_model),
        a=float(item["a"]),
        b=item["b"],
        c=item.get("c"),
        se_b=item.get("se_b"),
        category=category,
        n_categories=n_categories,
        weight=obs.weight,
    )


def _theta_eligible_count_this_session(session: Session, obs: ObservationIn) -> int:
    statement = select(Observation).where(
        Observation.candidate_id == obs.candidate_id,
        Observation.concept_id == obs.concept_id,
        Observation.session_id == obs.session_id,
        Observation.theta_eligible == True,  # noqa: E712 — SQL, not Python truthiness
        Observation.retracted_at == None,  # noqa: E711
    )
    return len(session.exec(statement).all())


def _write_observation(
    session: Session,
    obs: ObservationIn,
    obs_id: uuid.UUID,
    *,
    theta_eligible: bool,
    theta_after: float,
    se_after: float,
    ontology_version: str,
) -> None:
    session.add(
        Observation(
            id=obs_id,
            candidate_id=obs.candidate_id,
            concept_id=obs.concept_id,
            concept_weight=obs.concept_weight,
            session_id=obs.session_id,
            turn_id=obs.turn_id,
            evidence=[ref.model_dump(mode="json") for ref in obs.evidence],
            kind=str(obs.kind),
            response_model=str(obs.response_model),
            raw_category=obs.raw_category,
            n_categories=obs.n_categories,
            outcome=obs.outcome,
            item=obs.item,
            theta_eligible=theta_eligible,
            source_dimension_key=obs.source_dimension_key,
            weight=obs.weight,
            source_concept_id=obs.source_concept_id,
            hops=obs.hops,
            counts_toward_n_direct=obs.counts_toward_n_direct,
            theta_after=theta_after,
            se_after=se_after,
            versions=obs.versions.model_dump(),
            estimator_version=ESTIMATOR_VERSION,
            ontology_version=ontology_version,
            state_thresholds_version=STATE_THRESHOLDS_VERSION,
            consent_id=obs.consent_id,
            observed_at=obs.observed_at,
        )
    )


def _get_or_create_mastery(session: Session, obs: ObservationIn, graph: Ontology) -> Mastery:
    row = session.get(Mastery, (obs.candidate_id, obs.concept_id))
    if row is None:
        row = Mastery(
            candidate_id=obs.candidate_id,
            concept_id=obs.concept_id,
            theta=0.0,
            se=SE_PRIOR,
            ontology_version=graph.version,
            estimator_version=ESTIMATOR_VERSION,
        )
        session.add(row)
        session.flush()
    return row


def _swap_mastery(
    session: Session,
    mastery: Mastery,
    *,
    theta: float,
    se: float,
    observed_at: datetime,
    direct: bool,
    propagated_delta: float = 0.0,
) -> None:
    """Compare-and-swap on `version`, three attempts, then raise (EC-4.15).

    `last_evidence_at` moves for DIRECT observations only. If propagated
    evidence reset the clock, a concept fed by its neighbours would never
    become a re-test candidate — decay would be permanently deferred by
    activity that never actually tested it, which is the same lie as counting
    propagation toward `n_direct`.
    """
    for attempt in range(MAX_CAS_ATTEMPTS):
        expected = mastery.version
        values: dict = {
            "theta": theta,
            "se": min(se, SE_PRIOR),
            "version": expected + 1,
            "updated_at": utcnow(),
        }
        if direct:
            values["n_direct"] = mastery.n_direct + 1
            values["last_evidence_at"] = observed_at
        else:
            values["n_propagated"] = mastery.n_propagated + 1
            values["theta_propagated_total"] = mastery.theta_propagated_total + propagated_delta

        view = evaluate(
            theta=theta,
            se=values["se"],
            n_direct=values.get("n_direct", mastery.n_direct),
            last_evidence_at=values.get("last_evidence_at", mastery.last_evidence_at),
            ever_displayed=mastery.ever_displayed,
        )
        if view.displayable:
            values["ever_displayed"] = True

        statement = (
            sql_update(Mastery)
            .where(
                Mastery.candidate_id == mastery.candidate_id,
                Mastery.concept_id == mastery.concept_id,
                Mastery.version == expected,
            )
            .values(**values)
        )
        if _persist_mastery(session, statement) == 1:
            session.expire(mastery)
            return

        session.expire(mastery)
        refreshed = session.get(Mastery, (mastery.candidate_id, mastery.concept_id))
        if refreshed is None or attempt == MAX_CAS_ATTEMPTS - 1:
            break
        mastery = refreshed

    raise ContendedMastery(
        f"lost {MAX_CAS_ATTEMPTS} compare-and-swap attempts on "
        f"{mastery.candidate_id}/{mastery.concept_id}"
    )


def _propagate(
    session: Session,
    obs: ObservationIn,
    graph: Ontology,
    *,
    theta_eligible: bool,
) -> list[str]:
    """Write the derived observations §6.4 requires, and move their targets.

    Propagation of a propagated observation is not a thing: two hops is the
    limit, and the limit is enforced by not re-entering rather than by a
    counter somebody can get wrong.

    **Propagation is ability estimation, so it obeys the same admissibility
    rule the estimator does.** An observation that cannot move its OWN
    concept's theta — a self-report, a drill, a free-form probe, or one of
    M05's grounded items (§3.2.5: "never enter the IRT bank... not for ability
    estimation") — must not move a neighbour's either. Without this gate the
    module is inconsistent with itself in the direction that flatters the
    student: evidence too weak to score recursion directly was strong enough
    to raise it through DP, and where the neighbour already had direct
    evidence that contribution reached the DISPLAYED value.
    """
    if obs.kind == ObservationKind.propagated or not theta_eligible:
        return []

    steps = propagation.plan(obs.concept_id, obs.outcome, graph)
    touched: list[str] = []

    for step in steps:
        target = session.get(Mastery, (obs.candidate_id, step.concept_id))

        # Work out whether this step LANDS before creating anything. A row
        # created and then skipped is a belief with no observation behind it —
        # AC-4.1's exact failure — and it shows up in the mastery API as a
        # `not_tested` row that a student never generated.
        #
        # The common case for a skip is the honest one: failure propagation to
        # a never-tested concept cannot widen an SE that is already at the
        # prior, because you cannot know less than nothing.
        current_se = target.se if target else SE_PRIOR
        lifetime = target.theta_propagated_total if target else 0.0
        d_theta, new_se, _ = propagation.apply_clamps(
            step, current_se=current_se, lifetime_propagated=lifetime
        )
        if d_theta == 0.0 and new_se == current_se:
            continue

        if target is None:
            target = Mastery(
                candidate_id=obs.candidate_id,
                concept_id=step.concept_id,
                theta=0.0,
                se=SE_PRIOR,
                ontology_version=graph.version,
                estimator_version=ESTIMATOR_VERSION,
            )
            session.add(target)
            session.flush()

        derived = ObservationIn(
            candidate_id=obs.candidate_id,
            concept_id=step.concept_id,
            session_id=obs.session_id,
            turn_id=obs.turn_id,
            # The SOURCE observation's evidence — genuinely the evidence, just
            # indirect. This is what lets the drawer say "0.2 of this came from
            # your dynamic-programming answers on Jun 12, not from a recursion
            # question".
            evidence=obs.evidence,
            kind=ObservationKind.propagated,
            response_model=ResponseModel.none,
            outcome=obs.outcome,
            item=None,
            weight=max(step.weight, 1e-6),
            versions=obs.versions,
            consent_id=obs.consent_id,
            observed_at=obs.observed_at,
            source_concept_id=obs.concept_id,
            hops=step.hops,
            counts_toward_n_direct=False,
        )
        derived_id = observation_id(derived)
        if session.get(Observation, derived_id) is not None:
            continue

        new_theta = max(-4.0, min(4.0, target.theta + d_theta))
        _write_observation(
            session,
            derived,
            derived_id,
            theta_eligible=False,
            theta_after=new_theta,
            se_after=new_se,
            ontology_version=graph.version,
        )
        _swap_mastery(
            session,
            target,
            theta=new_theta,
            se=new_se,
            observed_at=obs.observed_at,
            direct=False,
            propagated_delta=d_theta,
        )
        touched.append(step.concept_id)

        # A concept that has only ever been reached indirectly is exactly the
        # thing to go and check (§6.9, reason='propagated_unverified'). It
        # renders `not_tested` either way — this is how it stops staying that
        # way.
        if target.n_direct == 0:
            enqueue_retest(
                session,
                candidate_id=obs.candidate_id,
                concept_id=step.concept_id,
                reason=RetestReason.propagated_unverified,
                source_ref={"from_concept": obs.concept_id, "hops": step.hops},
                priority=0.5,
            )

    return touched


# ─────────────────────────────────────────────────────────────
#  RETRACTION  (FR-4.26)
# ─────────────────────────────────────────────────────────────


def retract(
    session: Session,
    observation_id_: uuid.UUID,
    reason: str,
    *,
    ontology: Ontology | None = None,
) -> Mastery | None:
    """Mark an observation retracted and RECOMPUTE, never compensate.

    An inverse update leaves two wrong rows in the ledger and a right answer
    nobody can derive from either. M05's flagged items, M13's re-scores,
    EC-4.7 disputes and EC-4.10 account merges all route here.
    """
    row = session.get(Observation, observation_id_)
    if row is None or row.retracted_at is not None:
        return None

    row.retracted_at = utcnow()
    row.retraction_reason = reason
    session.add(row)
    session.commit()

    return recompute(session, row.candidate_id, row.concept_id, ontology=ontology)


def recompute(
    session: Session,
    candidate_id: uuid.UUID,
    concept_id: str,
    *,
    ontology: Ontology | None = None,
) -> Mastery | None:
    """Rebuild one posterior from its surviving observations.

    Also the `estimator_version` bump path (§6.7): observations are immutable,
    so a new estimator does not re-score, it REPLAYS — and the golden snapshot
    is expected to move, deliberately and under review.
    """
    graph = ontology or load()
    statement = (
        select(Observation)
        .where(
            Observation.candidate_id == candidate_id,
            Observation.concept_id == concept_id,
            Observation.retracted_at == None,  # noqa: E711
        )
        .order_by(Observation.observed_at)
    )
    surviving = list(session.exec(statement).all())

    theta, se = 0.0, SE_PRIOR
    n_direct = n_propagated = 0
    last_evidence_at: datetime | None = None
    propagated_total = 0.0
    per_session: dict[uuid.UUID, int] = {}

    for row in surviving:
        if row.theta_eligible and row.item:
            seen = per_session.get(row.session_id, 0)
            posterior = update(
                theta,
                se,
                Response(
                    model=row.response_model,
                    a=float(row.item["a"]),
                    b=row.item["b"],
                    c=row.item.get("c"),
                    se_b=row.item.get("se_b"),
                    category=(
                        row.raw_category
                        if row.response_model == ResponseModel.grm and row.raw_category is not None
                        else (1 if row.outcome >= 0.5 else 0)
                    ),
                    n_categories=row.n_categories or 2,
                    weight=row.weight,
                ),
                responses_this_session=seen,
            )
            theta, se = posterior.theta, posterior.se
            per_session[row.session_id] = seen + 1
        elif row.kind == ObservationKind.propagated:
            delta = row.theta_after - theta
            theta = row.theta_after
            se = row.se_after
            propagated_total += delta

        if row.counts_toward_n_direct:
            n_direct += 1
            last_evidence_at = row.observed_at
        else:
            n_propagated += 1

    mastery = session.get(Mastery, (candidate_id, concept_id))
    if mastery is None:
        return None

    view = evaluate(
        theta=theta,
        se=se,
        n_direct=n_direct,
        last_evidence_at=last_evidence_at,
        ever_displayed=mastery.ever_displayed,
    )
    with _write_path():
        _persist_mastery(
            session,
            sql_update(Mastery)
            .where(
                Mastery.candidate_id == candidate_id,
                Mastery.concept_id == concept_id,
            )
            .values(
                theta=theta,
                se=min(se, SE_PRIOR),
                n_direct=n_direct,
                n_propagated=n_propagated,
                last_evidence_at=last_evidence_at,
                theta_propagated_total=propagated_total,
                # NOT reset: the latch covers decay, not retraction, and
                # `evaluate` already refuses to display a value whose direct
                # evidence has fallen below the threshold.
                ever_displayed=mastery.ever_displayed or view.displayable,
                # A replay stamps the ontology and estimator it ran under, so a
                # snapshot that moved can be attributed to the bump that moved
                # it rather than being argued about.
                ontology_version=graph.version,
                estimator_version=ESTIMATOR_VERSION,
                version=mastery.version + 1,
                updated_at=utcnow(),
            ),
        )
        session.commit()

    session.expire(mastery)
    return session.get(Mastery, (candidate_id, concept_id))


# ─────────────────────────────────────────────────────────────
#  QUEUES AND CACHES
# ─────────────────────────────────────────────────────────────


def enqueue_retest(
    session: Session,
    *,
    candidate_id: uuid.UUID,
    concept_id: str,
    reason: RetestReason,
    source_ref: dict | None = None,
    requested_by: str = "M04",
    priority: float = 1.0,
) -> RetestQueueItem | None:
    """§6.9. One row, five producers. Idempotent per (candidate, concept, reason)
    while an earlier request is still open — a decay sweep runs nightly and
    must not enqueue the same concept thirty times in a month."""
    existing = session.exec(
        select(RetestQueueItem).where(
            RetestQueueItem.candidate_id == candidate_id,
            RetestQueueItem.concept_id == concept_id,
            RetestQueueItem.reason == str(reason),
            RetestQueueItem.resolved_at == None,  # noqa: E711
        )
    ).first()
    if existing is not None:
        return existing

    item = RetestQueueItem(
        candidate_id=candidate_id,
        concept_id=concept_id,
        reason=str(reason),
        requested_by=requested_by,
        source_ref=source_ref or {},
        priority=priority,
    )
    session.add(item)
    return item


def mark_profile_stale(session: Session, candidate_id: uuid.UUID) -> None:
    """Invalidate the NEXT session's summary. After commit, always.

    Not this session's: FR-4.23 pins the injected context for a session's life.
    Mutating an interviewer's prose between its own turns is a bug, and it
    invalidates M06's prompt cache on every observation.
    """
    summary = session.get(ProfileSummary, candidate_id)
    if summary is None:
        return
    summary.stale = True
    session.add(summary)
    session.commit()


def drain_outbox(session: Session, limit: int = 100) -> int:
    """Mark queued events delivered. After commit, always.

    In Phase 1 there is no bus and no subscriber, so this logs and marks. That
    is the honest shape of it: the table is what makes the event survive a
    crash, and swapping the log line for a publish is the only change when a
    queue exists (§20.2 of the master plan: defer until measured pain).
    """
    pending = session.exec(
        select(OutboxEvent)
        .where(OutboxEvent.delivered_at == None)  # noqa: E711
        .order_by(OutboxEvent.created_at)
        .limit(limit)
    ).all()
    for event in pending:
        log.debug("outbox %s %s", event.topic, event.payload)
        event.delivered_at = utcnow()
        session.add(event)
    if pending:
        session.commit()
    return len(pending)


def queue_pending(session: Session, obs: ObservationIn, failure: str) -> None:
    """§10: a write that failed mid-session is queued in M04's OWN database.

    Anywhere else and the fallback fails together with the thing it was meant
    to survive. Replay is safe because the id is a content hash.
    """
    from .models import PendingObservation

    session.add(
        PendingObservation(
            observation_id=observation_id(obs),
            payload=obs.model_dump(mode="json"),
            failure=failure,
        )
    )
    session.commit()
