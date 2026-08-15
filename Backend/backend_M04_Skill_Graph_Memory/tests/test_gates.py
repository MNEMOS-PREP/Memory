"""Release gates — spec §13.

Any failure here is a P0. These are not "tests that happen to be important";
they are the module's contract with the other eighteen, written so that a
change which breaks one cannot merge quietly.

    AC-4.1   every mastery change traces to a resolvable evidence ref
    AC-4.2   `not_tested` is never a number, and never 0.0
    AC-4.3   no mastery write outside record() — grep AND runtime guard
    AC-4.10  no failure signature reachable from any non-self endpoint
    AC-4.11  no observation or fact written without an active consent record
    AC-4.12  distilled facts pass all four screens        [M6 — not yet built]
    AC-4.13  profile-summary is byte-identical per session [M5 — not yet built]
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from ai_core.evidence import EvidenceState, resolve
from ai_core.evidence import EvidenceRef as Ref
from sqlalchemy import update as sql_update
from sqlmodel import select

from backend_M04_Skill_Graph_Memory import service, store
from backend_M04_Skill_Graph_Memory.models import Mastery, Observation
from backend_M04_Skill_Graph_Memory.store import (
    DbArtifactStore,
    MasteryWriteOutsideRecordPath,
    NoConsent,
    record,
)

from .conftest import evidence_for, make_artifact, scored

DP = "concept:dynamic_programming"
PACKAGE = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.gate


# ── AC-4.1 ────────────────────────────────────────────────────────────────


def test_ac_4_1_every_observation_traces_to_resolvable_evidence(
    session, candidate_id, consent, graph
):
    """100%, INCLUDING the propagated ones — which is the entire reason §6.4
    writes real rows instead of quietly adjusting a number."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    rows = session.exec(select(Observation)).all()
    assert rows

    artifact_store = DbArtifactStore(session)
    for row in rows:
        assert row.evidence, f"{row.kind} observation with no evidence at all"
        for raw in row.evidence:
            result = resolve(Ref.model_validate(raw), artifact_store)
            assert result.state is EvidenceState.resolved, (
                f"{row.kind} observation cites evidence that does not resolve: {result.detail}"
            )


def test_ac_4_1_a_mastery_row_never_exists_without_an_observation(
    session, candidate_id, consent, graph
):
    """A mixed history, deliberately: successes propagate up and failures
    propagate down, and it is the DOWN branch that used to create a row and
    then decline to touch it.

    Failure propagation to a never-tested concept cannot widen an SE that is
    already at the prior — so the step is skipped, and for a while the row was
    created before we knew that. The result was a `not_tested` bar the student
    never generated, sitting in the mastery API with nothing behind it: AC-4.1
    broken by the code that exists to keep it.
    """
    artifact = make_artifact(session, candidate_id)
    for index, (concept, correct) in enumerate(
        [
            ("concept:arrays", True),
            ("concept:hashing", True),
            ("concept:recursion", False),
            ("concept:recursion", False),
            (DP, False),
        ]
    ):
        record(
            session,
            scored(
                candidate_id,
                concept,
                consent,
                [evidence_for(artifact)],
                correct=correct,
                turn_id=uuid.UUID(int=400 + index),
            ),
            ontology=graph,
        )

    rows = session.exec(select(Mastery)).all()
    assert rows
    for mastery in rows:
        observations = session.exec(
            select(Observation).where(
                Observation.candidate_id == mastery.candidate_id,
                Observation.concept_id == mastery.concept_id,
            )
        ).all()
        assert observations, f"{mastery.concept_id} has a belief with nothing behind it"


# ── AC-4.2 ────────────────────────────────────────────────────────────────


def test_ac_4_2_not_tested_is_never_zero_at_the_api(client, session, candidate_id, consent, graph):
    """A student who was never asked about graphs did not score zero on graphs.

    The failure this guards is not hypothetical: every bar-chart component and
    every JSON serialiser defaults a missing number to 0, and a 0 renders as a
    full-width empty bar that reads as "you are terrible at this".
    """
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    body = client.get(f"/v1/candidates/{candidate_id}/mastery").json()

    for row in body["measured"]:
        if row["state"] in ("not_tested", "emerging"):
            assert row["mastery_p"] is None, f"{row['concept_id']} put a number on nothing"

    # And the untested majority is a COUNT, not 108 rows of zero.
    assert body["not_yet_tested"]["count"] > 0
    assert isinstance(body["not_yet_tested"]["names"], list)


def test_ac_4_2_an_unresolvable_topic_comes_back_unresolved_not_zero(
    client, session, candidate_id, consent, graph
):
    """EC-4.18. A silent zero is a confident claim of ignorance, and it is
    Rule 2 violated at an API boundary — the one place four other modules
    would inherit it from."""
    body = client.get(
        "/v1/skill-graph/theta",
        params={"candidate": str(candidate_id), "concepts": "blockchain,dynamic programming"},
    ).json()

    assert "blockchain" in body["unresolved"]
    for entry in body["per_topic"].values():
        if entry["state"] in ("not_tested", "emerging"):
            assert entry["mastery_p"] is None
        if entry["state"] == "not_tested":
            assert entry["theta"] is None, "0.0 on a logit scale reads as 'exactly average'"


# ── AC-4.3 ────────────────────────────────────────────────────────────────


