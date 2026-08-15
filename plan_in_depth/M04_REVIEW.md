# M04 — Plan Review, Before Implementation

> Reviewed: 2026-08-15 · Target: [M04_Skill_Graph_Memory.md](M04_Skill_Graph_Memory.md) · Reviewed against M15's shipped code, the master plan, and the eight sibling specs that consume M04.
>
> **Status of evidence.** Six independent review passes (psychometrics, storage, cross-module contracts, product/trust, research, technology fit) produced 87 findings. The adversarial verification pass did not complete, so nothing here is machine-confirmed. Everything in **Part 1** and **Part 2** below I re-checked by hand — by grep against the repo, by executing the arithmetic, or by reading the sibling spec — and those checks are shown inline. Findings marked *(unverified)* are single-pass and worth a second look before you act on them.

---

## Verdict

The product reasoning in M04 is the best in the plan set, and three of its rules are genuinely better than the master plan they came from: **evidence of competence propagates, evidence of failure does not** (§6.4); **decay widens SE and never lowers θ** (§6.5); and **one write path or no write at all** (§6.2). Keep all three untouched — they are what makes this module defensible in a viva.

The problem is that M04 is written as a *self-contained module* when its actual job is to be *the contract surface eighteen other modules read and write*. Everything that is wrong follows from that. The estimator section specifies a likelihood the data contract cannot feed. The storage section is written for Postgres + pgvector + Redis, none of which this project runs. The P0 gate depends on a type that exists nowhere. And the one module already shipped — M15 — calls M04 with a key space M04 does not publish.

None of this is deep. It is roughly **two days of contract work** and about **four days of honest re-estimation**, and it must happen before M05, because M05 inherits every one of these decisions on day one. The 14-day build order in §14 is really ~18 days; Part 8 rebuilds it and Part 9 says what to cut.

---

## Part 1 — Settle these before writing a line of M04

Seven decisions. Everything downstream inherits them, and each is cheap now and a migration later.

### 1.1 `EvidenceRef` does not exist — define it in Platform_Core

**Verified.** `grep -rn "EvidenceRef" plan_in_depth/` returns six uses (M04 ×2, M16 ×3, M19 ×1) and **zero definitions**. M13 defines `EvidenceSpan` instead. M19 — which owns the ledger the type points into — is Phase 2–4.

So M04's headline gate, AC-4.1 *"Every mastery change traces to a resolvable evidence ref — 100%"*, is a gate on an undefined predicate, and `assert_evidence_resolves()` on build day 3 has nothing to resolve against.

The circularity resolves cleanly once you notice **M04's own episodic tier is the Phase-1 evidence store**. §6.6 already says so: *"Episodic — every turn, evaluation… Immutable rows. This is the substrate everything else can be rebuilt from."* M19's ledger becomes a projection over it in Phase 2, not a prerequisite for it.

Put the type in `Platform_Core` v0.2.0 — the argument `dependencies.txt` already makes for `SourceChip` applies verbatim ("copied into nineteen repos they would drift"):

```python
# ai_core/evidence.py
class EvidenceSpan(BaseModel):        # M13's shape, unchanged, moved here
    artifact_type: Literal["transcript","code","canvas","audio","notes","submission"]
    artifact_id: UUID
    start: int
    end: int
    quote: str                        # verbatim
    t_ms: int | None = None
    verified: bool = False

class EvidenceRef(BaseModel):
    """Why a number is what it is. Resolvable two ways, so it works before
    the Evidence Ledger (M19, Phase 2-4) exists."""
    kind: Literal["span","artifact","ledger"]
    session_id: UUID
    turn_id: UUID | None = None
    span: EvidenceSpan | None = None      # required when kind == "span"
    artifact_id: UUID | None = None
    ledger_entry_id: UUID | None = None   # None in Phase 1; backfilled by M19
    checksum: str                          # sha256 of the artifact at write time
```

**Resolution rule** (state it in §6.2, it is what the gate tests): the artifact row exists **and** `sha256(artifact) == checksum` **and**, if a span is present, `artifact[start:end] == quote` after whitespace normalisation. Otherwise the ref is *tombstoned* — which is exactly what EC-4.9 already assumes.

Change §5's field to `evidence: list[EvidenceRef] = Field(min_length=1)`. A `NOT NULL` JSONB column is satisfied by `[]`; the length check is what actually enforces FR-4.5.

**Also fix M16.** It uses `EvidenceRef` in three models and will inherit whatever you choose here.

### 1.2 `Observation` cannot feed the likelihood §6.3 specifies

**Verified by reading §5 against §6.3.** The likelihood is `P(correct|θ) = 1/(1+exp(-a(θ-b)))`. The contract carries no `a`, no `item_id` to look one up, and `difficulty` (the `b`) is `float | None` with **no stated behaviour when it is `None`** — which is the common case, since M05 §6.5 gives an item an MML-estimated `b` only at n ≥ 30 responses.

Three consequences, escalating:

1. Build day 5 is unimplementable as written. Whoever writes it will hardcode `a = 1.0` and `b = 0.0`, and those two invented constants will silently define the entire ability scale.
2. θ is only meaningful relative to the `b` scale. Mixed Elo-derived and defaulted `b` makes θ incomparable across concepts **and across time as M05 recalibrates nightly** — which makes §2.1 Moment 3 ("You're 30% better at DP than in March") fiction, for exactly the reason Trap 4 warns about but with item parameters instead of rubric versions.
3. `observations` is the only place the platform's item-response matrix could live, and it cannot store the item. Master plan D2 wants ≥ 8,000 responses as `candidate × item × outcome` for Paper 2. As specced, that dataset cannot be built.

```python
class ItemParams(BaseModel):
    """The item AS ADMINISTERED. Copied onto the observation, not referenced —
    M05 recalibrates nightly and θ must stay reproducible from what was true then."""
    question_id: UUID
    irt_model: Literal["2pl","grm","3pl"]
    a: float
    b: float | list[float]            # scalar, or GRM category thresholds
    c: float | None = None            # 3PL guessing — see 2.7
    se_b: float | None = None
    params_source: Literal["prior","elo","mml"]
    bank_version: str

class Observation(BaseModel):
    ...
    item: ItemParams | None           # None for self_reported / drill / probe
    theta_eligible: bool              # False when item is None — derived, stored
    theta_after: float                # posterior AFTER this observation
    se_after: float                   # SE AFTER this observation
    ontology_version: str
```

