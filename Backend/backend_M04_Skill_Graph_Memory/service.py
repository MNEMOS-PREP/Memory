"""Read paths and orchestration over the database.

Spec: §6.6 (tiers), §6.8 (bottleneck), §6.9 (re-test queue), §7 (API surface).

Everything in this file that is not a query is a translation from a stored
posterior into what a consumer may see, and there is exactly one rule behind
all of it (Rule 2, FR-4.9, AC-4.2):

    **"not tested" is not zero.**

`mastery_p` comes back `None`, an unresolvable topic label comes back in
`unresolved`, and neither ever comes back as `0.0`. A silent zero is a
confident claim of ignorance and it is the one bug that would make every
downstream module quietly wrong at once.
"""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from datetime import datetime

from ai_core.concepts import normalise_alias
from ai_core.mastery import WEAK_CEILING, evaluate
from ai_core.timeutil import utcnow
from sqlalchemy import bindparam, text
from sqlmodel import Session, select

from .estimators import BktEvent, bkt_p_known
from .models import (
    Artifact,
    ConceptAliasRow,
    ConceptEdgeRow,
    ConceptRow,
    ConsentRecord,
    Dispute,
    Mastery,
    MasteryOut,
    MemoryFact,
    Observation,
    ObservationKind,
    PendingObservation,
    ProfileSummary,
    Purpose,
    RetestQueueItem,
    RetestReason,
    SessionProfileSnapshot,
)
from .ontology import Ontology, load
from .store import enqueue_retest

log = logging.getLogger(__name__)

#: A blocker has to block more than one thing to be worth naming. §6.8: if the
#: top blocker has `blocks < 2`, report NO bottleneck rather than a weak one.
#: A map with 40 equal bars is a wall; a map with one arrow is a plan, and a
#: map with one wrong arrow is worse than either.
MIN_BLOCKS = 2
#: Above this theta a concept is mastered enough to stop the walk, so we
#: surface the earliest UNMASTERED ancestor rather than always surfacing
#: `concept:arrays`.
MASTERED_THETA = 0.2

#: Below this, and with real evidence, a concept is a target worth unblocking.
#:
#: DERIVED from the state machine rather than written down, and that is the
#: whole point. The spec's own value was `theta < -0.3`, which is
#: `mastery_p < 0.4256` — while §5.3 calls a concept "needs work" below 0.45.
#: A student could therefore see a bar labelled *needs work* that the
#: bottleneck query did not count as weak, which is exactly the failure §6.8
#: warns about in its own last bullet: the number in the SQL differing from
#: the number on the screen, on this module's only call to action.
WEAK_THETA = math.log(WEAK_CEILING / (1.0 - WEAK_CEILING))


# ─────────────────────────────────────────────────────────────
#  ONTOLOGY PROJECTION
# ─────────────────────────────────────────────────────────────


def sync_ontology(session: Session, ontology: Ontology | None = None) -> int:
    """Project the YAML graph into tables so SQL can join against it.

    The YAML stays the source of truth and the in-memory graph stays what the
    write path validates against; these rows exist because §6.8's bottleneck
    walk is a recursive CTE. Keyed by `(id, ontology_version)`, so a version
    bump adds rows rather than mutating beliefs that referenced the old ones —
    which is what EC-4.4 and EC-4.5 migrate on.
    """
    graph = ontology or load()
    written = 0

    for concept in graph.concepts.values():
        row = session.get(ConceptRow, (concept.id, graph.version))
        if row is None:
            row = ConceptRow(id=concept.id, ontology_version=graph.version)
            written += 1
        row.name = concept.name
        row.domain = str(concept.domain)
        row.level = str(concept.level)
        row.foundational_floor = concept.foundational_floor
        row.typical_question_time_s = concept.typical_question_time_s
        session.add(row)

        for alias in Ontology._alias_keys(concept):
            alias_row = session.get(ConceptAliasRow, (alias, graph.version))
            if alias_row is None:
                session.add(
                    ConceptAliasRow(
                        alias_normalised=alias,
                        ontology_version=graph.version,
                        concept_id=concept.id,
                    )
                )

    existing_edges = {
        (e.src, e.dst, e.kind)
        for e in session.exec(
            select(ConceptEdgeRow).where(ConceptEdgeRow.ontology_version == graph.version)
        ).all()
    }
    for edge in graph.edges:
        key = (edge.src, edge.dst, str(edge.kind))
        if key in existing_edges:
            continue
        session.add(
            ConceptEdgeRow(
                src=edge.src,
                dst=edge.dst,
                kind=str(edge.kind),
                strength=edge.strength,
                ontology_version=graph.version,
            )
        )
        written += 1

    session.commit()
    log.info("ontology v%s projected: %d new rows", graph.version, written)
    return written


def resolve_labels(
    session: Session, labels: list[str], ontology: Ontology | None = None
) -> dict[str, str | None]:
    """FR-4.21. Free-text topic labels to concept ids, or None.

    Reads the in-memory graph, not the table: it is a dict lookup against the
    same normaliser the callers use, and four modules call this on their own
    hot paths. The table exists for joins, not for this.
    """
    graph = ontology or load()
    return {label: graph.resolve(label) for label in labels}


