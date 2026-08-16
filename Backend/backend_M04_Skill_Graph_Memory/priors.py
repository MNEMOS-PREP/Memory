"""Cold-start priors, and the hard limit on how far one may lean.

Spec: FR-4.15, open decision 3, §12's cold-start row.

Cold start is the common case, not the edge case: most sessions in Phase 1 are
a student's first, so the graph has to be useful at n = 0. The spec's answer is
a cohort prior — branch, with an institute fallback below n = 30.

**The arithmetic says you cannot lean on it as hard as the spec assumes.**
Open decision 3 requires the prior to be "gone by n = 3", and the simulation
harness (`simulation.wash_out`) measures what is actually left. With
`SE_PRIOR = 1.5` and typical items (a ~ U(0.8, 2.0)), three binary responses
carry roughly

    I(3 items) ~ 3 * a^2 * p(1-p) ~ 1.5      prior precision = 1/1.5^2 = 0.44

so the prior still holds about `0.44 / (0.44 + 1.5)` ~ **23%** of the posterior
after three answers. Measured on 120 synthetic students, a 2.0-logit gap
between two branch priors leaves **0.77 logits** at n = 3 — a third of it, and
far more than the tenth of a logit at which two students stop sharing a
five-state label.

That is the same class of error as the decay curve that could never fire: a
requirement the arithmetic forbids, stated as if it were a threshold. It has
two honest resolutions and only one of them is fair:

    1. Wait longer.        Let the prior run and declare it washed out at
                           n = 8 instead. But between n=1 and n=8 the platform
                           is showing a student a number driven by which
                           branch they are in, and that is precisely the
                           fairness problem open decision 3 exists to avoid.
    2. Lean less.          Cap how far apart two cohort priors may be, so that
                           whatever survives at n = 3 is below display
                           resolution.

We take (2). The residual is linear in the gap — 0.385 x gap at n = 3, from
the harness — so a gap under `0.10 / 0.385 = 0.26` logits is invisible by the
time a student has answered three questions.

**What this costs.** Very little of what a prior was ever going to buy. A
branch prior's job is to stop the very first question being chosen as though a
final-year CSE student and a first-year were identical; a quarter of a logit
does that. A prior big enough to still matter at n = 3 is a prior big enough to
tell a student something about their branch rather than about themselves.
"""

from __future__ import annotations

from ai_core.mastery import SE_PRIOR

#: Maximum spread between any two cohort priors, in logits. Derived above, and
#: enforced rather than documented — see `clamp_prior`.
MAX_COHORT_PRIOR_GAP = 0.25

#: Below this many students in a cohort, its mean is noise. Open decision 3:
#: branch, with the institute as the fallback.
MIN_COHORT_SIZE = 30

#: The fraction of a cold-start prior still present after three responses,
#: measured by `simulation.wash_out` at SE_PRIOR = 1.5. Recorded so that a
#: change to SE_PRIOR forces someone to re-derive the cap rather than assume
#: it still holds.
RESIDUAL_AT_N3 = 0.385


def clamp_prior(offset: float) -> float:
    """A cohort prior offset, limited to half the permitted gap either side.

    Callers pass the raw difference between their cohort's mean ability and the
    institute mean; what comes back is what may actually be used as a prior.
    """
    limit = MAX_COHORT_PRIOR_GAP / 2.0
    return max(-limit, min(limit, offset))


def cold_start_prior(
    cohort_mean: float | None,
    institute_mean: float | None,
    cohort_size: int,
) -> tuple[float, float]:
    """`(theta_prior, se_prior)` for a candidate with no observations.

    Returns the institute prior when the cohort is too small to mean anything,
    and a flat prior when neither is known — which is the honest Phase-1 answer
    and the one every test in this suite exercises.

    `se_prior` is always `SE_PRIOR`: a cohort tells you where to START looking,
    never how sure to be. Narrowing the error bar because of someone's branch
    is the version of this that would genuinely be indefensible.
    """
    if cohort_mean is not None and cohort_size >= MIN_COHORT_SIZE:
        return clamp_prior(cohort_mean), SE_PRIOR
    if institute_mean is not None:
        return clamp_prior(institute_mean), SE_PRIOR
    return 0.0, SE_PRIOR
