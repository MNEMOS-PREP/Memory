"""The programmes a student can say they are on, and what each course teaches.

Read from `packages/knowledge/curricula/*.json`, which `jobs/curricula.py`
builds from the college's own curriculum PDFs (2026-10-13). Loaded once, like
the ontology, because the welcome step and every profile write read it and it
changes only when the college publishes a new curriculum.

Two checks at load, both because the files outlive the ontology they were
mapped onto:

* every concept id must still be in the ontology. One that is not (a concept
  renamed since the build) is dropped and logged, never served: a course that
  points a practice session at a concept M05 cannot resolve is a 422 in the
  middle of a student's first interview;
* each concept is NAMED here, so a screen can say "covers Deadlocks, Paging"
  without fetching the ontology to translate ids.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .ontology import Ontology, load

log = logging.getLogger(__name__)

CURRICULA_RELATIVE = Path("packages/knowledge/curricula")


@dataclass(frozen=True)
class Curriculum:
    id: str
    document: dict
    #: code -> the course, from any semester or elective basket.
    courses: dict[str, dict] = field(default_factory=dict)

    def summary(self) -> dict:
        doc = self.document
        return {
            "id": self.id,
            "name": doc["name"],
            "short": doc["short"],
            "institution": doc["institution"],
            "curriculum_year": doc.get("curriculum_year"),
            "semesters": len(doc["semesters"]),
        }


def default_dir(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / "packages" / "knowledge").is_dir():
            return parent / CURRICULA_RELATIVE
    raise FileNotFoundError(f"no packages/knowledge above {here}")


def _named(course: dict, graph: Ontology, curriculum_id: str) -> dict:
    kept = []
    for concept in course.get("concepts", []):
        if concept["id"] not in graph:
            log.warning(
                "%s %s: concept %s is not in the ontology; dropped",
                curriculum_id,
                course["code"],
                concept["id"],
            )
            continue
        kept.append({**concept, "name": graph.get(concept["id"]).name})
    return {**course, "concepts": kept}


def parse(document: dict, graph: Ontology) -> Curriculum:
    cid = document["id"]
    semesters = [
        {**sem, "courses": [_named(c, graph, cid) for c in sem["courses"]]}
        for sem in document["semesters"]
    ]
    electives = [
        {**basket, "courses": [_named(c, graph, cid) for c in basket["courses"]]}
        for basket in document.get("electives", [])
    ]
    doc = {**document, "semesters": semesters, "electives": electives}
    courses = {c["code"]: c for sem in semesters for c in sem["courses"]}
    for basket in electives:
        for course in basket["courses"]:
            courses.setdefault(course["code"], course)
    return Curriculum(id=cid, document=doc, courses=courses)


_cache: dict[str, Curriculum] | None = None


def load_curricula(directory: Path | None = None, *, force: bool = False) -> dict[str, Curriculum]:
    """Every built curriculum, by id. An unreadable file is skipped and
    logged: one bad programme must not take sign-in away from the others."""
    global _cache
    if _cache is not None and not force:
        return _cache
    graph = load()
    found: dict[str, Curriculum] = {}
    target = directory or default_dir()
    for path in sorted(target.glob("*.json")) if target.is_dir() else []:
        try:
            curriculum = parse(json.loads(path.read_text(encoding="utf-8")), graph)
        except Exception as exc:  # noqa: BLE001 — every failure gets the same answer
            log.error("curriculum %s could not be read: %s", path.name, exc)
            continue
        found[curriculum.id] = curriculum
    _cache = found
    return found


def reset_cache() -> None:
    global _cache
    _cache = None


def coursework(
    curriculum: Curriculum | None,
    semester: int | None,
    year: str,
    ticked: list[str],
) -> dict:
    """What a student's courses have taught so far, for a planner.

    This semester's courses are the ones the student ticked (electives
    included); every earlier semester's are the curriculum's, because a
    student in semester 5 has sat 1-4. A graduate has sat all eight. Only
    courses that teach a concept are listed, and `studied_concepts` is their
    union in that order — this semester first, then back through the earlier
    ones — so a planner that keeps the first few keeps what is freshest.

    Nothing is inferred beyond that: no curriculum, or no semester and not
    graduated, is an empty answer, and a planner then plans as it always did.
    """
    empty = {"semester": semester, "courses": [], "studied_concepts": []}
    if curriculum is None:
        return {"curriculum_id": "", **empty}
    semesters = curriculum.document["semesters"]
    if semester is not None:
        current = [curriculum.courses[code] for code in ticked if code in curriculum.courses]
        earlier = [s for s in semesters if s["number"] < semester]
    elif year == "Graduated":
        current, earlier = [], list(semesters)
    else:
        return {"curriculum_id": curriculum.id, **empty}

    def row(course: dict, number: int | None, now: bool) -> dict:
        return {
            "code": course["code"],
            "title": course["title"],
            "semester": number,
            "current": now,
            "concepts": [c["id"] for c in course["concepts"]],
        }

    courses = [row(c, semester, True) for c in current]
    for past in sorted(earlier, key=lambda s: -s["number"]):
        courses += [row(c, past["number"], False) for c in past["courses"]]
    courses = [c for c in courses if c["concepts"]]
    studied = list(dict.fromkeys(cid for c in courses for cid in c["concepts"]))
    return {
        "curriculum_id": curriculum.id,
        "semester": semester,
        "courses": courses,
        "studied_concepts": studied,
    }