# ─────────────────────────────────────────────────────────────
#  MASTERY READS
# ─────────────────────────────────────────────────────────────


def mastery_for(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    domain: str | None = None,
    concept_ids: list[str] | None = None,
    ontology: Ontology | None = None,
    now: datetime | None = None,
) -> list[MasteryOut]:
    """Every concept we have anything to say about, plus the ones asked for.

    Note what this does NOT do: invent a row for all 120 concepts. At 120 with
    12 tested a full grid is ~90% empty, and an empty grid teaches a student
    the product is broken (§2.3). The map collapses the untested set to a count
    and a verb, and it can only do that if the API tells it the truth about
    which ones were measured.
    """
    graph = ontology or load()
    now = now or utcnow()

    statement = select(Mastery).where(Mastery.candidate_id == candidate_id)
    rows = {m.concept_id: m for m in session.exec(statement).all()}

    wanted: list[str]
    if concept_ids:
        wanted = list(concept_ids)
    else:
        wanted = sorted(rows)
        if domain:
            wanted = [cid for cid in wanted if cid in graph and graph.get(cid).domain == domain]

    queued = _queued_concepts(session, candidate_id)
    out: list[MasteryOut] = []
    for concept_id in wanted:
        if concept_id not in graph:
            continue
        concept = graph.get(concept_id)
        row = rows.get(concept_id)
        out.append(_to_out(concept_id, concept, row, queued, now))
    return out


def _to_out(concept_id, concept, row: Mastery | None, queued: set[str], now) -> MasteryOut:
    view = evaluate(
        theta=row.theta if row else 0.0,
        se=row.se if row else 1.5,
        n_direct=row.n_direct if row else 0,
        last_evidence_at=row.last_evidence_at if row else None,
        ever_displayed=row.ever_displayed if row else False,
        now=now,
    )
    return MasteryOut(
        concept_id=concept_id,
        name=concept.name,
        domain=str(concept.domain),
        state=str(view.state),
        label=view.label,
        mastery_p=view.mastery_p,
        theta=row.theta if row else 0.0,
        se=row.se if row else 1.5,
        se_effective=view.se_effective,
        n_direct=row.n_direct if row else 0,
        n_propagated=row.n_propagated if row else 0,
        last_evidence_at=row.last_evidence_at if row else None,
        stale=view.stale,
        retest_queued=concept_id in queued,
    )


def theta_by_label(
    session: Session,
    candidate_id: uuid.UUID,
    labels: list[str],
    *,
    ontology: Ontology | None = None,
) -> dict:
    """`GET /v1/skill-graph/theta` — the path M15 already calls.

    Adopted rather than replaced, and it returns objects rather than bare
    floats: M15 ships today consuming `Mapping[str, float]`, and a float cannot
    carry the one thing that matters here, which is whether we know anything at
    all.

    `unresolved` is the whole point. M15 keys its corpus on free-text topics
    students typed, and a label M04 cannot resolve comes back as unresolved —
    never as `theta = 0.0`. The caller then degrades that term to zero weight
    and SAYS SO, which is Rule 2 kept at an API boundary (EC-4.18).
    """
    graph = ontology or load()
    resolved = resolve_labels(session, labels, graph)
    concept_ids = [cid for cid in resolved.values() if cid]

    by_concept = {
        m.concept_id: m
        for m in mastery_for(session, candidate_id, concept_ids=concept_ids, ontology=graph)
    }

    per_topic: dict[str, dict] = {}
    for label, concept_id in resolved.items():
        if concept_id is None:
            continue
        row = by_concept.get(concept_id)
        if row is None:
            continue
        # A resolved label with no measurement behind it gets NULLS, not zeros
        # (AC-4.2). `theta = 0.0` on a logit scale reads as "exactly average",
        # which is a confident claim about a student nobody has asked a
        # question — and it is the number four other modules would inherit.
        measured = row.n_direct > 0
        per_topic[concept_id] = {
            "label": label,
            "theta": row.theta if measured else None,
            "se": row.se_effective if measured else None,
            "mastery_p": row.mastery_p,
            "state": row.state,
            "n_direct": row.n_direct,
            "last_evidence_at": row.last_evidence_at,
        }

    return {
        "per_topic": per_topic,
        "unresolved": sorted(label for label, cid in resolved.items() if cid is None),
        "ontology_version": graph.version,
    }


