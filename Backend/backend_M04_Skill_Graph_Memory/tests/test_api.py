"""The API surface (§7).

The interesting assertions are about SHAPE rather than status codes: five other
modules read these responses, and the fields that carry "we do not know" are
the ones that must not quietly become numbers.
"""

from __future__ import annotations

import hashlib
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
    assert body["ontology"]["concepts"] == 156
    assert body["ontology"]["faculty_reviewed"] is False


def test_concepts_are_public_and_filterable(client):
    body = client.get("/v1/concepts", params={"domain": "communication"}).json()
    assert body["count"] == 156
    assert all(c["domain"] == "communication" for c in body["concepts"])
    assert len(body["concepts"]) == 15


def test_one_concept_carries_its_neighbourhood(client):
    body = client.get(f"/v1/concepts/{DP}").json()
    assert body["name"] == "Dynamic Programming"
    assert any(p["concept_id"] == "concept:recursion" for p in body["prerequisites"])
    assert any(u["concept_id"] == "concept:knapsack" for u in body["unlocks"])
    # Named, so the Learn panel never shows an id.
    assert {"concept_id": "concept:recursion", "name": "Recursion"}.items() <= next(
        p for p in body["prerequisites"] if p["concept_id"] == "concept:recursion"
    ).items()


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
    assert body["totals"]["in_ontology"] == 156


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


def test_every_route_another_module_calls_refuses_a_browser(session):
    """Platform_Core v0.12.0's shared check, finding the routes from the OpenAPI
    document — a service route added later is checked by this test too.

    Until 2026-10-02 these were OPEN whenever no secret was configured, which
    on every laptop was always: the skill graph's write path answered any
    browser. An unset secret now means the machine secret, never "open".
    """
    from ai_core.db import get_session
    from ai_core.testing import assert_service_only
    from fastapi.testclient import TestClient

    from backend_M04_Skill_Graph_Memory.app import app

    app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(app) as bare:
            checked = assert_service_only(bare, app, expect_at_least=4)
    finally:
        app.dependency_overrides.clear()
    assert ("POST", "/v1/candidates/{candidate_id}/observations") in checked
    assert ("GET", "/v1/skill-graph/theta") in checked


