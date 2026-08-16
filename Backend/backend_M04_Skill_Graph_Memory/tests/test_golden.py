"""The golden snapshot (§12).

A fixed observation sequence, a frozen expected posterior. Any estimator change
that moves these numbers must be **deliberate**, and an `estimator_version`
bump is how you declare it (§6.7: a version bump does not re-score, it
REPLAYS — observations are immutable, so mastery is recomputed from them and
the snapshot is expected to move).

The failure this prevents is quiet: someone tunes a quadrature constant, every
behavioural test still passes because every behaviour is still qualitatively
right, and three months of students are scored on a different scale from the
three months before them. Trap 4 with the estimator as its subject.

If this test fails and the change was intended: re-run it, paste the new
numbers in, bump `ESTIMATOR_VERSION`, and say in the commit message why the
scale moved.
"""

from __future__ import annotations

import pytest

from backend_M04_Skill_Graph_Memory.estimators import (
    ESTIMATOR_VERSION,
    BktEvent,
    Response,
    bkt_p_known,
    replay,
)

#: The sequence. Hand-picked to exercise every branch that matters: a 2PL
#: item, a graded one, a guessing-corrected one, a hint-tempered weight, and an
#: item whose parameters we are unsure of.
SEQUENCE = [
    Response(model="2pl", a=1.20, b=-0.50, category=1),
    Response(model="2pl", a=1.60, b=0.30, category=0),
    Response(model="grm", a=1.30, b=[-1.2, -0.4, 0.4, 1.2], category=3, n_categories=5),
    Response(model="3pl", a=1.10, b=0.10, c=0.25, category=1),
    Response(model="grm", a=0.90, b=[-1.0, 0.0, 1.0], category=1, n_categories=4),
    Response(model="2pl", a=1.40, b=0.00, category=1, weight=0.7),
    Response(model="2pl", a=1.80, b=0.60, category=1, se_b=0.35),
]

#: Frozen 2026-08-15 under estimator 1.0, prior N(0, 1.5^2), 61-point
#: trapezoidal grid on [-4.5, 4.5].
GOLDEN_ESTIMATOR_VERSION = "1.0"
GOLDEN_SAME_SESSION = (0.8167350, 0.7716589)
GOLDEN_ACROSS_SESSIONS = (0.6896632, 0.5900714)
GOLDEN_BKT = 0.9320414


def test_the_estimator_version_matches_the_snapshot():
    """If these diverge, the snapshot below describes an estimator that is no
    longer the one running, and its passing means nothing."""
    assert ESTIMATOR_VERSION == GOLDEN_ESTIMATOR_VERSION


def test_golden_posterior_within_one_session():
    posterior = replay(0.0, 1.5, SEQUENCE, same_session=True)

    assert (posterior.theta, posterior.se) == (
        pytest.approx(GOLDEN_SAME_SESSION[0], abs=1e-6),
        pytest.approx(GOLDEN_SAME_SESSION[1], abs=1e-6),
    )


def test_golden_posterior_across_sessions():
    """The same seven answers, spread over seven sittings instead of one.

    Both numbers move, and it is worth being precise about why, because the
    obvious expectation — "same evidence, same theta, tighter error bar" — is
    wrong and the difference is the whole content of the local-dependence cap.

    Spread out, every answer is allowed to shrink the error bar, so the
    posterior tightens (0.77 -> 0.59). A tighter posterior is also a *stiffer*
    one: later answers move it less. Back-to-back, the cap freezes SE after the
    third answer, leaving a wide prior that the last few answers swing further
    (theta 0.69 -> 0.82). Correlated answers therefore buy no certainty and
    still push the estimate around, which is exactly the behaviour that makes
    five questions in one sitting worth less than five across a term.
    """
    posterior = replay(0.0, 1.5, SEQUENCE, same_session=False)

    assert (posterior.theta, posterior.se) == (
        pytest.approx(GOLDEN_ACROSS_SESSIONS[0], abs=1e-6),
        pytest.approx(GOLDEN_ACROSS_SESSIONS[1], abs=1e-6),
    )
    assert posterior.se < GOLDEN_SAME_SESSION[1]


def test_golden_bkt():
    events = [
        BktEvent(correct=True),
        BktEvent(correct=False),
        BktEvent(correct=True, days_since_previous=14, new_session=True),
        BktEvent(correct=True),
        BktEvent(correct=True, days_since_previous=45, new_session=True),
    ]
    assert bkt_p_known(events) == pytest.approx(GOLDEN_BKT, abs=1e-6)


def test_the_grid_itself_is_frozen():
    """The quadrature is part of the scale. Widening the interval or changing
    the point count moves every stored theta, so it belongs in the snapshot
    rather than being a constant somebody adjusts while debugging."""
    from backend_M04_Skill_Graph_Memory.estimators import (
        GRID_MAX,
        GRID_MIN,
        GRID_POINTS,
    )

    assert (GRID_MIN, GRID_MAX, GRID_POINTS) == (-4.5, 4.5, 61)