**The `None` branch, stated in §6.2:** an observation without `item` updates `n_observations`, `last_evidence_at` and the episodic tier, but **does not touch θ or SE**. This also gives you the mechanism to honour M05 §3.2.5 ("grounded items … never enter the IRT bank … not for ability estimation"), which the current write path has no way to respect.

`theta_after`/`se_after` are what make the trajectory chart and the evidence drawer reproducible without re-running the estimator.

### 1.3 Say who owns the ability estimate — M04 or M05

M04 §6.3 does an EAP update. M05 §6 runs a CAT that needs θ per item. M05's `SelectionRequest` takes `theta: dict[str,float]` as an *input*, which reads like M04 owns it — but M13's evaluation is async and will not have returned before the next question must be chosen. As written, neither module can supply an in-session θ.

Three sentences in §6.3 close it:

> **Who owns what.** M04 owns the *durable posterior* per `(candidate, concept)`: the only thing persisted, the only thing displayed, changed only through `record()`. M05 owns *item parameters* (`a`, `b`, `c`) and a *session-scoped provisional θ* held in `SessionState`: seeded from M04 at session bootstrap, updated in memory from the provisional score for selection only — never persisted, never displayed, discarded at session end. At session end M04 recomputes the posterior from the observations of record; if it disagrees with the provisional estimate the posterior wins silently, and a divergence > 0.5 logits is logged as a calibration signal.

Without this, both modules keep a θ and they drift — a two-source-of-truth bug across a repo boundary, which is the hardest kind to find.

### 1.4 The five states have no thresholds — publish them, with a consumer-facing scalar

**Verified.** `state: Literal["not_tested","emerging","weak","adequate","strong"]` appears in §5 with the comment "state is DERIVED" and **no derivation anywhere in the document**. §6.8 independently invents `theta < -0.3` for "weak"; §2.3's mock renders `ok` and `strong`, and `ok` is not in the enum.

Meanwhile M15's shipped `ranking.py` does `1.0 - float(theta)` and clamps to `[0,1]` — i.e. it is already treating θ as if it were a 0–1 probability. That is wrong against a logit scale and it is live code.

Publish both scalars and one boundary table in §5:

```python
class Mastery(BaseModel):
    theta: float             # logit, clamped [-4, 4]. M05's CAT and M19 analytics ONLY.
    se: float                # logit units. Prior 1.5.
    mastery_p: float | None  # 0-1. THE consumer scalar. None iff not displayable.
                             # mastery_p = 1 / (1 + exp(-theta))
    state: Literal["not_tested","emerging","weak","adequate","strong"]
```

| state | rule | student-facing string | bar treatment |
|---|---|---|---|
| `not_tested` | `n_direct == 0` | "not tested yet" | dashed outline, no fill |
| `emerging` | `n_direct < 2` or `se_effective ≥ 0.90` | "just started" | 20% hatched fill — a third *texture*, not a third colour |
| `weak` | `mastery_p < 0.45` | "needs work" | amber |
| `adequate` | `0.45 ≤ mastery_p < 0.70` | "solid" | green |
| `strong` | `mastery_p ≥ 0.70` | "strong" | green, full |

Two things fall out for free: `emerging` **is** the not-yet-displayable state, so `displayable` becomes `state not in ("not_tested","emerging")` and stops being a second competing rule; and M15's `gap_severity` becomes `1.0 - mastery_p`, correct by construction.

Note this is a **coordinated two-repo change** — M15's fixtures pass bare floats and its 216-test suite must move in the same PR pair.

### 1.5 Propagation must write rows, or AC-4.1 is false by construction

**Verified.** §6.4's `nudge_theta(prereq, +delta, cap_abs=0.20)` changes a stored mastery value with no `Observation` behind it. AC-4.1 says *every* mastery change traces to a resolvable evidence ref. So the module's own P0 gate fails on its own propagation step, and the evidence drawer that enforces platform Rule 3 has nothing to render for a propagated value.

Make propagation insert derived observations:

```python
kind = 'propagated'
evidence = obs.evidence            # the SOURCE observation's ref — genuinely the evidence, just indirect
source_concept_id = obs.concept_id
hops = hop
weight = damping**hop * strength
item = None
theta_eligible = False
counts_toward_n_direct = False
```

Split the counter: `n_direct` and `n_propagated` on `concept_mastery`, with `n_observations` as their sum. **Every state, display and bottleneck rule keys off `n_direct`.** A concept whose evidence is purely propagated renders as `not_tested` — no sixth state, no Rule 3 hole. The propagated θ still exists and is still used, by the one consumer that legitimately benefits from a prior it need not justify to a student: M05's selector.

And the drawer gets a better sentence than the current design allows:

> *"0.2 of this came from your dynamic-programming answers on Jun 12, not from a recursion question — worth checking recursion directly."*

### 1.6 Two consent columns, on day 2

**Verified.** `grep -cin "consent|IRB|ethic|DPDP|anonym|retention" M04_Skill_Graph_Memory.md` → **0**.

M04 holds the most sensitive derived data on the platform — `FailureSignature.kind = "gives_up_early"`, "you speak faster when you're unsure" — and its only privacy provision is FR-4.18 (export + hard delete). That is not DPDP 2023 compliance and it is not an ethics annexe.

Free now, a migration later:

- `observations.consent_id UUID NOT NULL`
- `candidate_facts.purpose TEXT NOT NULL` ∈ `{practice, institutional_reporting, research}`

Revoking research consent then becomes `WHERE purpose='research'` rather than a total wipe. Split FR-4.18 into **a** full export, **b** hard delete, **c** *partial revocation by purpose within 30 days* (P0).

Retention per tier, in §5: `observations` / `concept_mastery` → enrolment + 1 year. `candidate_facts` tier=`episodic` → same. **tier=`semantic` → enrolment + 90 days**, hard-deleted at graduation. Distilled behavioural inference is more sensitive than the raw turn it came from and should outlive it by *less*, not more.

Add **AC-4.10 [GATE]**: no endpoint under `/v1/candidates/{id}/` resolves for a caller who is not that candidate or a service principal, and no `FailureSignature` is reachable from any placement-cell surface at all. Write that last one as a loud rule, not an assumption.

