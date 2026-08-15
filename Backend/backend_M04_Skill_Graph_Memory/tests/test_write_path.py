"""The write path (§6.2) and propagation (§6.4).

Adversarial cases from §12 live here: an unresolvable reference, a tombstoned
one, a replayed observation, a batch, a retraction.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from ai_core.evidence import EvidenceRef, EvidenceSpan, UnresolvableEvidence, sha256_hex
from ai_core.mastery import SE_PRIOR, MasteryState, evaluate
from sqlmodel import select

from backend_M04_Skill_Graph_Memory import store
from backend_M04_Skill_Graph_Memory.models import Mastery, Observation, OutboxEvent, RetestQueueItem
from backend_M04_Skill_Graph_Memory.ontology import UnknownConcept
from backend_M04_Skill_Graph_Memory.propagation import LIFETIME_CAP
from backend_M04_Skill_Graph_Memory.store import NoConsent, record, record_batch

from .conftest import NOW, evidence_for, make_artifact, scored

DP = "concept:dynamic_programming"
RECURSION = "concept:recursion"


# ── the basic contract ────────────────────────────────────────────────────


def test_a_scored_answer_moves_the_posterior(session, candidate_id, consent, graph):
    artifact = make_artifact(session, candidate_id)
    result = record(
        session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph
    )

    assert result.applied is True
    assert result.theta_eligible is True
    assert result.theta_after > 0

    mastery = session.get(Mastery, (candidate_id, DP))
    assert mastery.n_direct == 1
    assert mastery.se < SE_PRIOR
    assert mastery.last_evidence_at is not None


def test_an_unknown_concept_is_rejected(session, candidate_id, consent, graph):
    artifact = make_artifact(session, candidate_id)
    obs = scored(candidate_id, DP, consent, [evidence_for(artifact)])
    obs.concept_id = "concept:dynamic_programing"  # one 'm'

    with pytest.raises(UnknownConcept):
        record(session, obs, ontology=graph)


def test_no_consent_no_write(session, candidate_id, consent, graph):
    """FR-4.20 / AC-4.11. Not a warning, not a log line."""
    artifact = make_artifact(session, candidate_id)
    consent.revoked_at = NOW
    session.add(consent)
    session.commit()

    with pytest.raises(NoConsent):
        record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    assert session.get(Mastery, (candidate_id, DP)) is None


def test_unresolvable_evidence_raises(session, candidate_id, consent, graph):
    """§12 adversarial: an observation whose evidence names nothing must raise,
    not be stored with a broken reference nobody notices until the drawer."""
    ghost = EvidenceRef(
        kind="span",
        session_id=uuid.uuid4(),
        span=EvidenceSpan(
            artifact_type="transcript",
            artifact_id=uuid.uuid4(),
            start=0,
            end=4,
            quote="gone",
        ),
        checksum=sha256_hex("gone"),
    )
    with pytest.raises(UnresolvableEvidence):
        record(session, scored(candidate_id, DP, consent, [ghost]), ontology=graph)


def test_tombstoned_evidence_still_records(session, candidate_id, consent, graph):
    """EC-4.9. Retention deleting a recording must not erase a student's
    history: the observation stays, the number stays, the drawer says why."""
    artifact = make_artifact(session, candidate_id, tombstoned=True)
    ref = EvidenceRef(
        kind="artifact",
        session_id=artifact.session_id,
        artifact_id=artifact.id,
        checksum=artifact.checksum,
    )
    result = record(session, scored(candidate_id, DP, consent, [ref]), ontology=graph)
    assert result.applied is True


def test_replaying_an_observation_moves_mastery_once(session, candidate_id, consent, graph):
    """EC-4.14, FR-4.25, AC-4.14. The uuid5 id is what makes §10's replay queue
    a fallback rather than a corruption path."""
    artifact = make_artifact(session, candidate_id)
    obs = scored(candidate_id, DP, consent, [evidence_for(artifact)])

    first = record(session, obs, ontology=graph)
    theta_after_first = session.get(Mastery, (candidate_id, DP)).theta

    second = record(session, obs, ontology=graph)

    assert first.applied is True
    assert second.applied is False and second.reason == "duplicate"
    assert session.get(Mastery, (candidate_id, DP)).theta == theta_after_first
    assert session.get(Mastery, (candidate_id, DP)).n_direct == 1


def test_the_observation_id_is_stable_across_processes(candidate_id, consent):
    """A caller that derives a different id produces a "new" observation on
    every replay, which is exactly the corruption the hash prevents."""
    turn = uuid.uuid4()
    ref = EvidenceRef(
        kind="artifact", session_id=uuid.uuid4(), artifact_id=uuid.uuid4(), checksum="x"
    )
    one = scored(candidate_id, DP, consent, [ref], turn_id=turn, session_id=uuid.UUID(int=1))
    two = scored(candidate_id, DP, consent, [ref], turn_id=turn, session_id=uuid.UUID(int=1))
    assert store.observation_id(one) == store.observation_id(two)


def test_a_batch_is_one_transaction(session, candidate_id, consent, graph):
    """M13 emits several observations per turn; §11's 60 ms budget is per call."""
    artifact = make_artifact(session, candidate_id)
    ref = evidence_for(artifact)
    batch = [
        scored(candidate_id, DP, consent, [ref]),
        scored(candidate_id, RECURSION, consent, [ref]),
    ]
    results = record_batch(session, batch, ontology=graph)

    assert [r.applied for r in results] == [True, True]
    assert session.get(Mastery, (candidate_id, DP)) is not None
    assert session.get(Mastery, (candidate_id, RECURSION)) is not None


