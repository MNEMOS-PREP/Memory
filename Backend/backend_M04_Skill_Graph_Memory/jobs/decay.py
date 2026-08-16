"""Queue a re-test for every concept that has decayed past the threshold.

    python -m backend_M04_Skill_Graph_Memory.jobs.decay --dry-run
    python -m backend_M04_Skill_Graph_Memory.jobs.decay
    python -m backend_M04_Skill_Graph_Memory.jobs.decay --candidate <uuid>

Nightly. §6.5's hand-off to M16, which existed as a function and as nothing
else: `service.sweep_decay()` had no caller anywhere — no route, no job, no
test — so in a running system a concept could decay indefinitely and never
reach the queue that is supposed to act on it. Read-path decay was always
live (`se_effective` and `stale` are computed per request, so the map greys
correctly); it was only the hand-off that was dormant.

This is deliberately a job and not a route. Decay is a function of the clock,
not of anyone asking, and a sweep that only runs when a student happens to
open a page is a sweep whose behaviour depends on traffic.
"""

from __future__ import annotations

import argparse
import uuid

from ai_core.db import engine
from ai_core.mastery import evaluate
from ai_core.timeutil import utcnow
from sqlmodel import Session, select

from .. import service
from ..models import Mastery
from ..ontology import load


def _name(graph, concept_id: str) -> str:
    return graph.get(concept_id).name if concept_id in graph else concept_id


def main() -> int:
    parser = argparse.ArgumentParser(description="M04 decay sweep (spec §6.5, §6.9)")
    parser.add_argument(
        "--candidate",
        type=uuid.UUID,
        default=None,
        help="one candidate; omit to sweep everybody",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be queued, write nothing",
    )
    args = parser.parse_args()

    graph = load()
    with Session(engine) as session:
        if args.dry_run:
            now = utcnow()
            statement = select(Mastery).where(Mastery.n_direct > 0)
            if args.candidate is not None:
                statement = statement.where(Mastery.candidate_id == args.candidate)

            would: list[str] = []
            for row in session.exec(statement).all():
                view = evaluate(
                    theta=row.theta,
                    se=row.se,
                    n_direct=row.n_direct,
                    last_evidence_at=row.last_evidence_at,
                    ever_displayed=row.ever_displayed,
                    now=now,
                )
                if view.retest_candidate:
                    would.append(
                        f"    {_name(graph, row.concept_id):34s} "
                        f"se {row.se:.2f} -> {view.se_effective:.2f}"
                    )
            print(f"\n  {len(would)} concept(s) would be queued\n")
            print("\n".join(would) or "    nothing has decayed past the threshold")
            print()
            return 0

        queued = service.sweep_decay(session, candidate_id=args.candidate)

    print(f"\n  {len(queued)} concept(s) queued for re-test\n")
    for concept_id in queued:
        print(f"    {_name(graph, concept_id)}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
