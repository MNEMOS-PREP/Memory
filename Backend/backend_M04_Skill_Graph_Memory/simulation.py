"""The simulation harness — synthetic students with abilities we know.

Spec: §12 (test plan), §14 milestone M3, AC-4.4.

**Built before the estimators are finished, on purpose.** The previous revision
of the spec put this last, sharing a day with a meeting that depended on
someone else's calendar, and shipped two constants that were provably wrong:
a decay curve that could never fire, and a BKT transit that made wrong answers
raise mastery. Neither was visible to the tests written for them. This harness
is what catches that class of error in an afternoon instead of in a pilot.

**The mis-specification grid is the point, not the matched cell.** Simulating
from the model you then fit tests your quadrature, not your estimator — it is
a sanity check that will pass on almost any implementation, and reporting it
alone is how a paper gets its first reviewer objection. So every cell below
simulates under one set of assumptions and scores under a different one, which
is the situation the module is actually in: real rubric data is graded, real
sessions are correlated, real item parameters are stale.

Pure Python and seeded throughout: no numpy, no database, no randomness that
cannot be reproduced from the seed printed in the output. A harness whose
results move between runs cannot tell you whether your estimator changed.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ai_core.mastery import SE_PRIOR

from .estimators import Response, grm_category_probabilities, p_2pl, update

#: Every default here is a knob the grid turns. They are gathered rather than
#: scattered so a cell reads as "the matched case, except X".
DEFAULT_STUDENTS = 200
DEFAULT_SESSIONS = 6
DEFAULT_ITEMS_PER_SESSION = 5


@dataclass
class Item:
    a: float
    b: float
    #: GRM thresholds, derived from `b` so a graded item and a binary item of
    #: the same difficulty are comparable.
    thresholds: list[float] = field(default_factory=list)

    def graded(self) -> list[float]:
        return self.thresholds or [self.b - 1.2, self.b - 0.4, self.b + 0.4, self.b + 1.2]


@dataclass
class CellResult:
    """One cell of the grid. Every number here goes in the paper."""

    name: str
    simulated_under: str
    scored_under: str
    #: Pearson correlation between true and recovered ability.
    r: float
    #: Mean signed error. A cell can correlate beautifully and still be
    #: systematically half a logit low, and that is a different problem.
    bias: float
    rmse: float
    #: Empirical SD of the error divided by the mean SE the estimator claimed.
    #: Above 1 means we are reporting more certainty than we have.
    se_ratio: float
    n_students: int
    floor: float
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.r >= self.floor

    def row(self) -> str:
        mark = "ok " if self.passed else "FAIL"
        return (
            f"  {mark} {self.name:<20} {self.simulated_under:<14} -> {self.scored_under:<10} "
            f"r={self.r:.3f} (floor {self.floor:.2f})  bias={self.bias:+.3f}  "
            f"rmse={self.rmse:.3f}  se_ratio={self.se_ratio:.2f}"
        )


# ─────────────────────────────────────────────────────────────
#  POPULATION
# ─────────────────────────────────────────────────────────────


def normal_abilities(n: int, rng: random.Random, sd: float = 1.0) -> list[float]:
    return [rng.gauss(0.0, sd) for _ in range(n)]


def bimodal_abilities(n: int, rng: random.Random) -> list[float]:
    """A cohort that is genuinely two groups — which ours is.

    A branch where half the students have done competitive programming and half
    have not is not normally distributed around a single mean, and an estimator
    with a normal prior shrinks both tails toward a middle nobody occupies.
    """
    return [rng.gauss(-1.2 if rng.random() < 0.5 else 1.2, 0.5) for _ in range(n)]


def make_items(n: int, rng: random.Random) -> list[Item]:
    return [Item(a=rng.uniform(0.8, 2.0), b=rng.gauss(0.0, 1.0)) for _ in range(n)]


# ─────────────────────────────────────────────────────────────
#  RESPONSE GENERATION
# ─────────────────────────────────────────────────────────────


def respond_2pl(theta: float, item: Item, rng: random.Random) -> int:
    return 1 if rng.random() < p_2pl(theta, item.a, item.b) else 0


def respond_grm(theta: float, item: Item, rng: random.Random) -> int:
    """Sample a rubric level 0..4 from the graded response model."""
    probs = grm_category_probabilities(theta, item.a, item.graded())
    draw = rng.random()
    cumulative = 0.0
    for category, p in enumerate(probs):
        cumulative += p
        if draw <= cumulative:
            return category
    return len(probs) - 1


# ─────────────────────────────────────────────────────────────
#  RECOVERY
# ─────────────────────────────────────────────────────────────


def recover(
    sessions: list[list[Response]],
    *,
    prior_theta: float = 0.0,
    prior_se: float = SE_PRIOR,
) -> tuple[float, float]:
    """Replay a student's history the way `store.recompute` does.

    Session boundaries are respected, so the local-dependence cap resets per
    session rather than treating a year of history as one sitting. Getting this
    wrong makes every cell look worse than it is and sends you hunting a bug in
    the estimator.
    """
    theta, se = prior_theta, prior_se
    for session in sessions:
        for index, response in enumerate(session):
            posterior = update(theta, se, response, responses_this_session=index)
            theta, se = posterior.theta, posterior.se
    return theta, se


# ─────────────────────────────────────────────────────────────
#  THE GRID
# ─────────────────────────────────────────────────────────────


def run_cell(
    name: str,
    *,
    simulated_under: str,
    scored_under: str,
    floor: float,
    n_students: int = DEFAULT_STUDENTS,
    sessions: int = DEFAULT_SESSIONS,
    items_per_session: int = DEFAULT_ITEMS_PER_SESSION,
    seed: int = 4,
    bimodal: bool = False,
    session_effect_sd: float = 0.0,
    b_drift: float = 0.0,
    prior_offset: float = 0.0,
    note: str = "",
) -> CellResult:
    """Simulate a cohort under one set of assumptions, score under another."""
    rng = random.Random(seed)
    truths = bimodal_abilities(n_students, rng) if bimodal else normal_abilities(n_students, rng)

    recovered: list[float] = []
    claimed_ses: list[float] = []

    for student_index, true_theta in enumerate(truths):
        student_rng = random.Random(seed * 1000 + student_index)
        history: list[list[Response]] = []

        for _ in range(sessions):
            # A shared per-session perturbation is what local dependence IS:
            # the same stem, the same mood, the same interviewer, so five
            # answers in one sitting are not five independent draws.
            shift = student_rng.gauss(0.0, session_effect_sd) if session_effect_sd else 0.0
            items = make_items(items_per_session, student_rng)
            responses: list[Response] = []

            for item in items:
                effective = true_theta + shift
                if simulated_under == "grm":
                    category = respond_grm(effective, item, student_rng)
                else:
                    category = respond_2pl(effective, item, student_rng)

                # What the SCORER believes about the item, which is not always
                # what generated the response.
                scored_b = item.b * (1.0 + b_drift)
                if scored_under == "grm":
                    responses.append(
                        Response(
                            model="grm",
                            a=item.a,
                            b=[t * (1.0 + b_drift) for t in item.graded()],
                            category=category,
                            n_categories=5,
                        )
                    )
                else:
                    # Scoring graded data as binary: the collapse M05 §3.1
                    # Trap 2 warns about. A 3-of-4 becomes simply "correct".
                    binary = category if simulated_under != "grm" else int(category >= 3)
                    responses.append(
                        Response(model="2pl", a=item.a, b=scored_b, category=binary)
                    )
            history.append(responses)

        theta, se = recover(history, prior_theta=prior_offset)
        recovered.append(theta)
        claimed_ses.append(se)

    errors = [got - want for got, want in zip(recovered, truths, strict=True)]
    bias = sum(errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    empirical_sd = math.sqrt(sum((e - bias) ** 2 for e in errors) / max(1, len(errors) - 1))
    mean_se = sum(claimed_ses) / len(claimed_ses)

    return CellResult(
        name=name,
        simulated_under=simulated_under,
        scored_under=scored_under,
        r=pearson(truths, recovered),
        bias=bias,
        rmse=rmse,
        se_ratio=empirical_sd / mean_se if mean_se else float("inf"),
        n_students=n_students,
        floor=floor,
        note=note,
    )


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (vx * vy) if vx and vy else 0.0


def grid(**overrides) -> list[CellResult]:
    """§12's mis-specification grid. AC-4.4 reads this table.

    Floors are the spec's, not tuned to what the code happens to produce. A
    floor moved to make a build green is a floor that no longer means anything.
    """
    cells = [
        run_cell(
            "matched",
            simulated_under="2pl",
            scored_under="2pl",
            floor=0.90,
            note="sanity, not a result: this passes on almost any implementation",
            **overrides,
        ),
        run_cell(
            "model mis-spec",
            simulated_under="grm",
            scored_under="2pl",
            floor=0.80,
            note="graded data collapsed to right/wrong — the cost of NOT shipping GRM",
            **overrides,
        ),
        run_cell(
            "local dependence",
            simulated_under="2pl",
            scored_under="2pl",
            floor=0.80,
            session_effect_sd=0.5,
            note="responses correlated within a session, scored as independent",
            **overrides,
        ),
        run_cell(
            "parameter drift",
            simulated_under="2pl",
            scored_under="2pl",
            floor=0.75,
            b_drift=0.20,
            note="20% drift in b: M05 recalibrated and we scored on stale params",
            **overrides,
        ),
        run_cell(
            "non-normal ability",
            simulated_under="2pl",
            scored_under="2pl",
            floor=0.80,
            bimodal=True,
            note="a genuinely bimodal cohort under a normal prior",
            **overrides,
        ),
    ]
    return cells


# ─────────────────────────────────────────────────────────────
#  COLD START  (§12's last row, and it is a gate)
# ─────────────────────────────────────────────────────────────


@dataclass
class WashOutResult:
    """How much of a cohort prior survives n observations.

    Open decision 3 uses branch-level priors for cold start, and a branch-level
    prior is a fairness problem sitting inside Paper 2 unless you can show it
    disappears. So: give two branches priors a full logit apart, draw true
    ability INDEPENDENTLY of branch, and measure the gap that remains.
    """

    n_observations: int
    prior_gap: float
    remaining_gap: float

    @property
    def washed_out(self) -> bool:
        #: A tenth of a logit is below the resolution of anything we display —
        #: two students a tenth apart are the same five-state label at every
        #: threshold.
        return abs(self.remaining_gap) < 0.10


def wash_out(
    *,
    n_students: int = DEFAULT_STUDENTS,
    prior_gap: float = 2.0,
    max_observations: int = 6,
    seed: int = 11,
) -> list[WashOutResult]:
    """Does the branch prior survive? It must not, by n = 3.

    This is a pass/fail gate, not a note. If a prior derived from which branch
    a student is in still moves their displayed mastery after three real
    answers, then the platform is reporting a property of their branch as a
    property of them.
    """
    rng = random.Random(seed)
    truths = normal_abilities(n_students, rng)
    items = [make_items(max_observations, random.Random(seed + i)) for i in range(n_students)]

    results: list[WashOutResult] = []
    for n in range(0, max_observations + 1):
        highs: list[float] = []
        lows: list[float] = []
        for index, true_theta in enumerate(truths):
            student_rng = random.Random(seed * 977 + index)
            responses = [
                Response(
                    model="2pl",
                    a=item.a,
                    b=item.b,
                    category=respond_2pl(true_theta, item, student_rng),
                )
                for item in items[index][:n]
            ]
            # The SAME student and the SAME answers, scored from each branch's
            # prior. Anything left is the prior talking, not the student.
            high, _ = recover([responses], prior_theta=+prior_gap / 2)
            low, _ = recover([responses], prior_theta=-prior_gap / 2)
            highs.append(high)
            lows.append(low)

        results.append(
            WashOutResult(
                n_observations=n,
                prior_gap=prior_gap,
                remaining_gap=(sum(highs) - sum(lows)) / len(highs),
            )
        )
    return results