def test_ac_4_3_runtime_guard_blocks_a_mastery_write_outside_record(session, candidate_id):
    """The half a CI grep cannot do: eighteen other repos import this package,
    and a grep of THIS repo cannot see what they do with it."""
    statement = sql_update(Mastery).where(Mastery.candidate_id == candidate_id).values(theta=3.0)

    with pytest.raises(MasteryWriteOutsideRecordPath):
        store._persist_mastery(session, statement)


def test_ac_4_3_no_mastery_update_outside_the_store(session):
    """The other half: nothing in this package writes that table except
    `store.py`. Cheap, and it catches the refactor that "just needed one small
    update" in a service function."""
    offenders: list[str] = []
    pattern = re.compile(r"(sql_update\(\s*Mastery|UPDATE\s+m04_concept_mastery)", re.IGNORECASE)

    for path in PACKAGE.rglob("*.py"):
        if path.name in ("store.py",) or "tests" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(PACKAGE)))

    assert offenders == [], f"mastery written outside store.py: {offenders}"


# ── AC-4.10 ───────────────────────────────────────────────────────────────


def test_ac_4_10_no_endpoint_exposes_a_failure_signature(client):
    """Not filtered — ABSENT. The cheapest way to keep this gate is to have
    nothing to leak: no route returns one, so no future filter can be forgotten.

    A placement cell must never see "abandoned before using hint". That is a
    behavioural description of one moment, and in a hiring decision it becomes
    a trait.
    """
    paths = client.get("/openapi.json").json()["paths"]

    for path, methods in paths.items():
        assert "failure" not in path.lower() and "signature" not in path.lower(), path
        for spec in methods.values():
            assert "FailureSignature" not in str(spec.get("responses", {}))


def test_ac_4_10_candidate_routes_all_identify_the_caller(client):
    """Every route under /v1/candidates/{id}/ resolves WHO is asking before it
    touches a row — as the student themselves (`require_self`) or as another
    module holding the shared secret (`require_service`).

    §7's prose says "self only" and its own table then marks
    `POST .../observations` as `service`; the table wins, because M13 posts
    with no student present. The gate is therefore that no candidate route
    bypasses identification, not that they all take the same path.
    """
    from backend_M04_Skill_Graph_Memory.router import require_self, require_service, router

    guards = {require_self, require_service}
    for route in router.routes:
        if "/v1/candidates/" not in getattr(route, "path", ""):
            continue
        dependants = {d.call for d in route.dependant.dependencies}
        assert dependants & guards, f"{route.path} does not identify the caller"


# ── AC-4.11 ───────────────────────────────────────────────────────────────


def test_ac_4_11_nothing_is_written_without_active_consent(session, candidate_id, consent, graph):
    artifact = make_artifact(session, candidate_id)

    stranger = uuid.uuid4()
    obs = scored(candidate_id, DP, consent, [evidence_for(artifact)])
    obs.consent_id = stranger

    with pytest.raises(NoConsent):
        record(session, obs, ontology=graph)

    assert session.exec(select(Observation)).all() == []


def test_ac_4_11_every_stored_observation_names_a_live_consent_record(
    session, candidate_id, consent, graph
):
    from backend_M04_Skill_Graph_Memory.models import ConsentRecord

    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    for row in session.exec(select(Observation)).all():
        record_row = session.get(ConsentRecord, row.consent_id)
        assert record_row is not None and record_row.candidate_id == row.candidate_id


# ── the ontology's own gate ───────────────────────────────────────────────


def test_the_shipped_ontology_has_no_lint_errors(graph):
    """FR-4.2 and the alias contract, on the real file. A cycle makes
    propagation loop; a colliding alias silently sends a student's topic to
    another concept's belief."""
    errors = [issue for issue in graph.lint() if issue.severity == "error"]
    assert errors == [], "; ".join(f"[{i.code}] {i.message}" for i in errors)


def test_the_bottleneck_query_agrees_with_what_the_card_would_render(
    session, candidate_id, consent, graph
):
    """§6.8's own requirement: a unit test asserts the number this query returns
    equals the number `BottleneckCard` renders. They diverged in the previous
    draft because the SQL excluded untested targets and the mock did not."""
    artifact = make_artifact(session, candidate_id)
    for index, concept in enumerate(
        ["concept:dynamic_programming", "concept:backtracking", "concept:dp_on_trees"]
    ):
        for attempt in range(2):
            record(
                session,
                scored(
                    candidate_id,
                    concept,
                    consent,
                    [evidence_for(artifact)],
                    correct=False,
                    a=1.6,
                    b=-1.0,
                    turn_id=uuid.UUID(int=900 + index * 10 + attempt),
                ),
                ontology=graph,
            )

    found = service.bottlenecks(session, candidate_id)

    # It must actually FIND something. Asserting only properties of the rows
    # returned is how this passed for an afternoon while the query matched
    # nothing at all: `:cid` was bound as a hyphenated string against a
    # CHAR(32) column, so every mastery join failed silently and every concept
    # looked untested.
    assert found, "a student weak on DP, backtracking and tree DP has a bottleneck"

    for entry in found:
        assert entry["blocks"] >= 2, "a blocker that blocks one thing is not a bottleneck"
        assert not graph.get(entry["concept_id"]).foundational_floor, (
            '"work on variables" is insulting advice — the floor belongs in this query'
        )


def test_a_brand_new_student_is_told_nothing_rather_than_something_invented(
    session, candidate_id, graph
):
    """EC-4.1. Every concept in the ontology is untested for a new student, so
    without a measured anchor every root looks like a bottleneck and the card
    confidently names one. Nothing measured, nothing to say."""
    assert service.bottlenecks(session, candidate_id) == []
