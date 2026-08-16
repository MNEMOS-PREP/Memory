"""Run the full mis-specification grid and the cold-start wash-out.

    python -m backend_M04_Skill_Graph_Memory.jobs.simulate
    python -m backend_M04_Skill_Graph_Memory.jobs.simulate --students 500 --sessions 10

Offline, seeded, no database. The test suite runs the same cells at a smaller
cohort so CI stays quick; this is what you run before writing a number down.

The output is deliberately a table rather than a pass/fail, because the useful
part is not "did it pass" — every cell has cleared its floor since the
estimators were finished. The useful part is `bias`, which is where the cost of
each mis-specification actually shows up: the graded-to-binary cell correlates
at 0.93 and is still half a logit low.
"""

from __future__ import annotations

import argparse

from ..priors import MAX_COHORT_PRIOR_GAP
from ..simulation import grid, wash_out


def main() -> int:
    parser = argparse.ArgumentParser(description="M04 simulation harness (spec §12)")
    parser.add_argument("--students", type=int, default=200)
    parser.add_argument("--sessions", type=int, default=6)
    parser.add_argument("--items", type=int, default=5, help="items per session")
    parser.add_argument("--seed", type=int, default=4)
    args = parser.parse_args()

    print(
        f"\n  Mis-specification grid — {args.students} students x {args.sessions} sessions "
        f"x {args.items} items, seed {args.seed}\n"
    )
    cells = grid(
        n_students=args.students,
        sessions=args.sessions,
        items_per_session=args.items,
        seed=args.seed,
    )
    for cell in cells:
        print(cell.row())
        print(f"       {cell.note}")

    print("\n  Cold-start wash-out — how much of a cohort prior survives\n")
    for gap, label in ((MAX_COHORT_PRIOR_GAP, "capped"), (2.0, "uncapped, for contrast")):
        print(f"    gap = {gap:.2f} logits ({label})")
        for result in wash_out(n_students=args.students, prior_gap=gap):
            mark = "washed out" if result.washed_out else "still showing"
            print(
                f"      n={result.n_observations}  remaining {result.remaining_gap:+.3f}  {mark}"
            )
        print()

    failed = [c for c in cells if not c.passed]
    if failed:
        print(f"  {len(failed)} cell(s) below floor — AC-4.4 is a gate.\n")
        return 1
    print("  All cells clear their floors (AC-4.4).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