def evidence_for(
    session: Session,
    candidate_id: uuid.UUID,
    concept_id: str,
    *,
    limit: int = 50,
) -> list[dict]:
    """"Why is this value what it is?" (FR-4.12, Rule 3, AC-4.1).

    Every observation behind a number, including the propagated ones — which
    is the reason §6.4 writes real rows. Each entry says whether it moved the
    estimate, so a student can tell the answer that counted from the drill that
    did not (EC-4.17), and a tombstoned reference says "evidence expired"
    rather than vanishing (EC-4.9).
    """
    statement = (
        select(Observation)
        .where(
            Observation.candidate_id == candidate_id,
            Observation.concept_id == concept_id,
        )
        .order_by(Observation.observed_at.desc())
        .limit(limit)
    )

    out: list[dict] = []
    for row in session.exec(statement).all():
        entry = {
            "observation_id": str(row.id),
            "kind": row.kind,
            "observed_at": row.observed_at,
            "session_id": str(row.session_id),
            "outcome": row.outcome,
            "theta_after": row.theta_after,
            "se_after": row.se_after,
            "moved_the_estimate": row.theta_eligible,
            "retracted": row.retracted_at is not None,
            "evidence": row.evidence,
        }
        if not row.theta_eligible and row.kind != ObservationKind.propagated:
            entry["note"] = "recorded, but not used for the estimate"
        if row.kind == ObservationKind.propagated:
            entry["note"] = (
                f"inherited from your {row.source_concept_id} answers, "
                f"{row.hops} step{'s' if row.hops != 1 else ''} away — "
                "worth checking this one directly"
            )
        out.append(entry)
    return out


def bkt_for(session: Session, candidate_id: uuid.UUID, concept_id: str) -> float | None:
    """The display-only companion, computed on read (§6.3, open decision 4).

    Never persisted: decay and propagation move theta only, so a stored BKT
    value drifts away from the posterior with no rule saying which the UI
    believes. One source of truth, one arbitration problem removed.
    """
    statement = (
        select(Observation)
        .where(
            Observation.candidate_id == candidate_id,
            Observation.concept_id == concept_id,
            Observation.retracted_at == None,  # noqa: E711
            Observation.kind != ObservationKind.propagated,
        )
        .order_by(Observation.observed_at)
    )
    rows = list(session.exec(statement).all())
    if not rows:
        return None

    events: list[BktEvent] = []
    previous_session = None
    previous_at = None
    for row in rows:
        new_session = row.session_id != previous_session
        gap = 0.0
        if new_session and previous_at is not None:
            gap = max(0.0, (row.observed_at - previous_at).total_seconds() / 86_400.0)
        events.append(
            BktEvent(correct=row.outcome >= 0.5, days_since_previous=gap, new_session=new_session)
        )
        previous_session, previous_at = row.session_id, row.observed_at

    return bkt_p_known(events)


# ─────────────────────────────────────────────────────────────
#  BOTTLENECK  (§6.8)
# ─────────────────────────────────────────────────────────────

#: WITH RECURSIVE works on SQLite as well as Postgres, so this stays inside
#: clone-and-run. Four semantics live in prose because the SQL alone does not
#: say them — see `bottlenecks()`.
_BOTTLENECK_SQL = """
WITH RECURSIVE target AS (
  SELECT c.id AS id,
         CASE WHEN m.concept_id IS NOT NULL AND m.n_direct >= 2 THEN 1 ELSE 0 END AS measured
    FROM m04_concepts c
    LEFT JOIN m04_concept_mastery m
           ON m.concept_id = c.id AND m.candidate_id = :cid
   WHERE c.ontology_version = :ov
     AND (m.concept_id IS NULL OR (m.n_direct >= 2 AND m.theta < :weak))
),
up(target_id, measured, blocker, hop, path_strength) AS (
  SELECT t.id, t.measured, e.src, 1, e.strength
    FROM target t
    JOIN m04_concept_edges e ON e.dst = t.id AND e.ontology_version = :ov
   WHERE e.kind = 'prerequisite_of'
  UNION ALL
  SELECT u.target_id, u.measured, e.src, u.hop + 1, u.path_strength * e.strength
    FROM up u
    JOIN m04_concept_edges e ON e.dst = u.blocker AND e.ontology_version = :ov
    LEFT JOIN m04_concept_mastery mb
           ON mb.concept_id = u.blocker AND mb.candidate_id = :cid
   WHERE e.kind = 'prerequisite_of'
     AND u.hop < 3
     AND (mb.concept_id IS NULL OR mb.theta < :mastered)
)
SELECT u.blocker                     AS blocker,
       count(DISTINCT u.target_id)   AS blocks,
       sum(u.path_strength)          AS weighted_blocks,
       max(u.measured)               AS has_measured_target,
       m.theta                       AS theta,
       m.se                          AS se,
       m.n_direct                    AS n_direct
  FROM up u
  JOIN m04_concepts c
    ON c.id = u.blocker AND c.ontology_version = :ov AND NOT c.foundational_floor
  LEFT JOIN m04_concept_mastery m
         ON m.concept_id = u.blocker AND m.candidate_id = :cid
 GROUP BY u.blocker, m.theta, m.se, m.n_direct
HAVING (m.theta IS NULL OR m.theta < :mastered)
   AND (max(u.measured) = 1 OR m.n_direct >= 2)
 ORDER BY weighted_blocks DESC, blocks DESC, blocker ASC
 LIMIT 3
"""


