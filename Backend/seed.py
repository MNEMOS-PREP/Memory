"""Seed a demo student, so this module demos on its own.

    .venv\\Scripts\\python seed.py

§10's last row is a platform rule, not a convenience: *M13 may not exist yet,
so episodic writes come from a fixture seam and M04 runs and demos standalone.*
This file is that seam. It is also the honest example of how to write to this
module, which is why it does something slower than it needs to:

**it goes through `record()` for every observation.** It could insert mastery
rows directly and finish in a millisecond. It does not, because a seed script
that bypasses the write path is the first place someone copies the wrong
pattern from — and because going through `record()` means the seeded data has
real evidence behind it and the evidence drawer works on the demo.

Idempotent by construction: the uuid5 observation id means running it twice
leaves exactly the same beliefs (FR-4.25).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from ai_core.db import create_all, engine, get_session
from ai_core.evidence import EvidenceRef, EvidenceSpan, sha256_hex
from ai_core.schema_repair import ensure_schema
from ai_core.timeutil import utcnow
from sqlmodel import Session, select

from backend_M04_Skill_Graph_Memory.models import Artifact, ConsentRecord, Purpose
from backend_M04_Skill_Graph_Memory.ontology import load
from backend_M04_Skill_Graph_Memory.service import sync_ontology
from backend_M04_Skill_Graph_Memory.store import ObservationIn, record_batch

#: Fixed, so the URLs in the README keep working and a second run updates the
#: same student instead of creating a stranger.
DEMO_CANDIDATE = uuid.UUID("4d0aa1c0-0000-4000-8000-000000000004")

NOW = utcnow()

# (concept, days ago, transcript, rubric level 0-4, item difficulty)
#
# A deliberately uneven history: strong on the fundamentals, breaking on
# recursion, and untouched on most of the ontology — which is what makes the
# map, the bottleneck card and the "not tested" majority all visible at once.
HISTORY = [
    (
        "concept:arrays",
        21,
        "I'd use a hash map for the complement lookup, so it's one pass and O(n) time.",
        4,
        -0.6,
    ),
    (
        "concept:arrays",
        21,
        "Sorting first would be O(n log n), which is worse than the hash map version here.",
        4,
        -0.2,
    ),
    (
        "concept:hashing",
        21,
        "A hash set gives average O(1) membership, worst case O(n) if everything collides.",
        3,
        -0.3,
    ),
    (
        "concept:hashing",
        14,
        "You'd rehash when the load factor crosses about 0.75, which amortises to O(1).",
        3,
        0.2,
    ),
    (
        "concept:two_pointers",
        14,
        "Left and right walking inwards, because the array is already sorted.",
        3,
        -0.1,
    ),
    (
        "concept:two_pointers",
        14,
        "Fast and slow pointers detect the cycle without extra space.",
        2,
        0.4,
    ),
    (
        "concept:recursion",
        7,
        "I think the base case is when n is zero... or maybe one, I'd have to try it.",
        1,
        -0.4,
    ),
    (
        "concept:recursion",
        7,
        "I'm not sure how the call stack unwinds here, I'd need to trace through it.",
        0,
        -0.1,
    ),
    (
        "concept:sorting",
        7,
        "Merge sort is stable and always n log n; quicksort is faster but n^2 worst case.",
        3,
        0.0,
    ),
    (
        "concept:sorting",
        3,
        "Quickselect gets you the kth element in expected linear time.",
        2,
        0.6,
    ),
    (
        "concept:dynamic_programming",
        3,
        "I'd memoise the subproblem results, but I couldn't work out the state here.",
        1,
        0.3,
    ),
    (
        "concept:dynamic_programming",
        3,
        "Tabulation would be bottom up, so I'd fill the smallest cases first.",
        1,
        0.5,
    ),
]


def seed() -> None:
    create_all()
    for change in ensure_schema(engine):
        print(f"  schema: added {change}")

    graph = load()
    session: Session = next(get_session())
    try:
        sync_ontology(session, graph)

        consent = session.exec(
            select(ConsentRecord).where(ConsentRecord.candidate_id == DEMO_CANDIDATE)
        ).first()
        if consent is None:
            consent = ConsentRecord(
                candidate_id=DEMO_CANDIDATE,
                purpose=Purpose.practice,
                granted_at=NOW - timedelta(days=30),
            )
            session.add(consent)
            session.commit()

        observations: list[ObservationIn] = []
        for index, (concept_id, days_ago, text, level, difficulty) in enumerate(HISTORY):
            observed_at = NOW - timedelta(days=days_ago)
            # One session per day of history, so the local-dependence cap and
            # BKT's between-session transit both have something real to act on.
            session_id = uuid.uuid5(DEMO_CANDIDATE, f"session-{days_ago}")
            turn_id = uuid.uuid5(DEMO_CANDIDATE, f"turn-{index}")
            artifact_id = uuid.uuid5(DEMO_CANDIDATE, f"artifact-{index}")

            if session.get(Artifact, artifact_id) is None:
                session.add(
                    Artifact(
                        id=artifact_id,
                        candidate_id=DEMO_CANDIDATE,
                        session_id=session_id,
                        turn_id=turn_id,
                        artifact_type="transcript",
                        content=text,
                        checksum=sha256_hex(text),
                        created_at=observed_at,
                    )
                )
                session.commit()

            quote = text[: min(len(text), 48)]
            observations.append(
                ObservationIn(
                    candidate_id=DEMO_CANDIDATE,
                    concept_id=concept_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    evidence=[
                        EvidenceRef(
                            kind="span",
                            session_id=session_id,
                            turn_id=turn_id,
                            span=EvidenceSpan(
                                artifact_type="transcript",
                                artifact_id=artifact_id,
                                start=0,
                                end=len(quote),
                                quote=quote,
                            ),
                            checksum=sha256_hex(text),
                        )
                    ],
                    kind="answer_scored",
                    # GRM, because most items are rubric-scored and collapsing a
                    # 5-level rubric to right/wrong throws away most of the
                    # information (§6.3).
                    response_model="grm",
                    raw_category=level,
                    n_categories=5,
                    outcome=level / 4.0,
                    item={
                        "question_id": str(uuid.uuid5(DEMO_CANDIDATE, f"q-{index}")),
                        "irt_model": "grm",
                        "a": 1.3,
                        "b": [
                            difficulty - 1.2,
                            difficulty - 0.4,
                            difficulty + 0.4,
                            difficulty + 1.2,
                        ],
                        "se_b": 0.25,
                    },
                    source_dimension_key="correctness",
                    consent_id=consent.id,
                    observed_at=observed_at,
                )
            )

        results = record_batch(session, observations, ontology=graph)
        applied = sum(1 for r in results if r.applied)

        print(f"\n  candidate     {DEMO_CANDIDATE}")
        print(f"  ontology      v{graph.version}, {len(graph)} concepts, reviewed={graph.reviewed}")
        print(f"  observations  {applied} written, {len(results) - applied} already there")
        print("\n  Try:")
        print(f"    curl http://127.0.0.1:8104/v1/candidates/{DEMO_CANDIDATE}/mastery")
        print(f"    curl http://127.0.0.1:8104/v1/candidates/{DEMO_CANDIDATE}/bottlenecks")
        print(
            "    curl http://127.0.0.1:8104/v1/candidates/"
            f"{DEMO_CANDIDATE}/mastery/concept:recursion/evidence"
        )
        print()
    finally:
        session.close()


if __name__ == "__main__":
    seed()
