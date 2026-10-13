"""The curricula a student picks at sign-in, and what each course teaches.

Two kinds of test. The built files are checked against the PDFs they came
from at the points the PDFs are hard (a row split across two lines, a code
the layout text pairs with the wrong title, a syllabus that wraps "references"
onto a line of its own), so a rebuild that regresses one of them fails here.
And the profile routes are checked to refuse what a planner must never act
on: a course code the curriculum does not have.
"""

from __future__ import annotations

import uuid

from backend_M04_Skill_Graph_Memory import curricula as curricula_module
from backend_M04_Skill_Graph_Memory.jobs.curricula import (
    Context,
    _ends_syllabus,
    _fragment,
    concepts_for,
)

CSE = "amrita-btech-cse-2023"
AIE = "amrita-btech-aie-2022"


def _as(candidate_id) -> dict:
    return {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}


def _concepts(course: dict) -> set[str]:
    return {c["id"] for c in course["concepts"]}


# ── the built files ──────────────────────────────────────────────────────────


def test_both_programmes_load_with_eight_semesters_and_only_real_concepts(graph):
    curricula_module.reset_cache()
    loaded = curricula_module.load_curricula()
    assert {CSE, AIE} <= set(loaded)
    for curriculum in loaded.values():
        assert [s["number"] for s in curriculum.document["semesters"]] == list(range(1, 9))
        for course in curriculum.courses.values():
            for concept in course["concepts"]:
                assert concept["id"] in graph, (course["code"], concept["id"])
                assert concept["name"] == graph.get(concept["id"]).name


def test_the_cells_not_the_layout_text_pair_codes_with_titles():
    """`pdftotext -layout` puts "Database Management Systems" beside 23CSE203;
    the table cells, and the syllabus page, say Data Structures."""
    cse = curricula_module.load_curricula()[CSE]
    third = {c["code"]: c["title"] for c in cse.document["semesters"][2]["courses"]}
    assert third["23CSE203"] == "Data Structures and Algorithms"
    assert third["23CSE202"] == "Database Management Systems"


def test_a_row_split_over_two_lines_is_one_course():
    """Semester I of the CSE PDF: the title on one row, its code on the next."""
    cse = curricula_module.load_curricula()[CSE]
    first = {c["code"]: c for c in cse.document["semesters"][0]["courses"]}
    assert first["23CSE101"]["title"] == "Computational Problem Solving"
    assert first["23CSE101"]["category"] == "CSE"
    assert first["23ENG101"]["title"] == "Technical Communication"


def test_elective_slots_and_baskets_are_kept_apart():
    cse = curricula_module.load_curricula()[CSE]
    fifth = cse.document["semesters"][4]
    assert [s["kind"] for s in fifth["slots"]] == ["professional", "professional"]
    baskets = {b["name"] for b in cse.document["electives"]}
    assert "Electives in Artificial Intelligence" in baskets
    # Offered to other branches, not to these students.
    assert not any("other branches" in b.casefold() for b in baskets)


def test_core_courses_map_to_what_their_syllabus_teaches():
    aie = curricula_module.load_curricula()[AIE]
    os_course = aie.courses["22AIE202"]
    assert {"concept:deadlocks", "concept:virtual_memory", "concept:page_replacement"} <= _concepts(
        os_course
    )
    deadlocks = next(c for c in os_course["concepts"] if c["id"] == "concept:deadlocks")
    assert deadlocks["matched"], "every concept carries the syllabus words behind it"
    # The units after a line reading just "references" were read too.
    assert {"concept:inheritance", "concept:exception_handling"} <= _concepts(
        aie.courses["22AIE111"]
    )


def test_a_course_with_no_technical_syllabus_maps_to_nothing():
    """Calculus says "functions"; chemistry says "acid"; neither is ours."""
    cse = curricula_module.load_curricula()[CSE]
    assert cse.courses["23MAT107"]["concepts"] == []  # Calculus
    assert all(not c["concepts"] for c in cse.courses.values() if c["code"].startswith("23CHY"))


# ── the build's own rules, on inputs small enough to read ────────────────────


def test_fragments_merge_by_the_fields_each_half_carries():
    ctx = Context("semester", "Semester 1", 1)
    for cells in (
        ["HUM", "", "3", "70:30"],  # category and credits, before their course
        ["", "23ENG101", "Technical Communication", "2-0-3"],
        ["", "23MAT107", "Calculus", "4", "70:30"],
        ["SCI", "3-0-2"],  # the rest of Calculus
        ["CSE", "Computational Problem Solving", "4", "70:30"],
        ["", "23CSE101", "3-0-2"],  # the code of the line above
    ):
        ctx.add(_fragment(cells))
    rows = {r.code: r for r in ctx.rows}
    assert set(rows) == {"23ENG101", "23MAT107", "23CSE101"}
    assert (rows["23ENG101"].category, rows["23ENG101"].credits) == ("HUM", "3")
    assert (rows["23MAT107"].category, rows["23MAT107"].ltp) == ("SCI", "3-0-2")
    assert rows["23CSE101"].title == "Computational Problem Solving"


def test_a_header_row_is_not_a_course():
    assert _fragment(["Cat", "Code", "Title", "L T P", "Credit"]) is None
    assert _fragment(["", "", "Total (14 L + 1 T + 13 P = 28 hrs)", "", "21"]) is None


