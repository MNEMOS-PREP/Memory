"""The API surface (§7).

The interesting assertions are about SHAPE rather than status codes: five other
modules read these responses, and the fields that carry "we do not know" are
the ones that must not quietly become numbers.
"""

from __future__ import annotations

import uuid

from backend_M04_Skill_Graph_Memory.store import record

from .conftest import evidence_for, make_artifact, scored

DP = "concept:dynamic_programming"


def test_health_is_what_every_other_module_probes(client):
    """`module.json` in every dependent repo probes `/health`, and M15 ships
    that probe today. Without it M04 reads as permanently down and every
    student sees "Your preparation — needs M04, which isn't running"."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["module"] == "M04"
    assert body["ontology_version"]


def test_deps_says_this_module_is_a_root(client):
    body = client.get("/v1/deps").json()
    assert body["dependencies"] == []
    assert body["degraded"] == []


def test_status_reports_the_ontology_and_whether_it_was_reviewed(client):
    body = client.get("/status").json()
    assert body["id"] == "M04"
    assert body["ontology"]["concepts"] == 120
    assert body["ontology"]["faculty_reviewed"] is False


def test_concepts_are_public_and_filterable(client):
    body = client.get("/v1/concepts", params={"domain": "communication"}).json()
    assert body["count"] == 120
    assert all(c["domain"] == "communication" for c in body["concepts"])
    assert len(body["concepts"]) == 15


def test_one_concept_carries_its_neighbourhood(client):
    body = client.get(f"/v1/concepts/{DP}").json()
    assert body["name"] == "Dynamic Programming"
    assert any(p["concept_id"] == "concept:recursion" for p in body["prerequisites"])
    assert any(u["concept_id"] == "concept:knapsack" for u in body["unlocks"])


def test_an_unknown_concept_is_a_404(client):
    assert client.get("/v1/concepts/concept:nope").status_code == 404


def test_resolve_reports_what_it_could_not_match(client):
    body = client.post(
        "/v1/concepts/resolve", json={"labels": ["DP", "hash map", "blockchain"]}
    ).json()

    assert body["resolved"]["DP"] == DP
    assert body["resolved"]["hash map"] == "concept:hashing"
    assert body["resolved"]["blockchain"] is None
    assert body["unresolved"] == ["blockchain"]


def test_mastery_separates_measured_from_untested(client, session, candidate_id, consent, graph):
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    body = client.get(f"/v1/candidates/{candidate_id}/mastery").json()

    measured = {row["concept_id"] for row in body["measured"]}
    assert DP in measured
    assert body["not_yet_tested"]["count"] > 100
    assert body["totals"]["in_ontology"] == 120


def test_the_evidence_drawer_answers_why(client, session, candidate_id, consent, graph):
    """Rule 3's escape hatch. Every mastery value is tappable, and what it shows
    is the answers behind it — including the ones that did NOT move it."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    body = client.get(f"/v1/candidates/{candidate_id}/mastery/{DP}/evidence").json()

    assert body["observations"]
    first = body["observations"][0]
    assert first["evidence"]
    assert first["moved_the_estimate"] is True
    assert body["bkt_p_known"] is not None


def test_a_propagated_concept_explains_its_inheritance(
    client, session, candidate_id, consent, graph
):
    """EC-4.16: it renders `not_tested`, and the drawer says where the number
    came from — which is the sentence that makes the honesty useful rather than
    just correct."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    body = client.get(
        f"/v1/candidates/{candidate_id}/mastery/concept:recursion/evidence"
    ).json()

    notes = [o.get("note", "") for o in body["observations"]]
    assert any("inherited from" in note for note in notes)


def test_disputing_a_value_queues_a_retest_and_says_so(
    client, session, candidate_id, consent, graph
):
    """§2.4. It never argues back. Being wrong occasionally is survivable;
    being wrong and unaccountable is not."""
    artifact = make_artifact(session, candidate_id)
    record(session, scored(candidate_id, DP, consent, [evidence_for(artifact)]), ontology=graph)

    body = client.post(
        f"/v1/candidates/{candidate_id}/mastery/{DP}/dispute",
        json={"reason": "I solved this in the round"},
    ).json()

    assert body["retest_id"]
    assert "next session" in body["message"]

    queued = client.get(f"/v1/candidates/{candidate_id}/retests").json()["retests"]
    assert any(item["concept_id"] == DP and item["reason"] == "dispute" for item in queued)
    assert all(item["bypass_freshness"] for item in queued if item["reason"] == "dispute")


def test_bottlenecks_says_why_when_there_is_nothing_to_say(client, candidate_id):
    """"No bottleneck" and "we could not work it out" are different messages,
    and the card renders neither by guessing."""
    body = client.get(f"/v1/candidates/{candidate_id}/bottlenecks").json()
    assert body["bottlenecks"] == []
    assert body["reason"]


def test_posting_observations_rejects_a_mismatched_candidate(
    client, session, candidate_id, consent
):
    artifact = make_artifact(session, candidate_id)
    obs = scored(candidate_id, DP, consent, [evidence_for(artifact)])

    response = client.post(
        f"/v1/candidates/{uuid.uuid4()}/observations",
        json={"observations": [obs.model_dump(mode="json")]},
    )
    assert response.status_code == 400


def test_posting_a_batch_returns_a_result_per_observation(
    client, session, candidate_id, consent
):
    artifact = make_artifact(session, candidate_id)
    payload = {
        "observations": [
            scored(candidate_id, DP, consent, [evidence_for(artifact)]).model_dump(mode="json"),
            scored(
                candidate_id, "concept:greedy", consent, [evidence_for(artifact)]
            ).model_dump(mode="json"),
        ]
    }
    response = client.post(f"/v1/candidates/{candidate_id}/observations", json=payload)

    assert response.status_code == 200
    assert [r["applied"] for r in response.json()] == [True, True]


def test_an_unresolvable_evidence_ref_is_a_422_with_a_reason(
    client, session, candidate_id, consent
):
    """Not a 500, and not a silent accept: a producer that believes a number
    moved when it did not is worse off than one that got an error."""
    obs = scored(
        candidate_id,
        DP,
        consent,
        [
            {
                "kind": "artifact",
                "session_id": str(uuid.uuid4()),
                "artifact_id": str(uuid.uuid4()),
                "checksum": "deadbeef",
            }
        ],
    )
    response = client.post(
        f"/v1/candidates/{candidate_id}/observations",
        json={"observations": [obs.model_dump(mode="json")]},
    )
    assert response.status_code == 422
    assert "evidence" in response.json()["detail"]


def test_service_endpoints_401_without_the_shared_secret(client, candidate_id, monkeypatch):
    """§7: the check is one dependency, and it is tested. M04 holds every belief
    the platform has about a student."""
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")

    unauthenticated = client.get(
        "/v1/skill-graph/theta", params={"candidate": str(candidate_id), "concepts": "DP"}
    )
    assert unauthenticated.status_code == 401

    authenticated = client.get(
        "/v1/skill-graph/theta",
        params={"candidate": str(candidate_id), "concepts": "DP"},
        headers={"X-Service-Secret": "s3cret"},
    )
    assert authenticated.status_code == 200


def test_a_student_cannot_read_another_students_record(client, candidate_id, monkeypatch):
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")

    response = client.get(
        f"/v1/candidates/{candidate_id}/mastery",
        headers={"X-Candidate-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 403
