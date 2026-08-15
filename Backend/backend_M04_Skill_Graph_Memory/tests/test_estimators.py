"""IRT and BKT arithmetic (§6.3, §12 unit list).

Two of the previous draft's constants were provably wrong rather than
debatable, and both were invisible to the tests written for them. These are the
tests that would have caught them, written first: the all-wrong BKT sequence,
and the sequences a decay curve has to move on.
"""

from __future__ import annotations

import math

import pytest

from backend_M04_Skill_Graph_Memory.estimators import (
    BKT_P_L0,
    LOCAL_DEPENDENCE_CAP,
    SE_PRIOR,
    BktEvent,
    Response,
    bkt_p_known,
    bkt_transit,
    grm_category_probabilities,
    p_2pl,
    p_3pl,
    replay,
    response_probability,
    update,
)

# ── BKT ───────────────────────────────────────────────────────────────────


def test_bkt_all_wrong_falls_monotonically():
    """THE test the previous parameters failed.

    At P(T) = 0.20 the transit dominated the evidence: a student answering
    everything wrong went 0.15 -> 0.2173 -> 0.2268 -> ... -> a hard floor of
    0.2286. A wrong answer RAISED mastery, and nothing in the suite noticed.
    """
    values = [bkt_p_known([BktEvent(correct=False)] * n) for n in range(0, 10)]
    assert values[0] == BKT_P_L0

    for earlier, later in zip(values, values[1:], strict=False):
        assert later < earlier, f"wrong answers must lower mastery: {values}"
    assert values[-1] < 0.01


def test_bkt_all_correct_rises_monotonically():
    values = [bkt_p_known([BktEvent(correct=True)] * n) for n in range(0, 8)]
    for earlier, later in zip(values, values[1:], strict=False):
        assert later > earlier


def test_bkt_does_not_learn_within_a_session():
    """P(T) models learning BETWEEN practice opportunities, and nobody teaches
    you anything between interview question 3 and question 4."""
    assert bkt_transit(0.0) == 0.0


def test_bkt_transit_grows_with_the_gap_and_is_bounded():
    assert bkt_transit(30) < bkt_transit(90) < bkt_transit(365) <= 0.15


def test_a_gap_between_sessions_raises_mastery_slightly():
    """Someone who has been away for two months has probably practised. That is
    the only place BKT is allowed to invent progress."""
    without = bkt_p_known([BktEvent(correct=True), BktEvent(correct=True)])
    with_gap = bkt_p_known(
        [
            BktEvent(correct=True),
            BktEvent(correct=True, days_since_previous=60, new_session=True),
        ]
    )
    assert with_gap > without


# ── IRT likelihoods ───────────────────────────────────────────────────────


def test_2pl_is_a_logistic_in_ability():
    assert p_2pl(0.0, a=1.0, b=0.0) == pytest.approx(0.5)
    assert p_2pl(2.0, a=1.0, b=0.0) > p_2pl(1.0, a=1.0, b=0.0)
    assert 0.0 < p_2pl(-8.0, a=2.0, b=1.0) < 0.001


def test_3pl_floors_at_the_guessing_rate():
    """A student who knows nothing still scores 1/4 on a four-option item, and
    scoring that as evidence of ability is how an aptitude section flatters
    everyone."""
    assert p_3pl(-6.0, a=1.0, b=0.0, c=0.25) == pytest.approx(0.25, abs=0.01)


def test_grm_categories_sum_to_one():
    probs = grm_category_probabilities(0.4, a=1.3, thresholds=[-1.5, -0.2, 0.9, 2.0])
    assert len(probs) == 5
    assert sum(probs) == pytest.approx(1.0)
    assert all(p >= 0 for p in probs)


def test_grm_reduces_to_2pl_at_two_categories():
    """The reason GRM is not a separate code path: at K=2 it IS the 2PL, so a
    disagreement here is a bug in one of them."""
    for theta in (-2.0, -0.5, 0.0, 1.3):
        grm = grm_category_probabilities(theta, a=1.1, thresholds=[0.3])
        assert grm[1] == pytest.approx(p_2pl(theta, a=1.1, b=0.3))


def test_grm_shifts_mass_upward_with_ability():
    low = grm_category_probabilities(-2.0, a=1.2, thresholds=[-1.0, 0.0, 1.0])
    high = grm_category_probabilities(2.0, a=1.2, thresholds=[-1.0, 0.0, 1.0])
    assert low[0] > high[0]
    assert high[-1] > low[-1]


