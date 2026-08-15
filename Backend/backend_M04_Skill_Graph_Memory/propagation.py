"""Prerequisite propagation — the most important rule in this module.

Spec: §6.4, FR-4.7, FR-4.24, Trap 3.

**The asymmetry is deliberate.** Evidence of competence is transferable;
evidence of failure is not.

    SUCCESS on DP   -> weakly RAISE theta for its prerequisites.
                       You cannot do DP without recursion, so a correct DP
                       answer is real, if indirect, evidence about recursion.
    FAILURE on DP   -> do NOT lower anything. Only WIDEN the SE of what
                       depends on it.
                       Failing DP does not prove you cannot do recursion. It
                       proves we should CHECK — and widening SE is exactly what
                       makes the CAT selector go and check.

Three constraints keep it honest, and each closes a hole the naive version has:

1. **It writes real observations.** `kind="propagated"`, carrying the SOURCE
   observation's evidence refs — genuinely the evidence, just indirect.
   Without this, propagation moves a mastery value with nothing behind it and
   AC-4.1 fails on M04's own write path: the drawer that enforces Rule 3 would
   have nothing to render.

2. **`n_direct` and `n_propagated` are separate, and only `n_direct` counts.**
   A concept whose evidence is purely propagated renders `not_tested`
   (FR-4.24, EC-4.16) — no sixth state, no Rule 3 hole. The propagated theta
   still exists and is still used by the one consumer that legitimately
   benefits from a prior it need not justify to a student: M05's selector.

3. **Both moves are clamped, per update and per lifetime.** Multiplicative
   widening is otherwise unbounded, and ten failed DP questions would widen
   recursion's SE past the prior SD — incoherent, because you cannot know less
   than nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_core.mastery import SE_PRIOR

from .ontology import Ontology

DAMPING = 0.3
MAX_HOPS = 2
#: Above this normalised outcome, an answer counts as success for propagation.
SUCCESS_THRESHOLD = 0.7
#: How much of a success transfers, before damping and edge strength.
SUCCESS_TRANSFER = 0.15
#: Ceiling on a SINGLE propagated theta move.
SINGLE_UPDATE_CAP = 0.20
#: Ceiling on the LIFETIME propagated contribution to any one concept.
#: Tracked in `Mastery.theta_propagated_total`: without it, a hundred adjacent
#: successes could walk a never-tested concept to "strong" without anyone ever
#: asking the student a question about it.
LIFETIME_CAP = 0.35
#: Raising theta while holding SE fixed is a claim of certainty that no answer
#: supplied, so the success branch widens slightly too.
SUCCESS_SE_FACTOR = 1.02
FAILURE_SE_TRANSFER = 0.25


@dataclass(frozen=True)
class PropagationStep:
    """One derived observation, before it meets the target's current state."""

    concept_id: str
    hops: int
    strength: float
    d_theta: float
    se_factor: float
    #: `damping^hop * strength`. Recorded on the derived observation so the
    #: drawer can say how much of a value came from somewhere else.
    weight: float
    direction: str  # "up" (to prerequisites) | "down" (to dependents)


def plan(
    concept_id: str,
    outcome: float,
    ontology: Ontology,
    *,
    damping: float = DAMPING,
    max_hops: int = MAX_HOPS,
) -> list[PropagationStep]:
    """What this observation implies about the neighbourhood. Pure.

    Returned in sorted concept order, which is not cosmetic: `record()` takes
    row locks in this order, and two concurrent sessions touching overlapping
    neighbourhoods deadlock on Postgres if the order differs between them.
    """
    steps: list[PropagationStep] = []

    if outcome >= SUCCESS_THRESHOLD:
        for neighbour in ontology.walk_up(concept_id, max_hops):
            damped = (damping**neighbour.hops) * neighbour.strength
            delta = damped * SUCCESS_TRANSFER * (outcome - 0.5)
            steps.append(
                PropagationStep(
                    concept_id=neighbour.concept_id,
                    hops=neighbour.hops,
                    strength=neighbour.strength,
                    d_theta=min(delta, SINGLE_UPDATE_CAP),
                    se_factor=SUCCESS_SE_FACTOR,
                    weight=(damping**neighbour.hops) * neighbour.strength,
                    direction="up",
                )
            )
    else:
        for neighbour in ontology.walk_down(concept_id, max_hops):
            steps.append(
                PropagationStep(
                    concept_id=neighbour.concept_id,
                    hops=neighbour.hops,
                    strength=neighbour.strength,
                    d_theta=0.0,
                    se_factor=1.0
                    + (damping**neighbour.hops) * neighbour.strength * FAILURE_SE_TRANSFER,
                    weight=(damping**neighbour.hops) * neighbour.strength,
                    direction="down",
                )
            )

    return sorted(steps, key=lambda s: s.concept_id)


def apply_clamps(
    step: PropagationStep,
    *,
    current_se: float,
    lifetime_propagated: float,
) -> tuple[float, float, float]:
    """The step as it will actually land: (d_theta, new_se, new_lifetime).

    Separated from `plan` because the clamps depend on the TARGET's history,
    not on the source observation — and because a clamp nobody can test in
    isolation is a clamp that gets quietly removed during a refactor.
    """
    headroom = max(0.0, LIFETIME_CAP - abs(lifetime_propagated))
    d_theta = step.d_theta
    if d_theta >= 0:
        d_theta = min(d_theta, headroom)
    else:
        d_theta = -min(-d_theta, headroom)

    new_se = min(current_se * step.se_factor, SE_PRIOR)
    return d_theta, new_se, lifetime_propagated + d_theta