def test_the_syllabus_ends_at_a_heading_not_at_a_wrapped_word():
    assert _ends_syllabus("Textbooks/References")
    assert _ends_syllabus("REFERENCES")
    assert not _ends_syllabus("references")


def test_a_generic_word_needs_its_domain_taught_by_phrase(graph):
    assert concepts_for("Limits, continuity and functions. Graphs of functions.", graph) == []
    operating = concepts_for(
        "Virtual memory, demand paging, page replacement. Deadlock avoidance and deadlocks.",
        graph,
    )
    ids = {c["id"] for c in operating}
    assert {"concept:virtual_memory", "concept:page_replacement", "concept:deadlocks"} <= ids


# ── the routes ───────────────────────────────────────────────────────────────


def test_the_curricula_are_listed_and_served(client):
    listed = client.get("/v1/curricula").json()
    assert {c["id"] for c in listed} >= {CSE, AIE}
    one = client.get(f"/v1/curricula/{AIE}")
    assert one.status_code == 200
    assert one.json()["semesters"][2]["courses"]
    assert client.get("/v1/curricula/nope").status_code == 404


def test_a_student_saves_their_semester_and_courses(client, candidate_id):
    url = f"/v1/candidates/{candidate_id}/profile"
    saved = client.put(
        url,
        json={"curriculum_id": AIE, "semester": 5, "courses": ["22AIE303", "22AIE304", "22AIE303"]},
        headers=_as(candidate_id),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["curriculum_id"], body["semester"]) == (AIE, 5)
    assert body["courses"] == ["22AIE303", "22AIE304"]  # one of each, order kept


def test_a_course_the_curriculum_does_not_have_is_refused(client, candidate_id):
    url = f"/v1/candidates/{candidate_id}/profile"
    me = _as(candidate_id)
    wrong = client.put(url, json={"curriculum_id": AIE, "courses": ["23CSE203"]}, headers=me)
    assert wrong.status_code == 422
    assert "23CSE203" in wrong.text
    assert client.put(url, json={"curriculum_id": "nope"}, headers=me).status_code == 422
    assert client.put(url, json={"courses": ["22AIE303"]}, headers=me).status_code == 422


def test_changing_programme_clears_the_old_programmes_courses(client, candidate_id):
    url = f"/v1/candidates/{candidate_id}/profile"
    me = _as(candidate_id)
    client.put(url, json={"curriculum_id": AIE, "semester": 5, "courses": ["22AIE303"]}, headers=me)
    moved = client.put(url, json={"curriculum_id": CSE}, headers=me).json()
    assert moved["courses"] == []
    # Saving something else keeps them.
    client.put(url, json={"courses": ["23CSE301"]}, headers=me)
    kept = client.put(url, json={"weekly_goal": 5}, headers=me).json()
    assert kept["courses"] == ["23CSE301"] and kept["semester"] == 5


def test_a_semester_can_be_cleared(client, candidate_id):
    url = f"/v1/candidates/{candidate_id}/profile"
    me = _as(candidate_id)
    client.put(url, json={"semester": 7}, headers=me)
    cleared = client.put(url, json={"semester": None, "year": "Graduated"}, headers=me).json()
    assert cleared["semester"] is None and cleared["year"] == "Graduated"
    assert client.put(url, json={"semester": 9}, headers=me).status_code == 422


def test_another_student_cannot_read_the_courses(client, candidate_id):
    url = f"/v1/candidates/{candidate_id}/profile"
    assert client.get(url, headers=_as(uuid.uuid4())).status_code == 403


# ── coursework: what a planner reads ─────────────────────────────────────────


def test_coursework_is_this_semester_ticked_then_every_earlier_semester(client, candidate_id):
    me = _as(candidate_id)
    client.put(
        f"/v1/candidates/{candidate_id}/profile",
        json={"curriculum_id": AIE, "semester": 3, "courses": ["22AIE202"]},  # Operating Systems
        headers=me,
    )
    body = client.get(f"/v1/candidates/{candidate_id}/coursework", headers=me).json()
    current = [c for c in body["courses"] if c["current"]]
    assert [c["code"] for c in current] == ["22AIE202"]
    # Semesters 1-2 are assumed sat; 3's unticked courses (DSA 2) are not.
    codes = {c["code"] for c in body["courses"]}
    assert {"22AIE112", "22AIE101"} <= codes  # DSA 1, C programming
    assert "22AIE203" not in codes  # DSA 2: this semester, not ticked
    assert "22AIE213" not in codes  # Machine Learning: semester 4, not yet
    studied = body["studied_concepts"]
    assert studied[0] in {c for c in current[0]["concepts"]}, "this semester comes first"
    assert "concept:deadlocks" in studied
    assert "concept:decision_trees" not in studied
    assert len(studied) == len(set(studied))


def test_coursework_is_empty_without_a_semester_and_everything_once_graduated():
    aie = curricula_module.load_curricula()[AIE]
    assert curricula_module.coursework(None, 5, "", [])["studied_concepts"] == []
    assert curricula_module.coursework(aie, None, "", [])["studied_concepts"] == []
    graduated = curricula_module.coursework(aie, None, "Graduated", [])
    assert "concept:decision_trees" in graduated["studied_concepts"]  # ML, semester 4
    assert not any(c["current"] for c in graduated["courses"])


def test_another_student_cannot_read_the_coursework(client, candidate_id):
    url = f"/v1/candidates/{candidate_id}/coursework"
    assert client.get(url, headers=_as(uuid.uuid4())).status_code == 403