def _bottleneck_statement():
    """The raw SQL, with `:cid` bound through the COLUMN'S OWN type.

    Not a detail. SQLModel maps `uuid.UUID` to `CHAR(32)` holding un-hyphenated
    hex on SQLite, and to a native `uuid` column on Postgres. A hand-written
    `str(candidate_id)` therefore matches on exactly one of the two stores and
    silently matches NOTHING on the other — no error, no empty-result warning,
    just a student whose every concept looks untested and a bottleneck card
    that renders nothing forever.

    Binding through `Mastery.__table__.c.candidate_id.type` means the
    parameter is rendered by the same code that wrote the column, on whichever
    dialect is in front of us.
    """
    cid_type = Mastery.__table__.c.candidate_id.type
    return text(_BOTTLENECK_SQL).bindparams(bindparam("cid", type_=cid_type))


def bottlenecks(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    ontology: Ontology | None = None,
) -> list[dict]:
    """The earliest unmastered prerequisite blocking the most targets.

    Four semantics, each of which is the REASON this is recursive:

    * **Stop walking a path once the blocker is itself mastered**, so we
      surface the earliest *unmastered* ancestor rather than always surfacing
      `concept:arrays`.
    * **Rank by strength-decayed `weighted_blocks`**, not raw count, so a hop-2
      blocker behind a 0.4 edge does not outrank a hop-1 blocker behind a 0.9
      one.
    * **`foundational_floor` concepts are excluded.** "Work on variables" is
      insulting advice (M16 §6.4a), and the floor belongs in the query every
      consumer shares rather than as a patch in one downstream module.
    * **Targets include untested concepts**, because §2.3's own mock counts
      "Backtracking — not tested" among the four that recursion blocks.
      Excluding them made the number in the SQL differ from the number on
      screen, on this module's only call to action.

    Returns [] when the best blocker blocks fewer than two things. A weak
    bottleneck is worse than none: it is a confident instruction to spend a
    week on the wrong topic.

    **A fifth semantic the spec does not state, and has to: something has to
    be measured.** A brand-new student with zero observations was otherwise
    told "your recursion blocks 22 topics" — every concept in the ontology is
    untested, so every root looks like a bottleneck. That is a number with
    nothing behind it, which is Rule 3 violated on the one screen whose entire
    job is to be actionable, and it contradicts EC-4.1's promise that a new
    student gets an onboarding state rather than fabricated findings.

    So a blocker qualifies two ways, and it needs both routes:

    * it is **itself measured** and unmastered — which is §2.3's own mock,
      where *"Recursion · needs work · blocks 4"* is the CTA and three of the
      four things it blocks are untested; or
    * **at least one target it blocks is measured-weak** — the "earliest
      unmastered ancestor" case, where the blocker itself has never been
      tested but sits above something we know is broken.

    Untested targets still COUNT toward `blocks` either way, which is what
    keeps the number in this query equal to the number on the screen.
    """
    graph = ontology or load()
    rows = (
        session.execute(
            _bottleneck_statement(),
            {
                "cid": candidate_id,
                "ov": graph.version,
                "weak": WEAK_THETA,
                "mastered": MASTERED_THETA,
            },
        )
        .mappings()
        .all()
    )

    out: list[dict] = []
    for row in rows:
        if row["blocks"] < MIN_BLOCKS:
            continue
        concept = graph.concepts.get(row["blocker"])
        if concept is None:
            continue
        out.append(
            {
                "concept_id": row["blocker"],
                "name": concept.name,
                "domain": str(concept.domain),
                "blocks": int(row["blocks"]),
                "weighted_blocks": round(float(row["weighted_blocks"]), 3),
                "theta": row["theta"],
                "se": row["se"],
                "n_direct": int(row["n_direct"] or 0),
            }
        )
    return out


# ─────────────────────────────────────────────────────────────
#  DISPUTES AND RE-TESTS
# ─────────────────────────────────────────────────────────────


def open_dispute(
    session: Session, candidate_id: uuid.UUID, concept_id: str, reason: str
) -> dict:
    """"This doesn't look right" → flag + queued re-test (§2.4, EC-4.7).

    It never argues. Being wrong occasionally is survivable; being wrong and
    unaccountable is not — so the answer is a re-test with `bypass_freshness`,
    without which M05's 90-day no-repeat filter would make the disputed value
    literally impossible to re-check and the promise empty.
    """
    mastery = session.get(Mastery, (candidate_id, concept_id))
    dispute = Dispute(
        candidate_id=candidate_id,
        concept_id=concept_id,
        reason=reason,
        theta_at_dispute=mastery.theta if mastery else 0.0,
    )
    session.add(dispute)
    session.flush()

    item = enqueue_retest(
        session,
        candidate_id=candidate_id,
        concept_id=concept_id,
        reason=RetestReason.dispute,
        source_ref={"dispute_id": str(dispute.id)},
        priority=2.0,
    )
    session.commit()

    return {
        "dispute_id": str(dispute.id),
        "concept_id": concept_id,
        "retest_id": str(item.id) if item else None,
        # The student-facing state, which is what makes disputing feel like
        # being heard rather than shouting.
        "message": "We've queued a question on this for your next session.",
    }


