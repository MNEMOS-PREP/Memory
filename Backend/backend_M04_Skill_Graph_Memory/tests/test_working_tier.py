"""The working tier, the trajectory contract, and the student's rights.

Spec: §6.6 (tiers), FR-4.23 + AC-4.13 (pinning), §7 (trajectory, export,
delete), FR-4.18a/b/c.

These are the endpoints other modules consume, so most of what is asserted
here is a promise to somebody else: M06 gets a context that does not move
under it, M19 gets history drawn on the scale it was scored on, and a student
gets a delete that actually deletes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlmodel import select

from backend_M04_Skill_Graph_Memory import service, store
from backend_M04_Skill_Graph_Memory.models import (
    Mastery,
    MemoryFact,
    Observation,
    Purpose,
)

from .conftest import NOW, evidence_for, make_artifact, scored

DP = "concept:dynamic_programming"
RECURSION = "concept:recursion"
HASHING = "concept:hashing"


def _history(session, candidate_id, consent, graph, *, concepts=(DP, HASHING)):
    artifact = make_artifact(session, candidate_id)
    for i, concept in enumerate(concepts):
        for j in range(3):
            store.record(
                session,
                scored(
                    candidate_id,
                    concept,
                    consent,
                    [evidence_for(artifact)],
                    correct=(i + j) % 2 == 0,
                    observed_at=NOW + timedelta(days=i * 3 + j),
                ),
                ontology=graph,
            )
    return artifact


# ── the working tier ──────────────────────────────────────────────────────


def test_the_summary_carries_the_slots_m06_codes_against(
    session, candidate_id, consent, graph
):
    """Including the two M6 has not filled yet.

    `recent_sessions` and `facts` are present and empty on purpose. A consumer
    written against a shape that later GROWS a key has to change; an empty
    list is a promise and a missing key is a migration.
    """
    _history(session, candidate_id, consent, graph)
    summary = service.build_profile_summary(session, candidate_id, ontology=graph)

    assert set(summary.payload) >= {
        "candidate_id",
        "ontology_version",
        "measured_concepts",
        "weakest",
        "strongest",
        "bottlenecks",
        "retests",
        "recent_sessions",
        "facts",
    }
    assert summary.payload["measured_concepts"] > 0
    assert summary.stale is False


def test_the_summary_stays_inside_its_token_budget(session, candidate_id, consent, graph):
    """§11 — it is injected into every turn, so this is a per-turn cost."""
    _history(session, candidate_id, consent, graph)
    summary = service.build_profile_summary(session, candidate_id, ontology=graph)
    assert summary.token_estimate <= service.SUMMARY_TOKEN_BUDGET


def test_an_untested_concept_never_reaches_the_summary_as_a_number(
    session, candidate_id, consent, graph
):
    """Rule 2 at the tier an AGENT reads, which is the one that matters most:
    a number here becomes a sentence an interviewer says out loud."""
    _history(session, candidate_id, consent, graph)
    summary = service.build_profile_summary(session, candidate_id, ontology=graph)

    for entry in summary.payload["weakest"] + summary.payload["strongest"]:
        assert entry["mastery_p"] is not None
        assert entry["state"] != "not_tested"


@pytest.mark.gate
def test_ac_4_13_the_summary_is_byte_identical_for_the_life_of_a_session(
    session, candidate_id, consent, graph
):
    """AC-4.13 [GATE] — ten calls with `record()` interleaved.

    The failure this prevents is not cosmetic. Mutating prose mid-interview
    changes the interviewer's own context between its turns, and it
    invalidates M06's prompt cache on every observation — a real bill. The
    in-session movement is not lost; it reaches the interviewer through M05's
    selector reading live mastery, which is the channel meant to carry it.
    """
    artifact = _history(session, candidate_id, consent, graph)
    session_id = uuid.uuid4()

    first = service.pinned_profile_summary(session, candidate_id, session_id)
    for i in range(10):
        store.record(
            session,
            scored(
                candidate_id,
                DP,
                consent,
                [evidence_for(artifact)],
                correct=i % 2 == 0,
                observed_at=NOW + timedelta(days=30 + i),
            ),
            ontology=graph,
        )
        again = service.pinned_profile_summary(session, candidate_id, session_id)
        assert again == first, f"the pinned summary moved on call {i + 1}"


def test_the_next_session_sees_the_new_evidence(session, candidate_id, consent, graph):
    """The other half of AC-4.13, and the half that makes it honest rather
    than merely stable: pinning must not mean frozen forever."""
    artifact = _history(session, candidate_id, consent, graph)
    first = service.pinned_profile_summary(session, candidate_id, uuid.uuid4())

    for i in range(6):
        store.record(
            session,
            scored(
                candidate_id,
                RECURSION,
                consent,
                [evidence_for(artifact)],
                correct=False,
                observed_at=NOW + timedelta(days=40 + i),
            ),
            ontology=graph,
        )

    second = service.pinned_profile_summary(session, candidate_id, uuid.uuid4())
    assert second["payload"] != first["payload"]


def test_a_session_id_cannot_be_reused_for_another_candidate(
    session, candidate_id, consent, graph
):
    """Returning the stored snapshot would hand a third party someone else's
    profile — the same class of leak AC-4.10 exists to prevent."""
    _history(session, candidate_id, consent, graph)
    session_id = uuid.uuid4()
    service.pinned_profile_summary(session, candidate_id, session_id)

    with pytest.raises(service.SessionCandidateMismatch):
        service.pinned_profile_summary(session, uuid.uuid4(), session_id)


# ── trajectory (the M19 contract) ─────────────────────────────────────────


def test_trajectory_is_served_from_what_was_true_then(
    session, candidate_id, consent, graph
):
    """Points come from the stored `theta_after`, not from re-running the
    estimator: a chart recomputed under today's arithmetic would silently
    redraw history on a scale the student was never scored on."""
    _history(session, candidate_id, consent, graph)
    out = service.trajectory(session, candidate_id, ontology=graph)

    assert out["series"], out["reason"]
    stored = {
        (o.concept_id, o.theta_after)
        for o in session.exec(
            select(Observation).where(Observation.theta_eligible == True)  # noqa: E712
        ).all()
    }
    for series in out["series"]:
        for point in series["points"]:
            assert (series["concept_id"], point["theta"]) in stored


def test_trajectory_says_why_it_is_empty(session, candidate_id, graph):
    """"No data" and "never scored" are the same JSON otherwise, and M19
    renders them differently."""
    out = service.trajectory(session, candidate_id, ontology=graph)
    assert out["series"] == []
    assert out["reason"]


def test_trajectory_filters_to_one_concept(session, candidate_id, consent, graph):
    _history(session, candidate_id, consent, graph)
    out = service.trajectory(session, candidate_id, concept_id=DP, ontology=graph)
    assert [s["concept_id"] for s in out["series"]] == [DP]


# ── the student's rights ──────────────────────────────────────────────────


def test_export_carries_every_table(session, candidate_id, consent, graph):
    """FR-4.18a — an export a student cannot check against what we store is a
    gesture, not a right."""
    _history(session, candidate_id, consent, graph)
    out = service.export_memory(session, candidate_id)

    assert set(out) >= {
        "consent",
        "mastery",
        "observations",
        "artifacts",
        "facts",
        "retests",
        "disputes",
    }
    assert out["observations"] and out["mastery"] and out["consent"]


def test_a_hard_delete_leaves_nothing_to_rebuild_from(
    session, candidate_id, consent, graph
):
    """FR-4.18b. The episodic tier is what every number is re-derivable from,
    so a flag would mean the numbers could come back — and §8 promises they
    cannot."""
    _history(session, candidate_id, consent, graph)
    service.delete_memory(session, candidate_id)

    assert session.exec(
        select(Observation).where(Observation.candidate_id == candidate_id)
    ).all() == []
    assert session.exec(
        select(Mastery).where(Mastery.candidate_id == candidate_id)
    ).all() == []


def test_a_hard_delete_keeps_the_consent_record(session, candidate_id, consent, graph):
    """Marked revoked, not removed: "when did this person withdraw" is a
    question the ethics annexe has to be able to answer."""
    _history(session, candidate_id, consent, graph)
    service.delete_memory(session, candidate_id)

    rows = service.export_memory(session, candidate_id)["consent"]
    assert rows and all(r["revoked_at"] is not None for r in rows)


def test_revoking_research_leaves_practice_history_alone(
    session, candidate_id, consent, graph
):
    """FR-4.18c — a student leaving the study keeps their practice history."""
    _history(session, candidate_id, consent, graph)
    session.add(
        MemoryFact(
            candidate_id=candidate_id,
            tier="semantic",
            kind="story",
            display_sentence="a fact held for research",
            purpose=Purpose.research,
        )
    )
    session.commit()

    out = service.revoke_purpose(session, candidate_id, Purpose.research)

    assert out["facts_removed"] == 1
    assert out["purge_due_at"]
    assert session.exec(
        select(Observation).where(Observation.candidate_id == candidate_id)
    ).all()


def test_revoking_practice_is_refused_as_a_half_measure(
    session, candidate_id, consent, graph
):
    """It would be a deletion. Calling it a revocation leaves the student
    believing something narrower happened than what did."""
    _history(session, candidate_id, consent, graph)
    with pytest.raises(service.CannotRevokePractice):
        service.revoke_purpose(session, candidate_id, Purpose.practice)