def test_a_bad_observation_fails_the_whole_batch_before_anything_lands(
    session, candidate_id, consent, graph
):
    """Validation for all of them BEFORE anything is written, so a bad third
    observation cannot leave the first two committed and the caller unsure what
    happened."""
    artifact = make_artifact(session, candidate_id)
    good = scored(candidate_id, DP, consent, [evidence_for(artifact)])
    bad = scored(candidate_id, DP, consent, [evidence_for(artifact)])
    bad.concept_id = "concept:nonsense"

    with pytest.raises(UnknownConcept):
        record_batch(session, [good, bad], ontology=graph)

    assert session.get(Mastery, (candidate_id, DP)) is None


def test_the_outbox_is_drained_after_commit(session, candidate_id, consent, graph):
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    events = session.exec(select(OutboxEvent)).all()
    assert events, "a mastery change must publish an event"
    assert all(e.delivered_at is not None for e in events)
    assert events[0].topic == "mastery.updated"


# ── propagation (§6.4) ────────────────────────────────────────────────────


def test_success_transfers_up_to_prerequisites(session, candidate_id, consent, graph):
    """You cannot do DP without recursion, so a correct DP answer is real, if
    indirect, evidence about recursion."""
    artifact = make_artifact(session, candidate_id)
    result = record(
        session,
        scored(candidate_id, DP, consent, [evidence_for(artifact)], correct=True),
        ontology=graph,
    )

    assert RECURSION in result.propagated_to
    recursion = session.get(Mastery, (candidate_id, RECURSION))
    assert recursion.theta > 0
    assert recursion.n_direct == 0
    assert recursion.n_propagated == 1


def test_failure_widens_dependents_without_lowering_them(session, candidate_id, consent, graph):
    """THE most important rule in this module. Failing recursion does not prove
    you cannot do DP — it proves we should check, and widening SE is what makes
    the selector go and check.

    DP is measured FIRST, because that is the only case where the rule has
    anything to do — see the test below.
    """
    artifact = make_artifact(session, candidate_id)
    record(
        session,
        scored(candidate_id, DP, consent, [evidence_for(artifact)], turn_id=uuid.UUID(int=11)),
        ontology=graph,
    )
    before = session.get(Mastery, (candidate_id, DP))
    theta_before, se_before = before.theta, before.se

    record(
        session,
        scored(
            candidate_id,
            RECURSION,
            consent,
            [evidence_for(artifact)],
            correct=False,
            turn_id=uuid.UUID(int=12),
        ),
        ontology=graph,
    )

    after = session.get(Mastery, (candidate_id, DP))
    assert after.theta == pytest.approx(theta_before), "failure must never lower an estimate"
    assert after.se > se_before, "failure must widen uncertainty, so the selector re-checks"
    assert after.n_direct == before.n_direct


def test_failure_propagation_into_an_untested_concept_is_a_no_op(
    session, candidate_id, consent, graph
):
    """And it creates NOTHING, which is the part that matters.

    An untested concept is already at the prior SD, so there is no uncertainty
    left to add — you cannot know less than nothing. Creating a row anyway
    would put a `not_tested` bar on the student's map that they never
    generated, backed by a belief with no observation behind it: AC-4.1 broken
    by the very code that exists to keep it.
    """
    artifact = make_artifact(session, candidate_id)
    record(
        session,
        scored(candidate_id, RECURSION, consent, [evidence_for(artifact)], correct=False),
        ontology=graph,
    )

    assert session.get(Mastery, (candidate_id, DP)) is None
    assert session.get(Mastery, (candidate_id, "concept:backtracking")) is None