def retests(session: Session, candidate_id: uuid.UUID, *, open_only: bool = True) -> list[dict]:
    statement = select(RetestQueueItem).where(RetestQueueItem.candidate_id == candidate_id)
    if open_only:
        statement = statement.where(RetestQueueItem.resolved_at == None)  # noqa: E711
    statement = statement.order_by(RetestQueueItem.priority.desc(), RetestQueueItem.created_at)

    graph = load()
    out = []
    for row in session.exec(statement).all():
        concept = graph.concepts.get(row.concept_id)
        out.append(
            {
                "id": str(row.id),
                "concept_id": row.concept_id,
                "name": concept.name if concept else row.concept_id,
                "reason": row.reason,
                "requested_by": row.requested_by,
                "priority": row.priority,
                "bypass_freshness": row.bypass_freshness,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
        )
    return out


def sweep_decay(
    session: Session,
    *,
    candidate_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Queue a re-test for everything that has decayed past the threshold.

    §6.5's hand-off to M16, as a table rather than a phrase. Nightly, or on
    demand. Only concepts with direct evidence: a concept nobody was ever asked
    about is a question for the selector, not a row in this queue.
    """
    now = now or utcnow()
    statement = select(Mastery).where(Mastery.n_direct > 0)
    if candidate_id is not None:
        statement = statement.where(Mastery.candidate_id == candidate_id)

    queued: list[str] = []
    for row in session.exec(statement).all():
        view = evaluate(
            theta=row.theta,
            se=row.se,
            n_direct=row.n_direct,
            last_evidence_at=row.last_evidence_at,
            ever_displayed=row.ever_displayed,
            now=now,
        )
        if not view.retest_candidate:
            continue
        item = enqueue_retest(
            session,
            candidate_id=row.candidate_id,
            concept_id=row.concept_id,
            reason=RetestReason.decay,
            source_ref={"se_effective": round(view.se_effective, 3)},
            priority=1.0,
        )
        if item is not None:
            queued.append(row.concept_id)
    session.commit()
    return queued


def _queued_concepts(session: Session, candidate_id: uuid.UUID) -> set[str]:
    rows = session.exec(
        select(RetestQueueItem.concept_id).where(
            RetestQueueItem.candidate_id == candidate_id,
            RetestQueueItem.resolved_at == None,  # noqa: E711
        )
    ).all()
    return set(rows)


def normalise(label: str) -> str:
    """Re-exported so callers do not import `ai_core` just to build a key."""
    return normalise_alias(label)


# ─────────────────────────────────────────────────────────────
#  THE WORKING TIER  (§6.6, FR-4.23) — what an agent gets at session start
# ─────────────────────────────────────────────────────────────

#: §11's budget. The summary is injected into every turn of an interview, so
#: this is a per-turn cost multiplied by the length of a session.
SUMMARY_TOKEN_BUDGET = 1200
SUMMARY_VERSION = "1.0"
#: Rough, and deliberately so: a real tokeniser here would mean importing one
#: on a read path to enforce a budget that only has to be approximately right.
CHARS_PER_TOKEN = 4


def build_profile_summary(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    ontology: Ontology | None = None,
    now: datetime | None = None,
) -> ProfileSummary:
    """Assemble the working tier and cache it. §6.6.

    Mastery top and bottom 10, the open bottlenecks, and the outstanding
    re-tests — everything an interviewer needs to open a session knowing who
    it is talking to.

    Two slots are present and empty until M6 lands: `recent_sessions` and
    `facts`. They are in the payload on purpose rather than omitted, because a
    consumer that codes against a shape which later grows a key has to change,
    and M06 is being written against this contract now. An empty list is a
    promise; a missing key is a migration.
    """
    graph = ontology or load()
    now = now or utcnow()

    rows = mastery_for(session, candidate_id, ontology=graph, now=now)
    displayable = [r for r in rows if r.mastery_p is not None]
    ranked = sorted(displayable, key=lambda r: r.mastery_p or 0.0)

    def brief(row: MasteryOut) -> dict:
        return {
            "concept_id": row.concept_id,
            "name": row.name,
            "state": row.state,
            "mastery_p": row.mastery_p,
            "n_direct": row.n_direct,
            "stale": row.stale,
        }

    weakest = [brief(r) for r in ranked[:10]]
    strongest = [brief(r) for r in reversed(ranked[-10:])]

    facts = session.exec(
        select(MemoryFact)
        .where(
            MemoryFact.candidate_id == candidate_id,
            MemoryFact.superseded_by == None,  # noqa: E711
        )
        .order_by(MemoryFact.importance.desc())
        .limit(5)
    ).all()

    payload = {
        "candidate_id": str(candidate_id),
        "ontology_version": graph.version,
        "measured_concepts": len(rows),
        "weakest": weakest,
        "strongest": strongest,
        "bottlenecks": bottlenecks(session, candidate_id, ontology=graph),
        "retests": retests(session, candidate_id)[:5],
        # M6 fills these. Present-and-empty, not absent — see the docstring.
        "recent_sessions": [],
        "facts": [
            {"kind": f.kind, "sentence": f.display_sentence, "importance": f.importance}
            for f in facts
            if _fact_is_visible(f, now)
        ],
    }

    text_lines = [f"{b['name']}: {b['state']}" for b in weakest[:5]]
    summary_text = " · ".join(text_lines)

    row = session.get(ProfileSummary, candidate_id)
    if row is None:
        row = ProfileSummary(candidate_id=candidate_id)
        session.add(row)
    row.summary_text = summary_text
    row.payload = _json_safe(payload)
    row.token_estimate = (len(summary_text) + len(str(payload))) // CHARS_PER_TOKEN
    row.stale = False
    row.built_at = now
    row.summary_version = SUMMARY_VERSION
    session.commit()
    session.refresh(row)
    return row


def _json_safe(value):
    """Coerce to something the JSON column can hold, recursively.

    Not cosmetic: `payload` is compared for byte-identity by AC-4.13, and a
    value that round-trips through the column differently from how it went in
    would fail that gate for a reason that has nothing to do with pinning.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _fact_is_visible(fact: MemoryFact, now: datetime) -> bool:
    """A deleted fact stays deleted. §15.9: suppression is a promise, and the
    button was a lie if the distiller can quietly re-surface what it hid."""
    return fact.suppressed_until is None or fact.suppressed_until <= now


def pinned_profile_summary(
    session: Session,
    candidate_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    ontology: Ontology | None = None,
    now: datetime | None = None,
) -> dict:
    """FR-4.23, AC-4.13 — byte-identical for the life of a session.

    Written once when the session opens and served unchanged thereafter, no
    matter how many observations land in between. `record()` marks the NEXT
    session's summary stale, never this one's: mutating an interviewer's own
    context between its turns is a bug, and it invalidates M06's prompt cache
    on every observation, which is a real bill rather than a purity argument.

    In-session movement is not lost — it reaches the interviewer through the
    channel that is supposed to carry it, M05's selector reading live mastery.
    """
    snapshot = session.get(SessionProfileSnapshot, session_id)
    if snapshot is not None:
        if snapshot.candidate_id != candidate_id:
            # The same session id cannot belong to two candidates. Returning
            # the stored one would hand a third party someone else's profile.
            raise SessionCandidateMismatch(session_id)
        return _snapshot_out(snapshot, pinned=True)

    summary = session.get(ProfileSummary, candidate_id)
    if summary is None or summary.stale:
        summary = build_profile_summary(session, candidate_id, ontology=ontology, now=now)

    snapshot = SessionProfileSnapshot(
        session_id=session_id,
        candidate_id=candidate_id,
        summary_text=summary.summary_text,
        payload=summary.payload,
        summary_version=summary.summary_version,
        ontology_version=str(summary.payload.get("ontology_version", "")),
        built_at=now or utcnow(),
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return _snapshot_out(snapshot, pinned=True)


def _snapshot_out(snapshot: SessionProfileSnapshot, *, pinned: bool) -> dict:
    return {
        "session_id": str(snapshot.session_id),
        "candidate_id": str(snapshot.candidate_id),
        "summary_text": snapshot.summary_text,
        "payload": snapshot.payload,
        "summary_version": snapshot.summary_version,
        "ontology_version": snapshot.ontology_version,
        "built_at": snapshot.built_at.isoformat(),
        "pinned": pinned,
    }


class SessionCandidateMismatch(Exception):
    """A pinned snapshot exists for this session under a different candidate."""

    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(f"session {session_id} belongs to another candidate")
        self.session_id = session_id


# ─────────────────────────────────────────────────────────────
#  TRAJECTORY  (§7) — the contract M19 needs; M19 owns the chart
# ─────────────────────────────────────────────────────────────


def trajectory(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    concept_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    ontology: Ontology | None = None,
) -> dict:
    """Mastery over time, straight from the observations of record.

    Served from `theta_after` / `se_after` — stored on every observation
    exactly so this is a read rather than a re-run of the estimator. That
    matters beyond speed: a chart recomputed under today's estimator would
    silently redraw history under a scale the student was never scored on.

    Only theta-eligible observations carry a point. The rest are real evidence
    and appear in the drawer, but they moved no estimate, and inventing a
    plateau for them would be drawing a line through data that does not exist.
    """
    graph = ontology or load()
    statement = select(Observation).where(
        Observation.candidate_id == candidate_id,
        Observation.theta_eligible == True,  # noqa: E712
    )
    if concept_id is not None:
        statement = statement.where(Observation.concept_id == concept_id)
    if since is not None:
        statement = statement.where(Observation.observed_at >= since)
    if until is not None:
        statement = statement.where(Observation.observed_at <= until)

    rows = session.exec(statement.order_by(Observation.observed_at)).all()

    series: dict[str, list[dict]] = {}
    for row in rows:
        series.setdefault(row.concept_id, []).append(
            {
                "observed_at": row.observed_at.isoformat(),
                "theta": row.theta_after,
                "se": row.se_after,
                "kind": row.kind,
                "estimator_version": row.estimator_version,
                "ontology_version": row.ontology_version,
            }
        )

    return {
        "candidate_id": str(candidate_id),
        "ontology_version": graph.version,
        "series": [
            {
                "concept_id": cid,
                "name": graph.get(cid).name if cid in graph else cid,
                "points": points,
            }
            for cid, points in sorted(series.items())
        ],
        # Said rather than implied: an empty series and "this student has never
        # been scored" are the same JSON otherwise, and M19 renders them
        # differently.
        "reason": None if series else "no scored observations in this window",
    }


# ─────────────────────────────────────────────────────────────
#  THE STUDENT'S RIGHTS  (FR-4.18a/b/c, §4) — export, delete, revoke
# ─────────────────────────────────────────────────────────────


def _pending_for(session: Session, candidate_id: uuid.UUID) -> list[PendingObservation]:
    """The fallback queue holds whole payloads, not foreign keys — it exists
    precisely for the case where the write failed, so it cannot depend on the
    row having been written. The candidate is therefore inside the payload."""
    return [
        row
        for row in session.exec(select(PendingObservation)).all()
        if str(row.payload.get("candidate_id", "")) == str(candidate_id)
    ]


# ─────────────────────────────────────────────────────────────
#  THE EPISODIC TIER  (§5.1 — what evidence resolves against)
# ─────────────────────────────────────────────────────────────

#: For artifacts with no turn behind them. A turn-scoped one does not use it —
#: see below.
ARTIFACT_NAMESPACE = uuid.UUID("6f0f3d40-8f38-5a1a-9f2f-2a4c0e6a1b44")


def artifact_id_for(session_id: uuid.UUID, turn_id: uuid.UUID | None, artifact_type: str):
    """**A turn's artifact IS the turn.**

    Not a derivation over it: M13 cites `artifact_id=turn.turn_id` on every
    span it quotes (`service.py`, where it builds the evaluator's view), so
    any other rule here would resolve to `absent` no matter how principled it
    was. Making the two the same by construction means there is no namespace
    for two modules to agree on and then drift apart on.

    Everything else — a session-level submission, a canvas with no turn — is
    keyed by `uuid5` over the session and the type, because those have no
    natural id and a producer should not have to keep one.
    """
    if turn_id is not None:
        return turn_id
    return uuid.uuid5(ARTIFACT_NAMESPACE, f"{session_id}|{artifact_type}")


def register_artifact(
    session: Session,
    *,
    candidate_id: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: uuid.UUID | None,
    content: str,
    artifact_type: str = "transcript",
) -> tuple[Artifact, bool]:
    """Store the thing a quote will be quoted from. `(artifact, created)`.

    The table has been here since day one and nothing could write to it, so
    every evidence ref from another module resolved to `absent` and the
    observation behind it was refused — which is how a scored interview
    reached M04 and moved nothing. AC-4.1 is only testable because this tier
    exists; it is only *true* because something fills it.

    Immutable on purpose: a second call with different content for the same
    turn returns the row that is already there. Evidence quotes character
    offsets into this text, so replacing it silently would move every span
    that points at it.
    """
    artifact = session.get(Artifact, artifact_id_for(session_id, turn_id, artifact_type))
    if artifact is not None:
        return artifact, False
    artifact = Artifact(
        id=artifact_id_for(session_id, turn_id, artifact_type),
        candidate_id=candidate_id,
        session_id=session_id,
        turn_id=turn_id,
        artifact_type=artifact_type,
        content=content,
        checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact, True


# ─────────────────────────────────────────────────────────────
#  CONSENT  (FR-4.20 — the thing every write is checked against)
# ─────────────────────────────────────────────────────────────


def active_consent(
    session: Session, candidate_id: uuid.UUID, purpose: str
) -> ConsentRecord | None:
    """The consent a write may cite, or None. Newest first, so a re-grant
    after a revocation is the one that counts."""
    rows = session.exec(
        select(ConsentRecord)
        .where(ConsentRecord.candidate_id == candidate_id)
        .where(ConsentRecord.purpose == purpose)
        .where(ConsentRecord.revoked_at.is_(None))
        .order_by(ConsentRecord.granted_at.desc())
    ).all()
    return rows[0] if rows else None


def grant_consent(
    session: Session,
    candidate_id: uuid.UUID,
    purpose: str,
    *,
    policy_version: str = "1.0",
) -> tuple[ConsentRecord, bool]:
    """Record consent for one purpose. `(record, created)`.

    Idempotent by design: a student opening a second interview is not a second
    consent, and a module that retries a session start must not accumulate
    rows nobody can tell apart. A grant at a NEW policy version is a real
    second consent, because it is a different thing being agreed to.
    """
    if purpose not in set(Purpose):
        raise UnknownPurpose(purpose)
    existing = active_consent(session, candidate_id, purpose)
    if existing is not None and existing.policy_version == policy_version:
        return existing, False
    record = ConsentRecord(
        candidate_id=candidate_id, purpose=purpose, policy_version=policy_version
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record, True


def consents_for(session: Session, candidate_id: uuid.UUID) -> list[ConsentRecord]:
    """Every consent on record, revoked ones included — FR-4.18a says a
    student may read their own history, and "when did I withdraw" is part of
    it."""
    return list(
        session.exec(
            select(ConsentRecord)
            .where(ConsentRecord.candidate_id == candidate_id)
            .order_by(ConsentRecord.granted_at.desc())
        ).all()
    )


def export_memory(session: Session, candidate_id: uuid.UUID) -> dict:
    """FR-4.18a — everything this module holds about one person.

    Every table, not a summary of them. An export a student cannot check
    against what we actually store is a gesture rather than a right.
    """

    def dump(rows) -> list[dict]:
        return [r.model_dump(mode="json") for r in rows]

    def by_candidate(model):
        return session.exec(select(model).where(model.candidate_id == candidate_id)).all()

    return {
        "candidate_id": str(candidate_id),
        "exported_at": utcnow().isoformat(),
        "consent": dump(by_candidate(ConsentRecord)),
        "mastery": dump(by_candidate(Mastery)),
        "observations": dump(by_candidate(Observation)),
        # Keyed by observation id, not candidate — the queue predates the row
        # it is trying to write, so the candidate is only in the payload.
        "observations_pending": [
            row.model_dump(mode="json") for row in _pending_for(session, candidate_id)
        ],
        "artifacts": dump(by_candidate(Artifact)),
        "facts": dump(by_candidate(MemoryFact)),
        "retests": dump(by_candidate(RetestQueueItem)),
        "disputes": dump(by_candidate(Dispute)),
        "profile_summary": dump(
            session.exec(
                select(ProfileSummary).where(ProfileSummary.candidate_id == candidate_id)
            ).all()
        ),
    }


def delete_memory(session: Session, candidate_id: uuid.UUID) -> dict:
    """FR-4.18b — hard delete, and it has to be hard.

    Not a `deleted` flag. The episodic tier is the substrate every number is
    re-derivable from, so leaving it in place while hiding it would mean the
    numbers could come back — and the promise in §8 is that they cannot.

    Consent rows survive deliberately, with their `revoked_at` set: "when did
    this person withdraw" is a question the ethics annexe has to answer, and
    it cannot be answered from a table we just emptied.
    """
    deleted: dict[str, int] = {}
    pending = _pending_for(session, candidate_id)
    for row in pending:
        session.delete(row)
    deleted[PendingObservation.__tablename__] = len(pending)

    for model in (
        Observation,
        Mastery,
        MemoryFact,
        RetestQueueItem,
        Dispute,
        Artifact,
        ProfileSummary,
    ):
        rows = session.exec(select(model).where(model.candidate_id == candidate_id)).all()
        for row in rows:
            session.delete(row)
        deleted[model.__tablename__] = len(rows)

    snapshots = session.exec(
        select(SessionProfileSnapshot).where(
            SessionProfileSnapshot.candidate_id == candidate_id
        )
    ).all()
    for snapshot in snapshots:
        session.delete(snapshot)
    deleted[SessionProfileSnapshot.__tablename__] = len(snapshots)

    now = utcnow()
    for consent in session.exec(
        select(ConsentRecord).where(ConsentRecord.candidate_id == candidate_id)
    ).all():
        if consent.revoked_at is None:
            consent.revoked_at = now
        consent.purge_due_at = None
        session.add(consent)

    session.commit()
    return {"candidate_id": str(candidate_id), "deleted": deleted, "at": now.isoformat()}


def revoke_purpose(
    session: Session,
    candidate_id: uuid.UUID,
    purpose: str,
    *,
    now: datetime | None = None,
    grace_days: int = 30,
) -> dict:
    """FR-4.18c — withdraw one purpose without touching the others.

    A student leaving the study keeps their practice history. The revocation
    is recorded immediately and `purge_due_at` records what is still owed, so
    a sweep can find outstanding work rather than a cron being trusted to have
    run — the failure mode of the alternative is silent and unauditable.
    """
    from datetime import timedelta

    now = now or utcnow()
    if purpose == Purpose.practice:
        # Practice is the purpose the platform exists for; revoking it is a
        # deletion, and calling it a revocation would leave the student
        # believing something narrower happened.
        raise CannotRevokePractice()

    revoked = 0
    for consent in session.exec(
        select(ConsentRecord).where(
            ConsentRecord.candidate_id == candidate_id,
            ConsentRecord.purpose == purpose,
            ConsentRecord.revoked_at == None,  # noqa: E711
        )
    ).all():
        consent.revoked_at = now
        consent.purge_due_at = now + timedelta(days=grace_days)
        session.add(consent)
        revoked += 1

    facts = session.exec(
        select(MemoryFact).where(
            MemoryFact.candidate_id == candidate_id,
            MemoryFact.purpose == purpose,
        )
    ).all()
    for fact in facts:
        session.delete(fact)

    session.commit()
    return {
        "candidate_id": str(candidate_id),
        "purpose": purpose,
        "consent_rows_revoked": revoked,
        "facts_removed": len(facts),
        "purge_due_at": (now + timedelta(days=grace_days)).isoformat(),
    }


class CannotRevokePractice(Exception):
    """Revoking `practice` is a deletion; say so rather than half-doing it."""


class UnknownPurpose(Exception):
    """Consent is per purpose and revocation is per purpose, so a purpose
    nobody can revoke is consent nobody can withdraw."""
