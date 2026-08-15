"""IRT and BKT — the arithmetic behind every number this module publishes.

Spec: §6.3. Pure functions over plain values: no database, no session, no
config. That is deliberate — two of the previous draft's constants were
provably wrong rather than debatable, and both were invisible to the tests
written for them. Arithmetic that can only be exercised through a web request
does not get exercised.

**IRT is the source of truth.** Theta and SE are the posterior; everything
displayed derives from them. BKT is a display-only companion computed on read
(§6.3, open decision 4): two persisted beliefs about one latent quantity with
no arbitration rule is a bug, not a feature.

**The item travels with the observation.** Trap 7: an equation in a spec is
not a specification until the contract above it can supply every symbol. The
previous draft specified `P(correct|theta) = 1/(1+exp(-a(theta-b)))` over an
observation carrying neither `a` nor an item reference — whoever implemented
it would have hardcoded two constants, and those constants would have silently
defined the entire ability scale while every test passed. So an observation
with no `item` is not theta-eligible, explicitly, and says so in the drawer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ai_core.mastery import SE_PRIOR, THETA_MAX, THETA_MIN

ESTIMATOR_VERSION = "1.0"

# ── the quadrature grid ──────────────────────────────────────────────────
#
# A FIXED grid on a bounded interval, integrated with the trapezoidal rule.
# The previous draft said "41-point Gauss-Hermite quadrature on [-4, 4]",
# which conflates two things: Gauss-Hermite integrates against exp(-x^2) over
# the whole line, and a fixed grid on a bounded interval is Gauss-Legendre or
# trapezoidal. The interval was also too narrow for sigma_prior = 1.5, which
# truncates the posterior for any genuinely strong or genuinely struggling
# student — the two groups it matters most to be right about.

GRID_MIN = -4.5
GRID_MAX = 4.5
GRID_POINTS = 61
GRID_STEP = (GRID_MAX - GRID_MIN) / (GRID_POINTS - 1)
THETA_GRID: tuple[float, ...] = tuple(GRID_MIN + i * GRID_STEP for i in range(GRID_POINTS))

#: Cap on theta-eligible observations per concept per session that are allowed
#: to SHRINK the SE. Five questions on one concept in one session are not
#: conditionally independent; treating them as independent understates SE by
#: roughly sqrt(1 + rho(k-1)) — about 1.35x at rho = 0.2, k = 5. That makes
#: M05 stop early believing it knows more than it does, and it is the first
#: thing a Paper 2 reviewer asks about (§6.3, local dependence).
LOCAL_DEPENDENCE_CAP = 3

# BKT priors — a single GLOBAL set, not fitted per concept. Four free
# parameters x 120 concepts by EM needs thousands of sequences PER CONCEPT and
# is not identifiable at any volume this project reaches: a pilot of 50-300
# students is three orders of magnitude short.
BKT_P_L0 = 0.15
BKT_P_GUESS = 0.20
BKT_P_SLIP = 0.10
BKT_TRANSIT_MAX = 0.15
BKT_TRANSIT_HALFLIFE_DAYS = 60.0


def logistic(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)  # avoid overflow at large negative x
    return e / (1.0 + e)


def clamp_theta(theta: float) -> float:
    return max(THETA_MIN, min(THETA_MAX, theta))


# ─────────────────────────────────────────────────────────────
#  LIKELIHOODS
# ─────────────────────────────────────────────────────────────


def p_2pl(theta: float, a: float, b: float) -> float:
    return logistic(a * (theta - b))


def p_3pl(theta: float, a: float, b: float, c: float) -> float:
    """MCQ aptitude, where guessing is real: a student who knows nothing still
    scores 1/4 on a four-option item, and scoring that as evidence of ability
    is how an aptitude section flatters everyone."""
    return c + (1.0 - c) * logistic(a * (theta - b))


def grm_category_probabilities(theta: float, a: float, thresholds: list[float]) -> list[float]:
    """Samejima's graded response model. P(X = k) for k = 0..K.

    `thresholds` are the K boundaries b_1..b_K of a rubric with K+1 levels:

        P(X >= k) = 1 / (1 + exp(-a(theta - b_k)))     P(X >= 0) = 1
        P(X = k)  = P(X >= k) - P(X >= k+1)            P(X >= K+1) = 0

    **Not optional and not deferred.** Most items are rubric-scored, and M05
    §3.1 Trap 2 names the failure exactly: collapsing to right/wrong throws
    away most of the information and biases `b`. It is twenty lines on top of
    the 2PL and it is the difference between a defensible Paper 2 and a
    reviewer's first objection.
    """
    cumulative = [1.0] + [logistic(a * (theta - b)) for b in thresholds] + [0.0]
    return [cumulative[k] - cumulative[k + 1] for k in range(len(thresholds) + 1)]


@dataclass(frozen=True)
class Response:
    """One scored response, in the form the likelihood actually needs."""

    model: str  # "2pl" | "grm" | "3pl"
    a: float
    b: float | list[float]
    c: float | None = None
    se_b: float | None = None
    #: 2PL/3PL: 1 for correct, 0 for incorrect. GRM: the rubric level, 0..K.
    category: int = 0
    n_categories: int = 2
    #: Likelihood tempering, in (0, 1]. Hint-assisted answers take 0.7. Never
    #: above 1 — a weight > 1 fabricates precision no answer supplied.
    weight: float = 1.0

    @property
    def a_effective(self) -> float:
        """Discrimination, attenuated for what we do not know about the item.

        Where `se_b` is known we attenuate rather than pretend:
        `a_eff = a / sqrt(1 + a^2 * se_b^2)`. An item calibrated on eleven
        responses should not move a student's estimate as hard as one
        calibrated on eleven hundred, and treating them alike is how
        calibration error is laundered into ability error.
        """
        if not self.se_b:
            return self.a
        return self.a / math.sqrt(1.0 + (self.a**2) * (self.se_b**2))


def response_probability(response: Response, theta: float) -> float:
    a = response.a_effective
    if response.model == "grm":
        thresholds = list(response.b) if isinstance(response.b, list) else [float(response.b)]
        probs = grm_category_probabilities(theta, a, thresholds)
        index = max(0, min(len(probs) - 1, response.category))
        return probs[index]

    b = float(response.b[0]) if isinstance(response.b, list) else float(response.b)
    if response.model == "3pl":
        p = p_3pl(theta, a, b, response.c if response.c is not None else 0.0)
    else:
        p = p_2pl(theta, a, b)
    return p if response.category >= 1 else 1.0 - p


# ─────────────────────────────────────────────────────────────
#  POSTERIOR UPDATE
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Posterior:
    theta: float
    se: float
    #: True when the SE was held at its previous value because this concept
    #: already had `LOCAL_DEPENDENCE_CAP` answers in this session. Reported
    #: rather than hidden — §6.3 says to report the cap, because an
    #: unreported correction is indistinguishable from a bug.
    local_dependence_capped: bool = False


_MIN_DENSITY = 1e-300


def update(
    prior_theta: float,
    prior_se: float,
    response: Response,
    *,
    responses_this_session: int = 0,
) -> Posterior:
    """One Bayesian update: N(prior) x likelihood, on the grid, EAP out.

    The posterior is carried forward as a Gaussian summary (theta, se) rather
    than as a full grid. That is an approximation and it is the right one here:
    the alternative is storing 61 floats per (candidate, concept) and a replay
    story for them, to buy accuracy that is invisible next to the item
    parameter uncertainty we already attenuate for.
    """
    sigma = max(prior_se, 1e-6)
    weight = max(0.0, min(1.0, response.weight))

    densities: list[float] = []
    for theta in THETA_GRID:
        z = (theta - prior_theta) / sigma
        prior = math.exp(-0.5 * z * z)
        if prior < _MIN_DENSITY:
            densities.append(0.0)
            continue
        p = response_probability(response, theta)
        # Tempering in the exponent: logL_eff = w * logL.
        likelihood = p**weight if p > 0 else 0.0
        densities.append(prior * likelihood)

    total = _trapezoid(densities)
    if total <= 0:
        # Every grid point has zero density — an item so far off the scale that
        # the response is impossible under the prior. Refusing to move is the
        # honest answer; moving somewhere arbitrary is not.
        return Posterior(theta=prior_theta, se=prior_se)

    mean = _trapezoid([d * t for d, t in zip(densities, THETA_GRID, strict=True)]) / total
    variance = (
        _trapezoid([d * (t - mean) ** 2 for d, t in zip(densities, THETA_GRID, strict=True)]) / total
    )
    se = math.sqrt(max(variance, 0.0))

    capped = False
    if responses_this_session >= LOCAL_DEPENDENCE_CAP and se < prior_se:
        # The answer still informs theta; it just stops buying certainty. Five
        # questions on one concept in one session share a stem, a mood and a
        # framing, and pretending otherwise understates SE by ~1.35x.
        se = prior_se
        capped = True

    return Posterior(theta=clamp_theta(mean), se=min(se, SE_PRIOR), local_dependence_capped=capped)


def _trapezoid(values: list[float]) -> float:
    if not values:
        return 0.0
    total = 0.5 * (values[0] + values[-1]) + sum(values[1:-1])
    return total * GRID_STEP


def replay(
    prior_theta: float,
    prior_se: float,
    responses: list[Response],
    *,
    same_session: bool = True,
) -> Posterior:
    """Recompute a posterior from a sequence. FR-4.26's retraction path.

    Mastery is recomputed from surviving observations, never compensated by an
    inverse update: an inverse leaves two wrongs in the ledger and a right
    answer nobody can derive from it.

    `same_session` decides whether the local-dependence cap applies across the
    whole list. It matters more than it looks: with the cap on, SE stops
    shrinking after the third response, so the prior stays wide and each later
    response moves theta further than it otherwise would. That is the correct
    behaviour for five questions asked back to back in one sitting — they are
    not five independent measurements — and the wrong behaviour for a year of
    history, where `recompute()` tracks the real session boundaries instead.
    """
    posterior = Posterior(theta=prior_theta, se=prior_se)
    for index, response in enumerate(responses):
        posterior = update(
            posterior.theta,
            posterior.se,
            response,
            responses_this_session=index if same_session else 0,
        )
    return posterior


# ─────────────────────────────────────────────────────────────
#  BKT  —  display-only companion, computed on read
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BktEvent:
    correct: bool
    #: Days since the previous event. 0 within a session.
    days_since_previous: float = 0.0
    new_session: bool = False


def bkt_transit(days_gap: float) -> float:
    """P(T) between sessions. ZERO within one.

    P(T) models learning between practice opportunities, and nobody teaches you
    anything between interview question 3 and question 4. At the previously
    specified P(T) = 0.20 the transit dominates the evidence: a student
    answering EVERYTHING wrong goes 0.15 -> 0.2173 -> 0.2268 -> ... -> a hard
    floor of 0.2286. A wrong answer RAISED mastery. Verified by running these
    exact equations with these exact priors, which is also why
    `test_bkt_all_wrong_is_monotonically_falling` exists.
    """
    if days_gap <= 0:
        return 0.0
    return BKT_TRANSIT_MAX * (1.0 - math.exp(-days_gap / BKT_TRANSIT_HALFLIFE_DAYS))


def bkt_p_known(events: list[BktEvent]) -> float:
    """P(the student knows this), from the sequence. Never persisted.

    Computed on read so it cannot drift away from the posterior: decay and
    propagation move theta only, so a stored BKT value would become a second
    belief about one latent quantity with no rule saying which the UI believes.
    """
    p = BKT_P_L0
    for event in events:
        if event.new_session:
            transit = bkt_transit(event.days_since_previous)
            p = p + (1.0 - p) * transit
        if event.correct:
            numerator = p * (1.0 - BKT_P_SLIP)
            denominator = numerator + (1.0 - p) * BKT_P_GUESS
        else:
            numerator = p * BKT_P_SLIP
            denominator = numerator + (1.0 - p) * (1.0 - BKT_P_GUESS)
        p = numerator / denominator if denominator > 0 else p
    return p