The ethics annexe itself is half a day: the 8 `FailureSignature.kind` values with operational definitions, the `MemoryFact.kind` list, who reads each, retention per tier, deletion semantics. File it in week 1 — approval takes weeks and it is on the critical path for using pilot data in a paper.

### 1.7 Delete the SQL block — this project runs SQLite

**Verified.** §5's DDL uses `TIMESTAMPTZ`, `JSONB`, `TEXT[]`, `VECTOR(1024)`, `USING hnsw`, `DEFAULT now()`. `dependencies.txt` says: *"SQLite by default (zero setup). Set `DATABASE_URL` for Postgres."* M15 ships and runs with zero Postgres, zero Redis, zero pgvector — and `README.md`'s first promise is that a module "clones, installs and runs on its own."

Some of that DDL is a hard syntax error on SQLite. The worse half is what SQLite *accepts*: `VECTOR(1024)` and `TEXT[]` become text columns silently.

Replace §5's SQL with SQLModel classes in M15's shipped idiom (`models.py` + `schema.py`'s additive repair), plus one explicit two-store table saying what each store provides:

| Concern | SQLite (default) | Postgres (`DATABASE_URL` set) |
|---|---|---|
| Vectors | `float32` bytes in a BLOB, brute-force cosine in Python | `pgvector`, same query shape |
| Working tier | table + `stale` flag | table + `stale` flag (Redis optional) |
| Graph walk | `WITH RECURSIVE` (SQLite supports it) | `WITH RECURSIVE` |
| Timestamps | naive UTC, enforced by one helper | `TIMESTAMPTZ` |

One consequence worth stating: `days = (now - last_evidence_at).days` in §6.5 raises `TypeError` the first time it runs against SQLite, because the stored datetime comes back naive. One UTC helper, used everywhere.

---

## Part 2 — Estimator corrections (arithmetic re-checked)

### 2.1 Decay can never fire — the retention loop is dead on arrival

**Verified by arithmetic.** §6.5: `se_effective = se * (1 + 0.35*(1 - exp(-days/45)))`, capped at 1.35×. Then: *"When `se_effective` crosses 0.9 the concept becomes a spaced-repetition candidate."*

These two lines are incompatible. Crossing 0.9 requires stored `se ≥ 0.9/1.35 = 0.667`. But M05's stopping rule terminates a domain at `SE < 0.30`, so every concept the CAT actually finished sits at `se ≤ 0.30`, and `0.30 × 1.35 = 0.405` — at infinity.

| stored se | se_effective at 90d | at 365d | at ∞ | ever ≥ 0.9? |
|---|---|---|---|---|
| 0.30 (well measured) | 0.391 | 0.405 | 0.405 | **never** |
| 0.65 (mediocre) | 0.847 | 0.877 | 0.878 | **never** |
| 0.85 (barely displayable) | 1.107 | 1.147 | 1.148 | at ~30 days |

So the concepts a student was measured *well* on can never be re-tested, and the ones measured *badly* are re-tested constantly. That is precisely backwards, and it silently deletes EC-4.8, §2.1 Moment 5, and the M16 hand-off — while the §12 property test ("decay never lowers θ") passes happily. Nobody finds it until a pilot student returns after a semester and the platform has nothing to say.

Replace with additive variance drift, which saturates at the prior rather than at a multiple of a number that is already small:

```python
SIGMA_DRIFT = 0.45     # logits of true-ability drift per 90 days
SE_PRIOR    = 1.5
var_eff = min(se**2 + SIGMA_DRIFT**2 * (days / 90.0), SE_PRIOR**2)
se_effective = sqrt(var_eff)
```

`se = 0.30` → 0.541 at 90d, 0.708 at 183d, 0.955 at 365d. You can never become less certain than before you had any data — a property the current formula lacks.

Then **decouple the two thresholds that were conflated**, which is what caused this: `retest_candidate = (se_effective ≥ 0.55) or (days_since_evidence ≥ 120)`; `displayable` stays at 0.9. A well-measured concept becomes a re-test candidate at ~95 days — the right cadence for a placement cycle.

One document has to move: master plan §30.2 specifies a **power-law** forgetting curve, this is exponential/additive. Pick one or the thesis contains two forgetting models.

### 2.2 BKT's `P(T)=0.20` makes wrong answers raise mastery

**Verified by execution** of §6.3's own equations with §6.3's own priors:

```
P(L0)=0.15, P(T)=0.20, P(G)=0.20, P(S)=0.10 — student answers EVERYTHING wrong:
  after 1 wrong: p_known = 0.2173     ← went UP from 0.15
  after 2 wrong: 0.2268
  after 3 wrong: 0.2283
  after 8 wrong: 0.2286               ← hard floor
```

`P(T)` models learning *between practice opportunities*. In a mock interview nobody teaches you anything between question 3 and question 4, so within a session `P(T)` should be ~0. At 0.20 it dominates the evidence and the estimate is nonsense: a student who fails eight straight questions ends up "more known" than the prior.

Set `P(T) = 0.0` within a session; apply a between-session transit of `1 - exp(-days_gap/60)` scaled to a max of 0.15, only on the first observation of a new session. With `P(T)=0.05` the same all-wrong sequence gives 0.070 → 0.059 → 0.057, which is the correct shape.

Two related points:
- **"Parameters fitted per-concept from cohort data (EM)"** is not identifiable at any volume this project will reach. Four free parameters per concept × 180 concepts needs thousands of sequences *per concept*. Ship fixed priors, state that they are fixed, and fit a **single global set** across all concepts if you fit anything at all. *(unverified — but the parameter count argument is straightforward.)*
- **BKT and IRT are two beliefs about one latent quantity with no arbitration rule.** §6.2 updates both; decay and propagation touch only θ. So `bkt_p_known` and `theta` drift apart with time and no rule says which the UI believes. Recommendation: make θ/SE the single source of truth, keep `bkt_p_known` as a *display-only* companion computed on read, or cut BKT from Phase 1 entirely and spend the days on the GRM path.

### 2.3 `displayable` is inconsistent with its own priors

**Verified by arithmetic.** `displayable = n_observations >= 2 and se < 0.9`, with prior `se = 1.5`. Best case — perfectly targeted items at maximum Fisher information:

| discrimination `a` | observations needed for se < 0.9 |
|---|---|
| 0.8 | **5** |
| 1.0 | **4** |
| 1.2 | **3** |
| 1.5 | 2 |

So EC-4.2's "no bar shown until n≥2" is misleading — the SE gate binds, not the count. Combined with §3.2's own sizing rule (a 60-minute session meaningfully tests 4–8 concepts), the map is largely empty after session 2, which is exactly when §2.2's emotional arc says the student should feel recognised.

Replace the count with an information threshold: `displayable = (n_direct >= 2) and (se_effective < 0.9)`, and state in §2.3 that the map's promise is *"12 of 180 topics measured"*, not a full grid. Then check the interaction: with decay applied, a concept at `se = 0.85` crosses 0.9 at ~30 days and the bar **disappears**. A vanishing bar is worse than a lowered one — §3.2's own rule 3 ("decay must not look like regression") is violated by a mechanism it did not anticipate. Specify hysteresis: once displayed, a concept stays displayed and shows *"not checked since March"* instead of leaving the list.

### 2.4 `widen_se` is unbounded; `nudge_theta` fabricates certainty

`widen_se(desc, factor = 1 + damping**hop * strength * 0.25)` compounds multiplicatively with no clamp. Ten failed DP questions widen recursion's SE by ~1.9×; there is nothing stopping it exceeding the prior SD of 1.5, which is incoherent — you cannot know less than nothing. Clamp: `se = min(se * factor, SE_PRIOR)`.

`nudge_theta` moves the posterior *mean* without a likelihood and never touches SE. Raising θ while holding SE constant is a claim of evidence you do not have. Either move both (treat propagation as a weak pseudo-observation with its own likelihood) or move neither. Given §6.4's whole thesis is asymmetry, the cleaner form is: **success propagation raises θ *and* widens SE slightly**; failure propagation widens SE only. `cap_abs=0.20` also caps a single update, not the lifetime total — state the lifetime cap.

### 2.5 GRM — the dominant observation type — has no data structure

§6.3 disposes of Samejima in one sentence. But `outcome: float # normalised 0–1` destroys the ordinal category and `difficulty: float | None` cannot hold a threshold *vector*. M05's `IRTParams` correctly declares `b: float | list[float]`; M04's cannot exchange a GRM item with it.

M05 §3.1 Trap 2 names the exact failure: *"Using binary 2PL on rubric-scored answers … collapsing it to right/wrong throws away most of the information and biases `b`."* M05 §6.4 says *"GRM is the one that matters."* M04 is the module that owns the response and it cannot store one.

Add `response_model: Literal["2pl","grm","3pl","none"]`, `raw_category: int | None` (0..K, un-normalised), `n_categories: int | None`; keep `outcome` for display and BKT only, never for the likelihood. GRM is ~20 lines on top of the 2PL you are already writing — do it on day 5, not "later".

### 2.6 Nobody has said which M13 dimension becomes `outcome`

M13 emits *several* `DimensionScore` objects per turn (correctness, depth, communication, each 0–4 with its own anchors). No document states which becomes the single `outcome` float, or how they combine. This is arguably the most important unwritten function on the platform, and the default anyone will write — a weighted mean — silently folds communication into technical mastery.

Hard rule for §6.2, with a test: **one observation per (turn, concept), from the single rubric dimension nominated as concept-bearing for that round type (default `correctness`); `communication`/`delivery` dimensions map only to `domain='communication'` concepts and never to technical ones.** Add `source_dimension_key: str` to `Observation` so it is auditable.

### 2.7 Smaller, still real

- **No guessing parameter**, though `mcq_answered` is a first-class `kind` and M05 specifies 3PL for aptitude. A 4-option MCQ answered by a student at θ = −2 is right 25% of the time; 2PL reads that as ability.
- **Local dependence is ignored.** Five questions on one concept in one session are not conditionally independent. Treating them as independent understates SE by roughly √(1+ρ(k−1)); at ρ≈0.2, k=5 that is ~1.35×. It inflates M05's stopping rule (it stops early, believing it knows more than it does) and it is the kind of thing a Paper 2 reviewer asks about first. Minimum viable fix: cap the *effective* count per concept per session at 3 for SE purposes, and say so.
- **`weight` scales the likelihood** is a no-op if implemented literally on a log-likelihood sum and fabricates precision if `w > 1`. Restrict to `w ∈ (0,1]` and define it as likelihood tempering: `logL_eff = w · logL`.
- **`se` vs `se_effective` is never resolved.** Three consumers need different ones: `displayable` and the CAT need `se_effective` (decay-aware); the golden test needs stored `se`. State which is persisted (`se`) and that `se_effective` is computed on read, everywhere, from one function.
- **"41-point Gauss–Hermite quadrature on θ ∈ [-4,4]"** conflates two rules — Gauss–Hermite is for integrals against `exp(-x²)` over the whole line; a fixed grid on a bounded interval is Gauss–Legendre or plain rectangular. Say "41-point fixed grid on [-4.5, 4.5], trapezoidal" and move on. The grid is also slightly narrow for a prior SD of 1.5.
- **EC-4.3 demands person-fit behaviour** ("fails easy, passes hard … flag `inconsistent`") but no person-fit statistic is specified. Standardised `l_z` is ~15 lines and gives EC-4.3 a real trigger.
- **Secondary concept weights are unrepresentable.** One answer that touches DP *and* recursion updates both at full strength, then propagation counts it a third time. M05's `Question.concepts` is `list[ConceptWeight]` — mirror that weight into the observation.

---

## Part 3 — Cross-module contracts

### 3.1 M15 already calls an endpoint §7 does not define

**Verified in shipped code.** `router.py:111` gates on `deps.is_available("M04")`; `assembly.py:287` and `ranking.py:150` consume `candidate_theta: Mapping[str, float] | None`. `module.json` probes `health_path: "/health"`.

§7 has no `/health` at all, and its `GET /v1/candidates/{id}/mastery` returns a shape nobody has agreed on. Worse, M15's keys are **free-text topic labels from student reports** ("Dynamic Programming", "DP", "dp problems"), while M04's are **stable concept IDs** (`concept:dynamic_programming`). Nothing in the spec resolves one to the other, even though §5 has an `aliases` field that exists for exactly this.

Add to §7:

```
GET  /health                                   → {"status","ontology_version"}
GET  /v1/deps
POST /v1/concepts/resolve                      {"labels": [...]} → {label: concept_id | null}
GET  /v1/skill-graph/theta?candidate=&concepts=
     → {"per_topic": {"concept:recursion": {"theta":-1.2,"se":0.7,"mastery_p":0.23,
                       "state":"weak","n_direct":4,"last_evidence_at":"..."}}}
```

The resolver endpoint is the thing five modules will need and none of them has. Ship it with the alias table on day 1.

### 3.2 `concepts` and `concept_edges` have no schema at all

**Verified.** §5's SQL block defines `concept_mastery`, `observations`, `candidate_facts` — and nothing else. §6.8 queries `concept_edges` and `REFERENCES concepts(id)`. FR-4.1 and FR-4.2 (versioned DAG, acyclicity enforced at write time) are both P0 against tables that do not exist in the document.

Add both, with `ontology_version` on every row — and add `ontology_version` to `concept_mastery` and `observations` too, because **EC-4.4 (concept removed) and EC-4.5 (concept split) are unexecutable without a version column to migrate on**.

### 3.3 The bottleneck query is not recursive and disagrees with its own screen

**Verified.** §11 bills it as a "Recursive CTE"; §6.8's SQL is two plain CTEs and a single join — one hop. It cannot find "the earliest unmastered prerequisite", only direct parents.

Second mismatch: `weak` is defined as `n_observations >= 2 AND theta < -0.3`, which **excludes untested concepts** — while §2.3's mock shows Recursion flagged "⚠ this blocks 4" with `Backtracking … not tested` counted underneath. The number on screen and the number in SQL will differ, on the module's only call to action.

```sql
WITH RECURSIVE target AS (           -- weak OR untested, matching §2.3
  SELECT c.id FROM concepts c
  LEFT JOIN concept_mastery m ON m.concept_id = c.id AND m.candidate_id = :cid
  WHERE c.ontology_version = :ov
    AND (m.concept_id IS NULL OR (m.n_direct >= 2 AND m.theta < -0.3))
), up(target_id, blocker, hop, path_strength) AS (
  SELECT t.id, e.src, 1, e.strength
    FROM target t JOIN concept_edges e ON e.dst = t.id
   WHERE e.kind = 'prerequisite_of'
  UNION ALL
  SELECT u.target_id, e.src, u.hop+1, u.path_strength * e.strength
    FROM up u JOIN concept_edges e ON e.dst = u.blocker
   WHERE e.kind = 'prerequisite_of' AND u.hop < 3
)
SELECT u.blocker, count(DISTINCT u.target_id) AS blocks,
       sum(u.path_strength) AS weighted_blocks, m.theta, m.se
  FROM up u LEFT JOIN concept_mastery m
    ON m.concept_id = u.blocker AND m.candidate_id = :cid
 GROUP BY u.blocker, m.theta, m.se
HAVING m.theta IS NULL OR m.theta < 0.2
 ORDER BY weighted_blocks DESC, m.theta ASC NULLS FIRST LIMIT 3;
```

Two semantics to state in prose because they are *why* it must be recursive: stop walking a path once a blocker is itself mastered (so you surface the earliest *unmastered* ancestor, not always `concept:arrays`); and rank by strength-decayed `weighted_blocks`, so a hop-2 blocker behind a 0.4 edge does not outrank a hop-1 blocker behind a 0.9 one.

`WITH RECURSIVE` works on SQLite, so this stays consistent with clone-and-run. Add a unit test asserting the number the query returns equals the number `BottleneckCard` renders.

Also: M16 §6.4a adds a **foundational floor** ("if the earliest prerequisite is 'variables', the advice is insulting") and cites "M4 §30.8" — a section that exists in neither document. Put the floor in M04's query and fix M16's reference.

### 3.4 M04 should own the re-test queue

§2.4 promises dispute → "schedules a re-test" → "notify when resolved". There is no table, no owner, no interim state, and M05's freshness filter (never repeat an item within 90 days) would actively *block* the re-test. M16, which might own scheduling, is Phase 4.

One table in M04 serves five producers:

```sql
CREATE TABLE retest_queue (
  id, candidate_id, concept_id,
  reason TEXT,          -- 'dispute'|'inconsistent'|'decay'|'propagated_unverified'|'counselor'
  requested_by TEXT,    -- 'M04'|'M13'|'M16'
  source_ref JSONB, priority REAL DEFAULT 1.0,
  bypass_freshness BOOL DEFAULT true,      -- overrides M05's 90-day filter
  created_at, expires_at, resolved_at, resolved_by_observation_id
);
```

Then M05 reads it as a selection input, and the student-facing state exists: *"We've queued a recursion question for your next session."*

### 3.5 Other contract gaps worth a line each

- **No way to retract an observation.** M05 EC-5.9 (student flags an item → excluded from *their* θ), M13 re-scores, EC-4.10 account merges, and dispute resolution all need it. Add `retracted_at` + `retraction_reason` and recompute rather than compensating-update.
- **Only `rubric_version` is stamped.** Four other versions silently invalidate θ: `estimator_version`, `ontology_version`, `item_bank_version`, `prompt_version`. M19's `VersionStamp` already has the right shape including `code_sha` — reuse it, don't invent a subset.
- **The M16 hand-off has no contract** beyond the words "hand-off to M16", and both modules model forgetting over the same event stream. Define it as: M04 publishes `retest_queue` rows; M16 reads and schedules. One direction, one table.
- **Platform_Core placement.** By M15's own test ("what a sourced fact looks like is a platform contract; layout is not"), four M04 types belong in `ai_core`: `EvidenceRef`, `EvidenceSpan`, `Concept`/`ConceptEdge` (M01, M02, M05, M15 all resolve against them) and the state-threshold function. `MasteryBar` is a contract too — the five-state rendering is a platform promise (FR-4.9, AC-4.2) and a nineteenth copy is how "not tested ≠ weak" quietly stops being true.

---

## Part 4 — Write path and runtime

- **`record()` has no idempotency key**, and §10's own fallback ("observation queued to `observations_pending`, replayed by a worker") is therefore a mastery-corruption path: a replayed observation counts twice. Make the id a content hash — `uuid5(OBS_NAMESPACE, f"{turn_id or session_id}|{concept_id}|{kind}|{rubric_version}")` — with the namespace constant *in the spec* so every caller derives the same id, and insert with `ON CONFLICT DO NOTHING`.
- **Concurrent `record()` loses updates.** The posterior update is read-modify-write with no version column and no row lock. M13 writing 8 observations for one session concurrently will drop some. Add `version INT` to `concept_mastery` and write conditionally with 3 retries, raising `ContendedMastery` rather than silently dropping. Also fix `propagate()`'s lock order — walk affected concept ids **sorted** to avoid deadlock on Postgres.
- **`invalidate_cache()` and `emit_event()` run inside the transaction.** Classic stale-cache-and-phantom-event pair: the event fires for a transaction that may roll back. Move both after commit; use a table outbox for the event.
- **The "materialised view" is named five times and defined nowhere**, and it cannot be a Postgres `MATERIALIZED VIEW` — those cannot be incrementally refreshed, so refreshing on every write is a non-starter. It is a **table with a `stale` flag**. Say so.
- **The 1,200-token profile summary is invalidated on every observation**, which makes the context M06 injects volatile *mid-session* and destroys its prompt cache. Split the belief (live) from the injected context (frozen): add `session_profile_snapshot(session_id, summary_text, summary_version, built_at)`, change §7 to `GET /profile-summary?session_id=`, and have `record()` invalidate the *next* session's snapshot. In-session mastery movement already reaches the interviewer through the correct channel — M05's selector reads live mastery. Add **AC-4.13**: `profile-summary` for a fixed `session_id` is byte-identical across 10 calls with `record()` interleaved.
- **The embedding model and version are not recorded** — `produced_by_model` is the *distillation* model, not the embedder. This directly violates master plan §20.3 ("store in pgvector with the embedding model + version recorded alongside, so you can re-embed"). Add `embedding_model` + `embedding_version`. Also: `VECTOR(1024)` silently picks a model nobody chose.
- **Drop the HNSW index.** Every memory search is candidate-scoped over a few hundred rows. Brute-force cosine is sub-millisecond at that size and works identically on both stores. HNSW is a Phase-3 optimisation at the earliest.
- **"No LLM on any read path" is not true of `/memory/search`** — the query must be embedded. Either budget the round trip inside FR-4.17's 400 ms or restate the claim as "no LLM on any *mastery* read path", which is the one that actually matters.
- **AC-4.3's CI grep cannot hold** in a one-module repo — the writes it forbids live in eighteen other repos. Make it two things: a local grep for `UPDATE.*concept_mastery` outside `store.py`, and a runtime guard (the ORM session for mastery tables is only obtainable inside `record()`).
- **`POST /observations` is "internal only, service-to-service" with no mechanism.** M15 has no auth at all. Minimum: a shared-secret header read from `keys.txt`, checked by one dependency, with the check tested. And say which database `observations_pending` lives in — it must be M04's, or the fallback fails with M04.

---

## Part 5 — Product, trust and the screens

- **The mastery map is designed for a state that will never occur.** §2.3's mock shows 8 rows; at 180 concepts with 12 tested the real screen is ~93% empty, and there is no sparse state anywhere in §8. Restructure as **measured-first, untested collapsed to a count and a verb** — header reads `12 of 180 topics measured`; never render a not-tested concept as its own row; a `NOT YET TESTED (168) — [ Take a 15-min check → ]` block at the bottom.
- **Moment 1 — "the retention hook" — has no producing mechanism.** *"Last time you broke on how indexes work"* requires a break-point fact with human-readable phrasing, and §11 forbids an LLM on the read path, so the sentence must be **written at distillation time and stored**. Add `MemoryFact.display_sentence: str` with the same validation screens as everything else. And write the fallback ladder, because AC-4.6 demands 100% and the current design can only meet it by fabricating:

  1. break point exists → *"Last time you broke on how indexes work. Let's start there."*
  2. no break point, did well → *"Last time you were solid on hashing. Let's push into something harder."*
  3. first return, nothing notable → *"Welcome back. Last time we covered arrays and hashing — want to keep going, or switch?"*
  4. > 60 days away → *"It's been a while. Let's re-check a couple of things before we go deep."*

- **`FailureSignature` is trait inference and it breaks a sibling module's P0 rule.** M12 FR-12.15 is *"Never infer emotion, personality, honesty, or hireability"*, enforced by a CI grep **over the entire codebase and frontend bundle**. M04 stores `confidently_wrong`, `gives_up_early`, `freeze_on_ambiguity` as dispositional labels with **no evidence field at all** — the one object in M04 that escapes Rule 3. Fix both halves: add `evidence: list[EvidenceRef]` and `observed_episodes: int`, and rename to behavioural descriptions of what was observed (`abandoned_before_hint`, `answer_confidence_exceeded_correctness`, `paused_>20s_on_underspecified_prompt`). Then state in §8 that these are never rendered to anyone but the student.
- **Three different operations share the word "delete."** FR-4.18 hard-deletes; §5 says facts are "superseded, never deleted"; §8 gives the student a per-fact ✕. Write the table: per-fact ✕ = supersede + exclude from retrieval + 30-day suppression; account deletion = hard delete of facts and observations; research revocation = `WHERE purpose='research'`. And decide §15.5 now — **yes, re-derive after 30 days, never after a second deletion** — plus tell the student which one they are getting: *"I'll stop using this. If it shows up again in a future session I may notice it again — delete it twice and I'll stop for good."*
- **§8 omits two required subsections** from the template (all states, mobile) and its accessibility line specifies `aria-level` on a `<table>`, which is a `treeitem` attribute — on a table the prerequisite depth belongs in a real column, not an ARIA level.
- **AC-4.7 (dispute rate < 5%) is passed by hiding the dispute button.** The honest metric is the **upheld** rate — of disputes that triggered a re-test, what fraction moved the value materially. That is also a free mini-result for the paper.
- **"Legible in 5 seconds" is stated as a requirement and is untestable.** Make it the one AC that proves the screen works: 5 of 5 test students, shown the map for 5 seconds, correctly name their weakest area.

---

## Part 6 — Research plan

- **The DKT comparison is arithmetically unreachable.** §6.3 gates it at ≥ 20k interactions; the project's own year-end target is ~8,000 responses and the Phase-3 pilot gate is 60 students. The experiment is guaranteed inconclusive before it is run — and *this changes what you log from day 1*, so decide now. Rewrite it as an **external-validity study**: run BKT+IRT vs SAKT primarily on public KT benchmarks (ASSISTments 2009–10 skill-builder, corrected release; EdNet-KT1 subsampled for robustness) using an existing implementation (pyKT / EduKTM), and report your own cohort as a descriptive replication with bootstrap CIs and an explicit power statement. ~1 week, and it is reviewable.
- **The retrieval eval set is swept and scored on the same 50 queries.** §6.6 tunes four weights on it; AC-4.8 then reports nDCG@5 on it. That is training on the test set, and 50 queries is underpowered for a 4-term ablation. Split 150 queries into dev (100, for the sweep) and test (50, touched once), have two annotators label with a reported agreement, and name the baselines that make it a result: **vector-only, BM25, recency-only, no-memory control, and Mem0** — which is simultaneously the answer to the examiner's obvious question, "why not just use Mem0 or Zep?" That question currently has **zero hits** in the spec.
- **AC-4.4 is circular.** Simulating students from the 2PL you then fit tests your quadrature code, not your estimator. Specify a mis-specification grid: simulate under GRM and score under 2PL; simulate with local dependence ρ = 0.2; simulate with 20% item-parameter drift; simulate a non-normal ability distribution. Report recovery under each. *That* is a result.
- **Name the falsifiable claim.** "It remembers" is not one. The strongest available and cheapest to run: **carried posterior vs session-local flat prior on items-to-SE-0.3** — measurable in simulation *and* live, powered at n ≈ 30 returning students, directly answers "what does memory buy you", and pays into Paper 2 rather than a sixth paper nobody will write. Pre-register it.
- **Nothing is stamped for reproduction.** Add `code_sha`, `estimator_version`, `prompt_version`, seed and dataset hash to every simulation run and every distillation batch — M19's `VersionStamp` is the right shape. Minimum viable tracking: a `runs/` directory with one JSON per run and DVC on the eval sets. W&B is optional; the stamps are not.
- **The simulation harness is the backbone of two papers and it is one day, at the end, sharing day 14 with a faculty meeting.** Move it to day 4–5, before the estimators are finished — it is how you find the decay bug and the BKT floor in an afternoon instead of in a pilot.
- **AC-4.9 (faculty sign-off) gates Phase 1 exit and is scheduled on day 14.** It is a dependency on someone else's calendar. Book it in week 1, review 120 concepts not 450, and give the reviewer a tool (see Streamlit, below) rather than a YAML file.

---

## Part 7 — Technology additions worth making

Mapped against the skills profile you supplied, cloud and Kubernetes excluded as asked. **Skipping is the honest answer for most of the agent frameworks** — M15 already proved plain Python + structured outputs + deterministic screens is sufficient at 10,700 lines, and master plan §22 explicitly warns against heavyweight agent frameworks as hard dependencies.

| Technology | Where it plugs into M04 | Cost | Lost if skipped | Verdict |
|---|---|---|---|---|
| **Structured outputs w/ constrained enums** | §6.6 distillation: `evidence_turn_ids` as a JSON-Schema `enum` of *this candidate's* turn ids | in the 2d below | hallucinated ids reach a student | **Adopt now** |
| **Guardrails — port M15's four screens** | new §6.6b, from `talking_points.py` + `ingest/validate.py` | 2d | the one LLM writing prose about a student is unvalidated | **Adopt now — highest value item here** |
| **`ai_core.llm`** (promote M15's `llm.py`) | §6.6, §6.7 | 1d | 2nd copy of provider/routing/cost/NullLLM; drift | **Adopt now** |
| **Cost telemetry** (M15's model-call tables → `ai_core.telemetry`) | §11 budget, §13 | in the 1d above | no way to know the ₹ budget is being met | **Adopt now** |
| **Knowledge engineering — `ontology_lint`** | §6.1: acyclicity, orphan concepts, granularity (>40 / <3 questions), alias collisions | 0.5d | Trap 5 lands anyway, silently | **Adopt now** |
| **Context engineering — pinned profile snapshot** | §6.6 working tier (see Part 4) | 0.5d | M06's prompt cache thrashes; ₹ and latency | **Adopt now** |
| **Streamlit ops app** (:8304) — ontology review, simulation dashboard, retrieval eval workbench | §6.1, §12, §6.6 | 1.5d | AC-4.9 stays un-achievable; faculty review over raw YAML | **Adopt now** — cheapest high-value item |
| **RAG / hybrid retrieval** | §6.6 — *already the core of the module*; just name it as such | — | — | Already there |
| **Custom IR eval harness** (~120 lines: nDCG@5, MRR, per-term ablation) | §6.6 eval, AC-4.8 | 0.5d | — | **Adopt now** |
| **Event-driven — table outbox** | §6.2 `emit_event` | 0.5d | dual-write bug | **Adopt now** |
| **Vector DB (pgvector HNSW / Qdrant)** | §5 `candidate_facts` | — | nothing at 300 students; brute-force cosine wins | **Skip** — revisit Phase 3 |
| **Redis + Arq** | §6.6 working tier, job queue | — | nothing yet; a table + `stale` flag covers it | **Adopt later** (M06 needs it first) |
| **Langfuse** | LLM tracing | — | little in M04 (2 LLM jobs, batch); real value in M06's live loop | **Adopt later** — port 3001 already reserved |
| **OpenTelemetry / AgentOps** | — | — | nothing; you have no distributed traces to correlate | **Skip** |
| **LangGraph** | §6.6 distillation, §6.7 re-score | — | nothing — these are linear batch pipelines, not state machines | **Skip in M04**; the honest home is M06's interview loop |
| **PydanticAI** | distillation calls | — | nothing over `llm.structured()` which already exists | **Skip** |
| **CrewAI / AutoGen / LangChain** | — | — | nothing. M04 is a data + estimation module; multi-agent coordination here is bloat, and §22 warns against it | **Skip** |
| **RAGAS / DeepEval / promptfoo / Inspect** | §6.6 eval | — | nothing — you have ground-truth relevance labels, so you want IR metrics, not LLM-judged ones | **Skip** |

**On cost.** §11's ₹0.8/active student/night is calendar-triggered and uncapped: 300 students × 365 nights = **₹87,600/year** for nightly distillation, most of it re-distilling students who did nothing that day. Two controls, both one line: trigger on *session-completed*, not on the calendar; and cap per student per month. That takes the same workload to roughly ₹6–10k/year.

**"Responsible AI" as artefacts, not a buzzword** — four concrete things, each with an owner and a test: the cohort-prior fairness check (§15.3, must provably wash out by n≈3 — otherwise a branch-level prior is a fairness problem sitting inside Paper 2); the no-trait-inference gate (Part 5); the deletion semantics table; and the purpose-limitation column from §1.6.

---

## Part 8 — Revised build order

§14's 14 days is really ~18. Adds: distillation done properly **+2**, Streamlit ops app **+1.5**, `ai_core` promotion **+1**, `ontology_lint` **+0.5**, concurrency/idempotency **+1**, fairness + deletion tests **+0.5**. Removes: no pgvector/HNSW/Redis setup **−1**, no eval framework to learn **−0.5**.

Restructured so **M04 clones and runs alone** — no day depends on M13 existing, and the two calendar dependencies (faculty, ethics) start in week 1.

| Milestone | Days | Demoable outcome |
|---|---|---|
| **M0 — Contracts** | 1–2 | `ai_core` v0.2.0 published: `EvidenceRef`, `EvidenceSpan`, `Concept`, `ConceptEdge`, state thresholds. **Ethics annexe filed. Faculty review booked.** |
| **M1 — Ontology** | 2–4 | 120 concepts in YAML, loader, DAG validation, `ontology_lint`, alias table, `POST /concepts/resolve`. `GET /health` + `/v1/deps` green. |
| **M2 — Store & write path** | 4–7 | SQLModel schema (both stores), `record()` with evidence enforcement, uuid5 idempotency, optimistic lock, outbox. Adversarial tests pass. |
| **M3 — Simulation first** | 7–8 | 200 synthetic students, known abilities, **mis-specification grid**. This is the harness that catches 2.1–2.4 before you ship them. |
| **M4 — Estimators** | 8–11 | IRT EAP (2PL + **GRM**), fixed-prior BKT as display companion, asymmetric propagation writing real rows, additive-drift decay, clamps. Golden snapshot frozen. |
| **M5 — Read paths** | 11–13 | Working tier table + pinned session snapshot, `/theta`, `/profile-summary`, evidence drawer endpoint, recursive bottleneck query, `retest_queue`. **M15's preparation block lights up.** |
| **M6 — Memory tiers** | 13–16 | Episodic writes (seam, fed by a fixture not by M13), distillation with the four screens, hybrid retrieval, 150-query eval set, IR harness. |
| **M7 — Surfaces** | 16–18 | Mastery map with the sparse state, "what I remember about you" with real deletion, dispute endpoint. Streamlit ops app. |

Faculty sign-off lands whenever their calendar allows; nothing blocks on it after M1.

---

## Part 9 — Cut list

Mandatory, in order of least regret:

1. **BKT's per-concept EM fit** → fixed global priors, stated as fixed. Not identifiable at any volume you will reach. *(Consider cutting BKT from Phase 1 entirely and making θ/SE the single source of truth — it removes the arbitration problem in 2.2 for free.)*
2. **Ontology 450 → 120** for Phase 1 (§15.1 already recommends 180). 120 covering DSA + CS core is what M05 can realistically seed 3+ calibrated items per concept for — otherwise §6.1's own granularity check fails on day one. Growth is a YAML append.
3. **`TrajectoryChart` + rubric-version boundary markers** → M19 owns charts and is Phase 2–4. Ship `GET /trajectory` (the contract M19 needs) and no chart. None of §2.1's six moments requires it.
4. **`DisputeDialog` UI** → ship the endpoint, the `retest_queue` row and the pending state; ship the dialog in Phase 2. The trust defence that actually carries §2.4 is the evidence drawer, and that stays.
5. **pgvector, HNSW, Redis, materialised views** → deferred, per Part 4. Postgres remains a `DATABASE_URL` away.
6. **DKT/SAKT in-house comparison** → replaced by the public-benchmark design in Part 6.

**Do not cut:** the "what I remember about you" screen with real deletion. It is the cheapest legibility win in the module, it is the responsible-AI artefact, and it is the best demo in the project.

---

## Part 10 — Open decisions (replaces §15)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Ontology size for Phase 1 | **120**, DSA + CS core + communication. Thin and correct beats large and wrong. |
| 2 | Expose θ to students? | **No** — 5-state label + `mastery_p`. (§15.2 was already right.) |
| 3 | Cohort prior — which cohort? | **Branch**, institute fallback at n < 30, **plus a published test that the prior washes out by n = 3.** Without that test it is a fairness problem inside Paper 2, not a Paper 3 topic. |
| 4 | Keep BKT in Phase 1? | **New decision.** Recommendation: keep as a display-only companion with fixed priors and `P(T)=0` within session — or cut it. Do not run two competing beliefs with no arbitration rule. |
| 5 | Who owns in-session θ? | **M05** (provisional, in-memory, discarded). M04 owns the durable posterior. Write it into §6.3. |
| 6 | Memory paper: Paper 2 or separate? | **Fold into Paper 2.** §15.4 defers to Month 6, which is after the annotation it requires must have started. The retrieval ablation is a section, not a paper. |
| 7 | Fact deletion re-derivation | **Yes after 30 days, never after a second deletion**, and tell the student that in those words. |
| 8 | Decay curve | **Additive variance drift** (2.1). Then amend master plan §30.2, which says power-law. |
| 9 | Does the placement cell ever see a failure signature? | **No.** Make it AC-4.10 and a CI grep, not an assumption. |

---

## What I would do first

Two days on Part 1, in this order: `EvidenceRef` into Platform_Core → `Observation` gains `item` and the ordinal → θ ownership line → state thresholds table → consent columns. Then start M05 on top of contracts that will not move under it.

The estimator bugs in Part 2 are real but they are *findable* once the simulation harness exists, which is why Part 8 moves it to day 7 instead of day 14.