def test_a_purely_propagated_concept_reads_as_not_tested(session, candidate_id, consent, graph):
    """FR-4.24, EC-4.16. No sixth state, no Rule 3 hole: if nobody asked you
    about it, we have not measured it, however much its neighbours imply."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    recursion = session.get(Mastery, (candidate_id, RECURSION))
    view = evaluate(
        theta=recursion.theta,
        se=recursion.se,
        n_direct=recursion.n_direct,
        last_evidence_at=recursion.last_evidence_at,
    )
    assert view.state is MasteryState.not_tested
    assert view.mastery_p is None


def test_propagation_writes_real_observations(session, candidate_id, consent, graph):
    """AC-4.1 on M04's OWN write path. Without a row, propagation moves a number
    with nothing behind it and the drawer has nothing to render."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    derived = session.exec(
        select(Observation).where(Observation.kind == "propagated")
    ).all()
    assert derived
    for row in derived:
        assert row.evidence, "a derived observation carries the source's evidence"
        assert row.source_concept_id == DP
        assert row.counts_toward_n_direct is False
        assert row.theta_eligible is False


def test_a_never_tested_neighbour_is_queued_for_a_real_check(session, candidate_id, consent, graph):
    """§6.9 reason='propagated_unverified'. Inheriting a belief is a reason to
    go and ask, not a reason to stop asking."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    queued = session.exec(
        select(RetestQueueItem).where(RetestQueueItem.reason == "propagated_unverified")
    ).all()
    assert {q.concept_id for q in queued} >= {RECURSION}


def test_lifetime_propagation_is_capped(session, candidate_id, consent, graph):
    """A hundred adjacent successes must not walk a never-tested concept to
    "strong" without anyone ever asking the student a question about it."""
    for index in range(25):
        artifact = make_artifact(session, candidate_id)
        record(
            session,
            scored(
                candidate_id,
                DP,
                consent,
                [evidence_for(artifact)],
                session_id=uuid.UUID(int=index + 100),
                turn_id=uuid.uuid4(),
                observed_at=NOW + timedelta(days=index),
            ),
            ontology=graph,
        )

    recursion = session.get(Mastery, (candidate_id, RECURSION))
    assert recursion.theta_propagated_total <= LIFETIME_CAP + 1e-9
    assert recursion.n_direct == 0


def test_propagation_does_not_propagate(session, candidate_id, consent, graph):
    """Two hops is the limit, enforced by not re-entering rather than by a
    counter somebody can get wrong."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    derived = session.exec(select(Observation).where(Observation.kind == "propagated")).all()
    assert all(row.hops <= 2 for row in derived)


# ── retraction (FR-4.26) ─────────────────────────────────────────────────


def test_retraction_recomputes_rather_than_compensating(session, candidate_id, consent, graph):
    """An inverse update leaves two wrong rows in the ledger and a right answer
    nobody can derive from either."""
    artifact = make_artifact(session, candidate_id)
    first = record(
        session,
        scored(
            candidate_id,
            DP,
            consent,
            [evidence_for(artifact)],
            correct=True,
            turn_id=uuid.UUID(int=7),
        ),
        ontology=graph,
    )
    record(
        session,
        scored(
            candidate_id,
            DP,
            consent,
            [evidence_for(artifact)],
            correct=True,
            turn_id=uuid.UUID(int=8),
        ),
        ontology=graph,
    )
    before = session.get(Mastery, (candidate_id, DP)).theta

    after = store.retract(session, first.observation_id, "student flagged the item", ontology=graph)

    assert after is not None
    assert after.n_direct == 1
    assert after.theta < before
    assert session.get(Observation, first.observation_id).retracted_at is not None


def test_recompute_matches_a_serial_replay(session, candidate_id, consent, graph):
    """§12 adversarial: the stored posterior must equal what replaying the
    surviving observations produces. If it does not, some path is compensating
    instead of recomputing."""
    artifact = make_artifact(session, candidate_id)
    for index in range(4):
        record(
            session,
            scored(
                candidate_id,
                DP,
                consent,
                [evidence_for(artifact)],
                correct=index % 2 == 0,
                turn_id=uuid.UUID(int=200 + index),
            ),
            ontology=graph,
        )
    stored = session.get(Mastery, (candidate_id, DP))
    theta_before, se_before = stored.theta, stored.se

    replayed = store.recompute(session, candidate_id, DP, ontology=graph)

    assert replayed.theta == pytest.approx(theta_before, abs=1e-9)
    assert replayed.se == pytest.approx(se_before, abs=1e-9)
