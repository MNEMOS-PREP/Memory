"""The mis-specification grid and the cold-start wash-out (§12, AC-4.4).

Runs at a reduced cohort so the suite stays fast; the full 200 x 6 run is
`python -m backend_M04_Skill_Graph_Memory.jobs.simulate`. The cells and the
floors are identical either way — only `n_students` moves, and the seed is
fixed, so a failure here reproduces exactly.
"""

from __future__ import annotations

import pytest

from backend_M04_Skill_Graph_Memory.priors import (
    MAX_COHORT_PRIOR_GAP,
    RESIDUAL_AT_N3,
    clamp_prior,
    cold_start_prior,
)
from backend_M04_Skill_Graph_Memory.simulation import (
    grid,
    pearson,
    run_cell,
    wash_out,
)

STUDENTS = 120
SESSIONS = 4


@pytest.fixture(scope="module")
def cells():
    return grid(n_students=STUDENTS, sessions=SESSIONS)


@pytest.mark.gate
def test_ac_4_4_every_cell_of_the_grid_clears_its_floor(cells):
    """AC-4.4. The matched cell is a sanity check; the other four are the test.

    Simulating from the model you then fit exercises your quadrature, not your
    estimator — it passes on almost any implementation, which is why reporting
    it alone is a reviewer's first objection.
    """
    failures = [c.row() for c in cells if not c.passed]
    assert failures == [], "\n" + "\n".join(failures)


def test_the_matched_cell_recovers_ability_nearly_exactly(cells):
    matched = next(c for c in cells if c.name == "matched")
    assert matched.r >= 0.90
    assert abs(matched.bias) < 0.10


def test_collapsing_graded_data_to_binary_costs_half_a_logit(cells):
    """The price of NOT shipping GRM, as a number.

    Correlation survives the collapse — which is exactly why a spec can get
    away with deferring GRM and look fine — but the estimate is systematically
    LOW, because "3 out of 4" scored as merely "correct" throws away the
    distance between adequate and excellent. M05 §3.1 Trap 2 names this and
    §6.3 is why GRM ships on day one rather than later.
    """
    mis_spec = next(c for c in cells if c.name == "model mis-spec")
    assert mis_spec.r >= 0.80
    assert mis_spec.bias < -0.20, "the collapse should bias downward, and visibly"


def test_the_estimator_does_not_overstate_its_own_certainty(cells):
    """`se_ratio` above 1 means we report more confidence than the errors
    justify. Below 1 is conservative, which is the side to be on when the
    number decides what a student is asked next."""
    for cell in cells:
        assert cell.se_ratio <= 1.4, f"{cell.name} understates SE by {cell.se_ratio:.2f}x"


def test_correlated_sessions_erode_the_safety_margin(cells):
    """Local dependence does not break recovery, but it visibly eats into how
    conservative the SE is — which is the effect §6.3's per-session cap exists
    to blunt, and the first thing a Paper 2 reviewer asks about."""
    independent = next(c for c in cells if c.name == "matched")
    correlated = next(c for c in cells if c.name == "local dependence")
    assert correlated.se_ratio > independent.se_ratio


def test_pearson_is_sane():
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_a_cell_reports_bias_separately_from_correlation():
    """A cell can correlate beautifully and still be half a logit low, and that
    is a different problem with a different fix."""
    cell = run_cell(
        "shifted",
        simulated_under="2pl",
        scored_under="2pl",
        floor=0.0,
        n_students=40,
        sessions=2,
        prior_offset=2.0,
    )
    assert cell.bias > 0.10
    assert cell.r > 0.5


# ── cold start (§12's last row — a gate, not a note) ──────────────────────


@pytest.mark.gate
def test_a_capped_cohort_prior_has_washed_out_by_three_answers(cells):
    """Open decision 3's fairness requirement, at the gap we actually permit.

    A prior derived from which branch a student is in must not still be moving
    their displayed mastery once they have answered real questions. At
    `MAX_COHORT_PRIOR_GAP` it is gone by n = 3 — below the tenth of a logit at
    which two students stop sharing a five-state label.
    """
    at_three = next(
        r for r in wash_out(n_students=80, prior_gap=MAX_COHORT_PRIOR_GAP) if r.n_observations == 3
    )
    assert at_three.washed_out, f"{at_three.remaining_gap:+.3f} logits of branch still showing"


def test_a_large_prior_gap_provably_cannot_wash_out_by_n3():
    """The finding that produced the cap, pinned so nobody re-widens the gap.

    A 2-logit spread between branch priors still leaves ~0.77 logits after
    three answers — a third of it. With SE_PRIOR = 1.5, three items simply do
    not carry enough information to overwhelm the prior, so "the prior is gone
    by n = 3" is achievable only by leaning less, never by waiting.
    """
    at_three = next(r for r in wash_out(n_students=80, prior_gap=2.0) if r.n_observations == 3)

    assert not at_three.washed_out
    assert at_three.remaining_gap == pytest.approx(2.0 * RESIDUAL_AT_N3, abs=0.15)


def test_the_prior_decays_monotonically_with_evidence():
    results = wash_out(n_students=60, prior_gap=1.0)
    gaps = [r.remaining_gap for r in results]
    for earlier, later in zip(gaps, gaps[1:], strict=False):
        assert later <= earlier + 1e-9, f"evidence must never strengthen a prior: {gaps}"


def test_priors_are_clamped_at_the_published_limit():
    limit = MAX_COHORT_PRIOR_GAP / 2
    assert clamp_prior(3.0) == pytest.approx(limit)
    assert clamp_prior(-3.0) == pytest.approx(-limit)
    assert clamp_prior(0.05) == pytest.approx(0.05)


def test_a_small_cohort_falls_back_to_the_institute():
    theta, se = cold_start_prior(cohort_mean=0.9, institute_mean=0.1, cohort_size=4)
    assert theta == pytest.approx(0.1)
    assert se == 1.5


def test_an_unknown_cohort_gets_a_flat_prior():
    assert cold_start_prior(None, None, 0) == (0.0, 1.5)


def test_a_cohort_never_narrows_the_error_bar():
    """A cohort tells you where to start looking, never how sure to be.
    Narrowing someone's error bar because of their branch is the version of
    this that would genuinely be indefensible."""
    _, se = cold_start_prior(cohort_mean=0.9, institute_mean=0.0, cohort_size=500)
    assert se == 1.5