def test_theta_needs_the_student_as_well_as_the_secret(session, candidate_id, monkeypatch):
    """Platform_Core v0.11.0: the guard reads the query. Until then the secret
    alone opened `/skill-graph/theta?candidate=` for ANY student — M15 called it
    without saying who for — because the router guard read only the path.

    A caller with the secret is a module; the forwarded headers say which
    student it is acting for, and that student must be the one asked about.
    """
    from ai_core.db import get_session
    from fastapi.testclient import TestClient

    from backend_M04_Skill_Graph_Memory.app import app

    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")
    app.dependency_overrides[get_session] = lambda: session
    params = {"candidate": str(candidate_id), "concepts": "DP"}
    secret = {"X-Service-Secret": "s3cret"}
    try:
        with TestClient(app) as bare:  # no default identity, unlike `client`
            alone = bare.get("/v1/skill-graph/theta", params=params, headers=secret)
            other = bare.get(
                "/v1/skill-graph/theta",
                params=params,
                headers={**secret, "X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())},
            )
            theirs = bare.get(
                "/v1/skill-graph/theta",
                params=params,
                headers={**secret, "X-Role": "student", "X-Candidate-Id": str(candidate_id)},
            )
    finally:
        app.dependency_overrides.clear()
    assert alone.status_code == 403, "the secret alone still opens any student's beliefs"
    assert other.status_code == 403
    assert theirs.status_code == 200


def test_a_student_cannot_read_another_students_record(client, candidate_id, monkeypatch):
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")

    response = client.get(
        f"/v1/candidates/{candidate_id}/mastery",
        headers={"X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 403


# ── the working tier, trajectory and rights (§7) ──────────────────────────


def test_profile_summary_requires_a_session_to_pin_to(client, candidate_id):
    """An unpinned summary is a different object with a different guarantee.
    Letting one endpoint return either, depending on a query parameter, is how
    M06 ends up believing it has a stable context when it does not."""
    response = client.get(f"/v1/candidates/{candidate_id}/profile-summary")
    assert response.status_code == 422


def test_profile_summary_is_a_service_endpoint(client, candidate_id, monkeypatch):
    """It is injected into an agent's context, not rendered to a student."""
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")
    params = {"session_id": str(uuid.uuid4())}

    assert (
        client.get(f"/v1/candidates/{candidate_id}/profile-summary", params=params).status_code
        == 401
    )
    ok = client.get(
        f"/v1/candidates/{candidate_id}/profile-summary",
        params=params,
        headers={"X-Service-Secret": "s3cret"},
    )
    assert ok.status_code == 200
    assert ok.json()["pinned"] is True


def test_a_pinned_summary_reuses_the_session_it_was_built_for(client, candidate_id):
    session_id = str(uuid.uuid4())
    first = client.get(
        f"/v1/candidates/{candidate_id}/profile-summary", params={"session_id": session_id}
    ).json()
    second = client.get(
        f"/v1/candidates/{candidate_id}/profile-summary", params={"session_id": session_id}
    ).json()
    assert first == second

    stranger = client.get(
        f"/v1/candidates/{uuid.uuid4()}/profile-summary", params={"session_id": session_id}
    )
    assert stranger.status_code == 409


def test_trajectory_returns_a_named_reason_when_it_is_empty(client, candidate_id):
    """M19 renders "no data" and "never scored" differently, so it is told
    which one this is rather than left to infer it from an empty list."""
    body = client.get(f"/v1/candidates/{candidate_id}/trajectory").json()
    assert body["series"] == []
    assert body["reason"]


def test_export_and_delete_are_the_students_own(client, candidate_id, monkeypatch):
    """FR-4.18a/b — reachable by the student, and by nobody else."""
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")
    stranger = {"X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())}

    assert client.get(f"/v1/candidates/{candidate_id}/export", headers=stranger).status_code == 403
    assert (
        client.delete(f"/v1/candidates/{candidate_id}/memory", headers=stranger).status_code == 403
    )

    body = client.get(
        f"/v1/candidates/{candidate_id}/export",
        headers={"X-Role": "student", "X-Candidate-Id": str(candidate_id)},
    ).json()
    assert "observations" in body and "consent" in body


def test_an_artifact_can_be_registered_and_then_cited(client, candidate_id, monkeypatch):
    """The seam that made a scored interview move nothing.

    `m04_artifacts` is what every evidence ref resolves against, and nothing
    could write to it — so M13's observations came back "evidence does not
    resolve" and were rejected, one per concept, on every turn.
    """
    monkeypatch.delenv("M04_SERVICE_SECRET", raising=False)
    session_id, turn_id = uuid.uuid4(), uuid.uuid4()
    body = {
        "candidate_id": str(candidate_id),
        "session_id": str(session_id),
        "turn_id": str(turn_id),
        "content": "Keys are hashed to a bucket index, so you jump straight to the bucket.",
    }
    created = client.post(f"/v1/candidates/{candidate_id}/artifacts", json=body)
    assert created.status_code == 201
    out = created.json()

    # The id a citer already uses. M13 puts `artifact_id=turn_id` on every span
    # it quotes, so anything else here resolves to absent however principled.
    assert out["artifact_id"] == str(turn_id)
    assert out["checksum"] == hashlib.sha256(body["content"].encode()).hexdigest()

    # Immutable, and idempotent: a retry is not a second transcript, and the
    # character offsets already quoted into it do not move.
    again = client.post(
        f"/v1/candidates/{candidate_id}/artifacts", json={**body, "content": "something else"}
    )
    assert again.status_code == 200
    assert again.json()["checksum"] == out["checksum"]


def test_registering_an_artifact_for_somebody_else_is_refused(client, candidate_id, monkeypatch):
    monkeypatch.delenv("M04_SERVICE_SECRET", raising=False)
    refused = client.post(
        f"/v1/candidates/{candidate_id}/artifacts",
        json={
            "candidate_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "content": "x",
        },
    )
    assert refused.status_code == 400


def test_consent_can_be_granted_and_read_back(client, candidate_id):
    """FR-4.20 from the other side. The table has been enforced since day one
    and nothing could query it, so M06 reported "consent isn't recorded" on
    every session and M13 emitted no observations at all."""
    me = {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}
    assert client.get(f"/v1/candidates/{candidate_id}/consent", headers=me).json() == []

    created = client.post(
        f"/v1/candidates/{candidate_id}/consent", json={"purpose": "practice"}, headers=me
    )
    assert created.status_code == 201
    granted = created.json()
    assert granted["active"] is True and granted["purpose"] == "practice"

    # The id an observation cites, found by the purpose it was granted for.
    found = client.get(
        f"/v1/candidates/{candidate_id}/consent?purpose=practice", headers=me
    ).json()
    assert [row["consent_id"] for row in found] == [granted["consent_id"]]


def test_granting_the_same_consent_twice_is_one_consent(client, candidate_id):
    """A student opening a second interview has not agreed to anything new,
    and a module retrying a session start must not leave two rows nobody can
    tell apart."""
    me = {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}
    first = client.post(f"/v1/candidates/{candidate_id}/consent", json={}, headers=me)
    again = client.post(f"/v1/candidates/{candidate_id}/consent", json={}, headers=me)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["consent_id"] == first.json()["consent_id"]
    assert len(client.get(f"/v1/candidates/{candidate_id}/consent", headers=me).json()) == 1


def test_a_revoked_consent_is_not_offered_to_a_writer(client, candidate_id):
    """Revocation already worked; what is new is that a reader now sees it.
    The row stays — "when did they withdraw" is an ethics question — but it is
    no longer the consent a write may cite."""
    me = {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}
    client.post(
        f"/v1/candidates/{candidate_id}/consent", json={"purpose": "research"}, headers=me
    )
    client.delete(f"/v1/candidates/{candidate_id}/memory?purpose=research", headers=me)

    assert (
        client.get(f"/v1/candidates/{candidate_id}/consent?purpose=research", headers=me).json()
        == []
    )
    history = client.get(f"/v1/candidates/{candidate_id}/consent", headers=me).json()
    assert [row["active"] for row in history] == [False]
    assert history[0]["revoked_at"] is not None


def test_consent_is_the_students_own_and_a_purpose_must_exist(client, candidate_id):
    me = {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}
    stranger = {"X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())}
    assert (
        client.get(f"/v1/candidates/{candidate_id}/consent", headers=stranger).status_code == 403
    )
    assert (
        client.post(
            f"/v1/candidates/{candidate_id}/consent", json={}, headers=stranger
        ).status_code
        == 403
    )
    refused = client.post(
        f"/v1/candidates/{candidate_id}/consent", json={"purpose": "marketing"}, headers=me
    )
    assert refused.status_code == 400
    assert "marketing" in refused.json()["detail"]


def test_revoking_practice_is_refused_with_a_reason(client, candidate_id):
    """400 with the sentence that says what to call instead — a student who
    meant "delete everything" must not be told "done" for something narrower."""
    response = client.delete(
        f"/v1/candidates/{candidate_id}/memory", params={"purpose": "practice"}
    )
    assert response.status_code == 400
    assert "without ?purpose" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────
#  THE STUDENT'S PROFILE  (what they said they are preparing for)
# ─────────────────────────────────────────────────────────────


def _as(candidate_id) -> dict:
    return {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}


def test_a_profile_is_empty_before_the_student_says_anything(client, candidate_id):
    body = client.get(f"/v1/candidates/{candidate_id}/profile", headers=_as(candidate_id)).json()
    assert body["onboarded_at"] is None
    assert body["drives"] == [] and body["display_name"] == ""
    assert body["weekly_goal"] == 3


def test_the_welcome_step_saves_the_answers_and_stamps_once(client, candidate_id):
    me = _as(candidate_id)
    first = client.put(
        f"/v1/candidates/{candidate_id}/profile",
        json={
            "display_name": "Asha",
            "target_role": "Software engineer",
            "companies": [{"name": "TCS"}],
            "drives": [
                {"label": "Infosys SP", "date": "2026-11-02"},
                {
                    "label": "TCS Digital",
                    "date": "2026-10-16",
                    "drive_id": "11111111-1111-4111-8111-111111111111",
                },
            ],
            "onboarded": True,
        },
        headers=me,
    )
    assert first.status_code == 200, first.text
    stamped = first.json()["onboarded_at"]
    assert stamped
    # Soonest first: the countdown reads the first row.
    assert [d["label"] for d in first.json()["drives"]] == ["TCS Digital", "Infosys SP"]
    assert first.json()["drives"][0]["drive_id"] == "11111111-1111-4111-8111-111111111111"

    # Settings saves one field and keeps the rest — and the stamp.
    again = client.put(
        f"/v1/candidates/{candidate_id}/profile",
        json={"weekly_goal": 5, "onboarded": True},
        headers=me,
    ).json()
    assert again["weekly_goal"] == 5
    assert again["display_name"] == "Asha"
    assert again["onboarded_at"] == stamped


def test_a_bad_reminder_time_or_goal_is_refused(client, candidate_id):
    me = _as(candidate_id)
    url = f"/v1/candidates/{candidate_id}/profile"
    assert client.put(url, json={"reminder_time": "25:00"}, headers=me).status_code == 422
    assert client.put(url, json={"weekly_goal": 9}, headers=me).status_code == 422
    assert client.put(url, json={"reminder_time": "19:30"}, headers=me).status_code == 200


def test_the_profile_is_the_students_own_and_goes_with_export_and_delete(
    client, candidate_id, monkeypatch
):
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")
    me = _as(candidate_id)
    url = f"/v1/candidates/{candidate_id}/profile"
    stranger = _as(uuid.uuid4())
    assert client.get(url, headers=stranger).status_code == 403
    assert client.put(url, json={"display_name": "x"}, headers=stranger).status_code == 403

    client.put(url, json={"display_name": "Asha"}, headers=me)
    exported = client.get(f"/v1/candidates/{candidate_id}/export", headers=me).json()
    assert exported["student_profile"][0]["display_name"] == "Asha"

    client.delete(f"/v1/candidates/{candidate_id}/memory", headers=me)
    assert client.get(url, headers=me).json()["display_name"] == ""