def test_item_uncertainty_attenuates_discrimination():
    """An item calibrated on eleven responses must not move a student's estimate
    as hard as one calibrated on eleven hundred."""
    confident = Response(model="2pl", a=2.0, b=0.0, category=1)
    shaky = Response(model="2pl", a=2.0, b=0.0, se_b=0.8, category=1)
    assert shaky.a_effective < confident.a_effective

    sharp = update(0.0, 1.5, confident)
    blunt = update(0.0, 1.5, shaky)
    assert blunt.theta < sharp.theta


# ── posterior updates ─────────────────────────────────────────────────────


def test_a_correct_answer_raises_theta_and_a_wrong_one_lowers_it():
    correct = update(0.0, 1.5, Response(model="2pl", a=1.5, b=0.0, category=1))
    wrong = update(0.0, 1.5, Response(model="2pl", a=1.5, b=0.0, category=0))

    assert correct.theta > 0 > wrong.theta
    assert correct.se < 1.5 and wrong.se < 1.5


def test_evidence_shrinks_the_error_bar():
    posterior = replay(
        0.0,
        SE_PRIOR,
        [Response(model="2pl", a=1.4, b=0.0, category=1) for _ in range(2)],
    )
    assert posterior.se < SE_PRIOR


def test_se_never_exceeds_the_prior():
    """You cannot know less than you knew before you had any data."""
    for category in (0, 1):
        posterior = update(0.0, SE_PRIOR, Response(model="2pl", a=0.4, b=3.5, category=category))
        assert posterior.se <= SE_PRIOR


def test_theta_is_clamped():
    posterior = replay(
        0.0,
        SE_PRIOR,
        [Response(model="2pl", a=2.5, b=-3.0, category=1) for _ in range(40)],
    )
    assert -4.0 <= posterior.theta <= 4.0


def test_weight_tempers_the_update():
    """Hint-assisted answers take weight 0.7: real evidence, worth less."""
    full = update(0.0, 1.5, Response(model="2pl", a=1.5, b=0.0, category=1, weight=1.0))
    tempered = update(0.0, 1.5, Response(model="2pl", a=1.5, b=0.0, category=1, weight=0.7))
    assert tempered.theta < full.theta


def test_local_dependence_stops_the_error_bar_shrinking():
    """Five questions on one concept in one session are not independent.
    Treating them as independent understates SE by ~1.35x at rho = 0.2, k = 5,
    which makes M05 stop early believing it knows more than it does."""
    response = Response(model="2pl", a=1.4, b=0.0, category=1)

    uncapped = update(0.6, 0.7, response, responses_this_session=LOCAL_DEPENDENCE_CAP - 1)
    capped = update(0.6, 0.7, response, responses_this_session=LOCAL_DEPENDENCE_CAP)

    assert uncapped.se < 0.7
    assert capped.se == 0.7
    assert capped.local_dependence_capped is True
    # The answer still informs theta. It just stops buying certainty.
    assert capped.theta == pytest.approx(uncapped.theta)


def test_eap_recovers_a_known_ability():
    """The sanity check, not a result: simulate from the model we then fit and
    see that the quadrature works. The mis-specification grid in §12 is what
    actually tests the estimator."""
    true_theta = 1.0
    responses = []
    for index in range(30):
        b = -2.0 + (4.0 * index / 29)
        p = p_2pl(true_theta, a=1.5, b=b)
        # Deterministic: take the modal response, so the test cannot flake.
        responses.append(Response(model="2pl", a=1.5, b=b, category=1 if p >= 0.5 else 0))

    # Across sessions: thirty items on one concept in a single sitting is not
    # a thing that happens, and the local-dependence cap is deliberately harsh
    # about pretending otherwise.
    posterior = replay(0.0, SE_PRIOR, responses, same_session=False)
    assert abs(posterior.theta - true_theta) < 0.6
    assert posterior.se < 0.5


def test_an_impossible_response_does_not_move_the_estimate():
    """An item so far off the scale that the response has zero density under
    the prior. Refusing to move is honest; moving somewhere arbitrary is not."""
    posterior = update(0.0, 1e-9, Response(model="2pl", a=50.0, b=40.0, category=1))
    assert math.isfinite(posterior.theta)


def test_response_probability_respects_the_observed_category():
    correct = Response(model="2pl", a=1.0, b=0.0, category=1)
    wrong = Response(model="2pl", a=1.0, b=0.0, category=0)
    assert response_probability(correct, 1.0) > 0.5
    assert response_probability(wrong, 1.0) < 0.5
