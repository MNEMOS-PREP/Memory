# M4 — Candidate Skill Graph & MNEMOS Memory Core

> **Master plan reference:** §30 · **Phase:** 1 · **Owner:** E3 · **Depends on:** `Platform_Core` v0.2.0 (evidence + concept contracts) and nothing else — no module is required to build, run or demo this one · **Feeds:** every other module
>
> **Revision 2** (2026-08-15) — reworked after [M04_REVIEW.md](M04_REVIEW.md). Substantive changes: `EvidenceRef` now defined and owned (§5.1); `Observation` carries the item, the ordinal and the versions its own likelihood needs (§5.2); the five states have published thresholds (§5.3); raw Postgres DDL replaced by a two-store schema (§5.4); the decay curve replaced — the previous one could never fire (§6.5); BKT's `P(T)` corrected — the previous value made wrong answers raise mastery (§6.3); propagation now writes real observations so AC-4.1 holds on M04's own write path (§6.4); the bottleneck query is actually recursive and honours a foundational floor (§6.8); the re-test queue has an owner (§6.9); consent, retention and access are specified (§4, §5.4, §7, AC-4.10/11); build order re-estimated at ~18 days (§14).

---

## 1. In one paragraph

This is the module the project is named after, and the reason the platform is a system rather than a pile of features. It holds two things: a **concept graph** (what there is to know, and what depends on what) and, per student, a **belief about what they know** — not a score, a posterior with uncertainty that decays over time. Every module reads it before acting and writes evidence-linked observations after. It is why the HR round knows what the technical round found, why the Company Guider surfaces *your* weak topics first, and why the Counselor can say "three weeks ago you froze on concurrency — look at you now." Users never see the words "skill graph". They see an interviewer that remembers them.

---

## 2. Reverse-thinking: the user

### 2.1 The user never sees this module — they feel it

There is no "Skill Graph" screen. There are **six moments** where the student experiences it, and if those moments don't land, the module has failed regardless of how elegant the graph is.

| # | Moment | What the student experiences | What's actually happening |
|---|---|---|---|
| 1 | Second session, minute one | *"Last time you broke on how indexes work. Let's start there."* | Read mastery + break points |
| 2 | Mid-session | The questions get harder because they're doing well | θ update → CAT selection |
| 3 | Report | "You're 30% better at DP than in March" | Trajectory over versioned scores |
| 4 | Company brief | Their weak topics are listed first | Gap-ordered ranking |
| 5 | Six weeks later | *"You haven't touched graphs since March — worth a refresh?"* | Confidence decay → spaced repetition |
| 6 | Counselor | *"Your DP problem is actually a recursion problem."* | Prerequisite bottleneck walk |

**Moment 1 is the retention hook.** Everything else is downstream of a student feeling recognised in the first ten seconds of their second session.

**What actually produces that sentence.** §11 forbids an LLM on the read path, and the opening line *is* a read — so the sentence is written at distillation time and stored in `MemoryFact.display_sentence`, through the four screens in §6.6b. It is not composed at session start; it is looked up.

AC-4.6 demands this fires for 100% of returning students, and the only way to hit 100% with one template is to fabricate. So there is a ladder, and these are the shipped strings:

| Condition | Opening line |
|---|---|
| A break point exists | *"Last time you broke on how indexes work. Let's start there."* |
| No break point, did well | *"Last time you were solid on hashing. Let's push into something harder."* |
| Returning, nothing notable | *"Welcome back. Last time we covered arrays and hashing — want to keep going, or switch?"* |
| Away > 60 days | *"It's been a while. Let's re-check a couple of things before we go deep."* |
| Session 1 was abandoned | *"We didn't get far last time. Want to pick up where we stopped, or start fresh?"* |

AC-4.6 measures rung 1–2 coverage separately from the fallbacks, because "we said *something*" and "we said something *specific*" are different products.

### 2.2 The emotional arc across sessions

```
Session 1   "It's a generic AI interviewer."                (indifference)
Session 2   "Wait — it remembered."                          (surprise → attachment)
Session 5   "I can see I'm actually getting better."         (momentum)
Session 12  "This thing knows me better than I do."          (dependence — the moat)
```

### 2.3 Where the student *does* see it directly: the mastery map

One screen, reachable from the dashboard, and it must be legible in 5 seconds:

The screen is **measured-first**. At 120 concepts with 12 tested, a full grid is ~90% empty, and an empty grid teaches a student the product is broken. Never render an untested concept as its own row — collapse the set to a count and a verb.

```
┌──────────────────────────────────────────────────────────────┐
│  What you know                    12 of 120 topics measured  │
│                                                              │
│  MEASURED (12)                              [ DSA ▾ ]        │
│   Arrays          ████████████░░  strong    tested 3×        │
│   Hashing         ██████████░░░░  strong    tested 2×        │
│   Two pointers    ███████░░░░░░░  solid     tested 2×        │
│   Recursion       ████░░░░░░░░░░  needs work · blocks 4      │
│      └ DP            ██░░░░░░░░░  needs work                 │
│      └ Trees         ███░░░░░░░░  needs work                 │
│   Sliding window  ▒▒▒▒░░░░░░░░░░  just started · tested 1×   │
│   Graphs          ███████░░░░░░░  solid  · not checked       │
│                                          since March         │
│                                                              │
│  NOT YET TESTED (108)          [ Take a 15-min check → ]     │
│   Backtracking · Tries · Union-find · Segment trees · …      │
│                                                              │
│  ⓘ "Recursion blocks 4 topics" — fixing it likely moves      │
│    backtracking, DP, and trees at the same time.             │
│                              [ Work on recursion → ]         │
└──────────────────────────────────────────────────────────────┘
```

**Five UX rules this screen must obey:**
1. **"Not tested" is visually distinct from "weak"** — dotted/empty vs filled-amber, plus the words. (README Rule 2, and it is violated by default in every bar-chart component ever written.)
2. **"Just started" is distinct from both** — a third *texture* (hatched), not a third colour, because the difference must survive greyscale and colour-blindness. See §5.3 for the five states and their strings; the internal enum name is never rendered.
3. **Indentation shows prerequisites.** The student learns the dependency structure just by looking, which is itself educational.
4. **A bar never disappears.** Decay greys it and adds "not checked since March" — it never removes the row. A vanishing bar breaks the same promise a falling one would (§3.2, rule 3).
5. **The bottleneck callout is the only call to action.** A map with 40 equal bars is a wall; a map with one arrow is a plan.

### 2.4 The trust failure that kills this module

If a student sees `DP: weak` after they solved a DP problem correctly, they stop believing the whole platform. Three defences:

- **Every mastery value is tappable** → shows the evidence: which sessions, which questions, which answers moved it. (Rule 3.)
- **A single bad turn cannot repaint the graph.** Damped updates + a minimum-evidence threshold before a value is displayed at all.
- **The student can dispute it**: *"This doesn't look right"* → flags for review and schedules a re-test rather than arguing. Being wrong occasionally is survivable; being wrong and unaccountable is not.

---

## 3. Reverse-thinking: the developer

### 3.1 The nine traps

**Trap 1 — Storing a single float per skill.** `dsa_score = 7.2` is unusable: you can't tell "never tested" from "tested and mediocre", you can't decay it honestly, and you can't select questions adaptively. *Counter: store a posterior — `(θ, standard_error, n_observations, last_evidence_at)` — and derive display values from it.*

**Trap 2 — Letting modules write mastery directly.** The moment M6 does `mastery.dp += 0.1`, the graph is no longer traceable and Rule 3 is dead. *Counter: a single write path, `MemoryStore.record(observation)`, where an observation without an evidence reference is rejected by the type system.*

**Trap 3 — Over-propagating through the prerequisite graph.** One failed DP question shouldn't downgrade recursion, arrays, and loops. Un-damped belief propagation makes the graph oscillate and produces absurd narratives. *Counter: damping 0.3, max 2 hops, and propagation only moves *uncertainty*, never the point estimate, on failure (§6.4).*

**Trap 4 — Comparing scores across rubric versions.** You change the rubric in month 5 and every "you improved 30%" claim silently becomes fiction. *Counter: every observation carries `rubric_version`; longitudinal queries are version-scoped; a rubric bump triggers a batch re-score (§6.7).*

**Trap 5 — Building the ontology by asking an LLM for 450 concepts.** You get a plausible-looking list with wrong prerequisites and inconsistent granularity, and every downstream number inherits the mess. *Counter: seed from actual syllabi and company topic lists, then have a faculty member review the edges. It's two days of unglamorous work and it is load-bearing.*

**Trap 6 — Vector-only memory retrieval.** "Find things similar to this question" surfaces a semantically related but three-months-stale, low-importance fact over yesterday's break point. *Counter: hybrid score with recency and importance (§6.6). This is also the exact thing we ablate for the paper.*

**Trap 7 — Specifying a likelihood the data contract cannot feed.** Revision 1 of this document specified `P(correct|θ) = 1/(1+exp(-a(θ-b)))` and an `Observation` carrying neither `a` nor an item reference, with `b` optional and no stated behaviour when absent. Whoever implemented it would have hardcoded two constants, and those constants would have silently defined the entire ability scale — while every test passed. *Counter: the item travels with the observation (§5.2), and `theta_eligible` is explicit rather than implied.* The general form of this trap: **an equation in a spec is not a specification until the contract above it can supply every symbol.**

**Trap 8 — Writing the storage section for the stack you wish you had.** Revision 1's DDL used `TIMESTAMPTZ`, `JSONB`, `TEXT[]`, `VECTOR(1024)` and an HNSW index; the project runs SQLite by default and the one shipped module uses none of that. Half of it is a syntax error and the other half is worse — SQLite accepts `VECTOR(1024)` as a text column without complaint. *Counter: one schema, two stores, stated explicitly (§5.4).* The rule this module keeps: **a P0 requirement that only holds on infrastructure nobody has running is not a requirement, it is a wish.**

**Trap 9 — Parameters nobody arithmetically checked.** Two of revision 1's constants were provably wrong, not debatable: a decay curve capped at 1.35× could never cross the threshold it fed, and `P(T) = 0.20` made a wrong answer *raise* mastery. Both were invisible to the tests that were written for them. *Counter: the simulation harness is built before the estimators (§14 M3), and §12's unit list names the specific sequences — all-wrong, well-measured-then-idle — that catch this class.*

### 3.2 The non-obvious hard parts

1. **Concept granularity is a product decision, not a taxonomy decision.** Too coarse ("DSA") and feedback is useless; too fine ("Kadane's algorithm") and you never accumulate enough observations per node to estimate anything. Rule of thumb: **a concept is right-sized if a 60-minute session can meaningfully test 4–8 of them** and if a student would recognise the name.
2. **Cold start is the common case, not the edge case.** Most sessions in Phase 1 will be a student's first. The graph must be *useful at n=0* — that means priors from cohort/branch/CGPA and honest "not tested" everywhere else.
3. **Decay must not look like regression.** If confidence decay lowers the displayed bar, students think they got worse by doing nothing. *Decay widens the error bar; it never lowers the estimate.* This is a one-line rule that saves a hundred support messages — and it has a corollary the first draft missed: **a bar must not vanish either.** Decay pushing a concept below the display threshold removes the row, and an absent bar is a worse message than a shorter one. Hysteresis, §6.5.
4. **The graph is read on the hot path.** A session start reads a slice; a question selection reads mastery for 20 concepts. Budget: < 120 ms. A summary table with a `stale` flag, rebuilt after commit; Redis if it happens to be there. Not a materialised view — Postgres cannot refresh one incrementally, so "refreshed on write" was never implementable. And the *injected* summary is pinned per session even though the belief underneath it is live (§6.6): mutating an interviewer's context between its own turns is a bug, and it invalidates M6's prompt cache on every observation.
5. **Memory must be re-derivable.** Every semantic fact records the model and prompt that produced it, so when models improve we can rebuild the whole semantic tier from immutable episodic records.

---

## 4. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | Maintain a versioned concept DAG with typed edges | P0 |
| FR-4.2 | Enforce acyclicity on `prerequisite_of` edges at write time | P0 |
| FR-4.3 | Store per-(candidate, concept) posterior: θ, SE, n_direct, n_propagated, last_evidence_at | P0 |
| FR-4.4 | Accept mastery updates **only** via evidence-linked observations | P0 |
| FR-4.5 | Reject any observation lacking a resolvable evidence reference | P0 |
| FR-4.6 | IRT (2PL + GRM) owns θ/SE; BKT is a display-only companion behind one interface | P0 |
| FR-4.7 | Damped prerequisite propagation, max 2 hops, written as derived observations | P1 |
| FR-4.8 | Confidence decay over time that widens SE and never lowers θ | P0 |
| FR-4.9 | Distinguish `not_tested` from `weak` at every API and UI boundary | P0 |
| FR-4.10 | Three memory tiers with a hybrid retrieval score | P0 |
| FR-4.11 | Version every semantic fact with its producing model, prompt **and embedder** | P0 |
| FR-4.12 | Support "why is this value what it is?" → evidence list | P0 |
| FR-4.13 | Support student dispute → flag + queued re-test | P1 |
| FR-4.14 | Bottleneck query: earliest unmastered prerequisite blocking the most targets | P0 |
| FR-4.15 | Cohort priors for cold start, with a published wash-out test | P1 |
| FR-4.16 | Batch re-score on rubric version change | P1 |
| FR-4.17 | Read latency p95 < 120 ms (working tier), < 400 ms (hybrid semantic) | P0 |
| FR-4.18a | Full export of a candidate's memory on request | P0 |
| FR-4.18b | Hard delete of a candidate's memory on request | P0 |
| FR-4.18c | Partial revocation by purpose (research / reporting) within 30 days | P0 |
| FR-4.19 | Track failure signatures alongside mastery, each evidence-linked | P1 |
| FR-4.20 | No observation or fact written without an active consent record | P0 |
| FR-4.21 | Resolve free-text skill labels to canonical concept ids (alias table) | P0 |
| FR-4.22 | Own the re-test queue; expose it to selection with a freshness bypass | P1 |
| FR-4.23 | Session-pinned profile summary: byte-identical for the life of a session | P0 |
| FR-4.24 | Propagated evidence never counts toward displayable mastery | P0 |
| FR-4.25 | Idempotent `record()`: replaying an observation is a no-op | P0 |
| FR-4.26 | Observations are retractable; mastery recomputes rather than compensates | P1 |

---

## 5. Data contracts

### 5.1 Platform types (live in `Platform_Core`, not here)

`EvidenceRef` is the atomic unit of justification for the whole platform — M13 produces them, M04 stores them, M19's ledger projects over them, M16 renders them. Nineteen copies would drift and "every number traces to evidence" would quietly stop being true in whichever repo fell behind. It ships in `ai_core.evidence` (Platform_Core v0.2.0), by the same argument `dependencies.txt` already makes for the provenance components.

```python
# ai_core/evidence.py — NOT defined in this module
class EvidenceSpan(BaseModel):
    artifact_type: Literal["transcript","code","canvas","audio","notes","submission"]
    artifact_id: UUID
    start: int; end: int
    quote: str                    # verbatim
    t_ms: int | None = None
    verified: bool = False

class EvidenceRef(BaseModel):
    """Why a number is what it is. Resolvable two ways, so it works in Phase 1
    before the Evidence Ledger (M19) exists."""
    kind: Literal["span","artifact","ledger"]
    session_id: UUID
    turn_id: UUID | None = None
    span: EvidenceSpan | None = None      # REQUIRED when kind == "span"
    artifact_id: UUID | None = None
    ledger_entry_id: UUID | None = None   # None in Phase 1; backfilled by M19
    checksum: str                          # sha256 of the artifact at write time
```

**Resolution** (this is what AC-4.1 tests): the artifact row exists **and** `sha256(artifact) == checksum` **and**, if a span is present, `artifact[start:end] == quote` after whitespace normalisation. Otherwise the ref is **tombstoned** — which is what EC-4.9 already assumes. In Phase 1 the resolver reads M04's own episodic tier; §6.6 already says that tier is "the substrate everything else can be rebuilt from", and that is exactly what makes it the Phase-1 evidence store. M19's ledger becomes a projection over it, not a prerequisite for it.

### 5.2 Module types

```python
class Concept(BaseModel):
    id: str                       # "concept:dynamic_programming" — stable, human-readable
    name: str
    domain: Literal["dsa","cs_core","ml","system_design","tooling",
                    "aptitude","communication","behavioural"]
    level: Literal["foundational","intermediate","advanced"]
    aliases: list[str]            # FR-4.21 — the resolver's source of truth
    foundational_floor: bool      # true = never surfaced as a bottleneck (M16 §6.4a)
    typical_question_time_s: int
    ontology_version: str

class ConceptEdge(BaseModel):
    src: str; dst: str
    kind: Literal["prerequisite_of","specialises","applies_to","co_occurs_with"]
    strength: float               # 0–1; how hard a dependency
    ontology_version: str

class ItemParams(BaseModel):
    """The item AS ADMINISTERED. Copied onto the observation, never referenced —
    M5 recalibrates nightly, and θ must stay reproducible from what was true then."""
    question_id: UUID
    irt_model: Literal["2pl","grm","3pl"]
    a: float                      # discrimination — required by §6.3's own likelihood
    b: float | list[float]        # difficulty, or GRM category thresholds
    c: float | None = None        # 3PL guessing, MCQ only
    se_b: float | None = None     # parameter uncertainty; attenuates the update
    params_source: Literal["prior","elo","mml"]
    bank_version: str

class Observation(BaseModel):
    """The ONLY way mastery changes. No evidence → no write."""
    id: UUID                      # uuid5 content hash — see §6.2, FR-4.25
    candidate_id: UUID
    concept_id: str
    concept_weight: float = 1.0   # secondary concepts count less (mirrors M5 ConceptWeight)
    session_id: UUID
    turn_id: UUID | None
    evidence: list[EvidenceRef] = Field(min_length=1)   # FR-4.5 lives HERE, not in NOT NULL
    kind: Literal["answer_scored","code_submitted","mcq_answered","probe_depth",
                  "hint_used","self_reported","gd_contribution","drill_completed",
                  "propagated"]                          # ← §6.4 writes real rows
    # --- the response, in the form the likelihood actually needs ---
    response_model: Literal["2pl","grm","3pl","none"]
    raw_category: int | None      # 0..K, the UN-normalised rubric level (GRM)
    n_categories: int | None
    outcome: float                # normalised 0–1 — DISPLAY and BKT only, never the likelihood
    item: ItemParams | None       # None → not θ-eligible; see §6.3
    theta_eligible: bool          # derived at write time, stored, shown in the drawer
    source_dimension_key: str | None   # which M13 rubric dimension became this (§6.3)
    weight: float = 1.0           # ∈ (0,1]; likelihood tempering, never > 1
    # --- propagation provenance (kind == "propagated") ---
    source_concept_id: str | None = None
    hops: int = 0
    counts_toward_n_direct: bool = True
    # --- posterior after, so trajectories replay without re-running the estimator ---
    theta_after: float
    se_after: float
    # --- versions, consent, lifecycle ---
    versions: VersionStamp        # M19's type: rubric, prompt, model, calibration, bank, code_sha
    estimator_version: str
    ontology_version: str
    consent_id: UUID              # FR-4.20
    observed_at: datetime
    retracted_at: datetime | None = None      # FR-4.26; recompute, never compensate
    retraction_reason: str | None = None

class Mastery(BaseModel):
    candidate_id: UUID
    concept_id: str
    theta: float                  # IRT ability, logit scale, clamped [-4, 4]
    se: float                     # standard error — the honesty channel. Prior 1.5.
    mastery_p: float | None       # 0–1. THE consumer scalar. None iff not displayable.
                                  # mastery_p = 1 / (1 + exp(-theta))
    bkt_p_known: float | None     # display-only companion, computed on read (§6.3)
    n_direct: int                 # observations ABOUT this concept
    n_propagated: int             # inherited from neighbours — never displayable (FR-4.24)
    last_evidence_at: datetime | None
    break_depth_mean: float | None    # from probe ladders
    version: int                  # optimistic lock (§6.2)
    ontology_version: str
    state: Literal["not_tested","emerging","weak","adequate","strong"]
    # state is DERIVED — see the one function below, which is the platform's only definition

    @property
    def displayable(self) -> bool:
        return self.state not in ("not_tested", "emerging")

class MemoryFact(BaseModel):
    id: UUID
    candidate_id: UUID
    tier: Literal["episodic","semantic","working"]
    kind: Literal["break_point","story","failure_signature",
                  "comm_fingerprint","preference"]        # closed set — the five §6.6 names
    content: dict
    display_sentence: str         # the shipped string; written at distillation, never at read
    quote: str | None             # verbatim substring of a cited turn — screen 2 (§6.6b)
    embedding: list[float] | None
    embedding_model: str          # master plan §20.3 — so we can re-embed on upgrade
    embedding_version: str
    importance: float             # 0–1, assigned at write time
    concept_ids: list[str]
    source_evidence: list[EvidenceRef] = Field(min_length=1)
    produced_by_model: str
    produced_by_prompt: str
    purpose: Literal["practice","institutional_reporting","research"]   # FR-4.18c
    created_at: datetime
    superseded_by: UUID | None    # facts are superseded, never deleted
    suppressed_until: datetime | None = None    # student deleted it — §15.7
    delete_count: int = 0                       # twice = never re-derive

class FailureSignature(BaseModel):
    """Behavioural descriptions of what was observed. NOT traits, NOT dispositions.
    M12 FR-12.15 forbids inferring personality anywhere on the platform and greps the
    whole codebase for it; these names are written to survive that grep on merit."""
    candidate_id: UUID
    kind: Literal["abandoned_before_using_hint","answer_length_exceeded_budget",
                  "paused_over_20s_on_underspecified_prompt",
                  "stated_confidence_exceeded_correctness",
                  "correct_under_rubric_below_threshold_on_clarity",
                  "score_improved_after_hint","score_fell_under_time_pressure",
                  "asked_no_clarifying_question_on_ambiguous_prompt"]
    strength: float
    observed_episodes: int
    evidence: list[EvidenceRef] = Field(min_length=1)   # Rule 3 applies here too
    supporting_sessions: list[UUID]
    updated_at: datetime
    # NEVER rendered to a placement cell or any third party — AC-4.10 [GATE]
```

### 5.3 The five states — one definition, published

`state` has been the source of three different threshold sets across three specs. There is now exactly one, and every consumer reads it:

```python
STATE_THRESHOLDS_VERSION = "1.0"          # goes in VersionStamp

def state(m: Mastery, now: datetime) -> str:
    if m.n_direct == 0:                                  return "not_tested"
    if m.n_direct < 2 or se_effective(m, now) >= 0.90:   return "emerging"
    if m.mastery_p < 0.45:                               return "weak"
    if m.mastery_p < 0.70:                               return "adequate"
    return "strong"
```

| state | rule | student-facing string | bar treatment |
|---|---|---|---|
| `not_tested` | `n_direct == 0` | "not tested yet" | dashed outline, no fill |
| `emerging` | `n_direct < 2` or `se_effective ≥ 0.90` | "just started" | 20% hatched fill — a third **texture**, not a third colour |
| `weak` | `mastery_p < 0.45` | "needs work" | amber |
| `adequate` | `0.45 ≤ mastery_p < 0.70` | "solid" | green |
| `strong` | `mastery_p ≥ 0.70` | "strong" | green, full |

Two things fall out. `emerging` **is** the not-yet-displayable state, so `displayable` stops being a second competing rule. And M15's `gap_severity` becomes `1.0 - mastery_p` — correct by construction, where `1.0 - theta` on a logit scale never was.

> **Coordinated change.** M15 ships today consuming `Mapping[str, float]` and its fixtures pass bare floats. Moving to the object above is a two-repo PR pair; M15's 216 tests move in the same pair or neither does.

### 5.4 Storage — one schema, two stores

**There is no raw DDL in this spec.** The platform's first promise (`README.md`) is that a module clones, installs and runs on its own; `dependencies.txt` says SQLite by default, Postgres via `DATABASE_URL`. `TIMESTAMPTZ`, `JSONB`, `TEXT[]`, `VECTOR(1024)`, `USING hnsw` and `DEFAULT now()` are Postgres-only — and the ones SQLite *accepts* are worse than the ones it rejects, because `VECTOR(1024)` and `TEXT[]` silently become text columns.

So: SQLModel classes in M15's shipped idiom (`models.py` + `schema.py`'s additive repair on startup), and one explicit table of what each store provides.

| Concern | SQLite (default, zero setup) | Postgres (`DATABASE_URL` set) |
|---|---|---|
| Vectors | `float32` bytes in a BLOB, brute-force cosine in Python | `pgvector`, same query shape |
| Working tier | table + `stale` flag | table + `stale` flag (Redis optional) |
| Graph walk | `WITH RECURSIVE` (supported) | `WITH RECURSIVE` |
| JSON columns | `JSON` (SQLModel maps it) | `JSONB` |
| Timestamps | naive UTC via one helper | `TIMESTAMPTZ` |
| Concurrency | single writer; optimistic lock still required | row-level; optimistic lock required |

Brute-force cosine is not a compromise: **every memory search is candidate-scoped over a few hundred rows**, where it is sub-millisecond. HNSW is a Phase-3 optimisation at the earliest and it is the single thing that would have broken clone-and-run.

```python
# backend_M04_Skill_Graph/models.py — tables owned by this module
m04_concepts               # Concept, PK (id, ontology_version)
m04_concept_edges          # ConceptEdge, indexed (dst, kind), (src, kind)
m04_concept_aliases        # (alias_normalised, concept_id, ontology_version) — FR-4.21
m04_concept_mastery        # Mastery, PK (candidate_id, concept_id), `version` for the CAS
m04_observations           # Observation, PK id (uuid5), idx (candidate_id, concept_id, observed_at DESC)
                           #                             idx (item_id) — the response matrix for Paper 2
m04_candidate_facts        # MemoryFact, idx (candidate_id, tier, created_at DESC) where superseded_by is null
m04_profile_summary        # working tier, `stale` flag — NOT a materialised view (§6.6)
m04_session_profile_snapshot   # session-pinned context, FR-4.23
m04_retest_queue           # §6.9
m04_outbox                 # mastery.updated events, drained after commit (§6.2)
```

**Every table that holds a belief carries `ontology_version`.** Without it EC-4.4 (concept removed) and EC-4.5 (concept split) have nothing to migrate on.

**Timestamps.** SQLite returns naive datetimes, so `(now - last_evidence_at).days` in §6.5 raises `TypeError` on the first decay run. One UTC helper, used everywhere, tested.

**Retention, per table** (master plan §46.3): `m04_observations`, `m04_concept_mastery`, `tier='episodic'` facts → enrolment + 1 year. **`tier='semantic'` facts → enrolment + 90 days**, hard-deleted at graduation. Distilled behavioural inference is more sensitive than the raw turn it came from and should outlive it by *less*, not more. Working tier is a TTL and needs no policy.

---

## 6. The pipeline in minute detail

### 6.1 The ontology (build this first, by hand, with faculty)

**120 concepts for Phase 1** (450 is the year-end target). 120 covering DSA + CS core + communication is what M5 can realistically seed 3+ calibrated items per concept for by Phase-1 exit — at 180 the granularity check below *fails by construction*, and a thin correct ontology beats a large wrong one. Growth is a YAML append, not a migration.

Sourcing, in order:
1. University syllabi for DSA, OS, DBMS, CN, OOP, ML (we have these — it's our own institution).
2. Company topic tags from LeetCode/GfG company lists (topics only, no content).
3. The aptitude section structure from AMCAT/CoCubes patterns.
4. Communication constructs from the M12/M17 feature list.

Format — `packages/knowledge/ontology/concepts.yaml`, versioned in git:
```yaml
- id: concept:dynamic_programming
  name: Dynamic Programming
  domain: dsa
  level: advanced
  aliases: [DP, memoization, tabulation, "dynamic programing"]   # misspellings included
  foundational_floor: false     # true ⇒ never surfaced as a bottleneck
  typical_question_time_s: 900
  prerequisites:
    - {id: concept:recursion, strength: 0.9}
    - {id: concept:arrays, strength: 0.4}
  specialises: [concept:knapsack, concept:lis, concept:edit_distance]
```

**Aliases are a platform contract, not a nicety (FR-4.21).** M15 keys its corpus on free-text topic labels students typed ("DP", "dp problems", "Dynamic Programming"); M1 maps resume surface forms; M2 maps JD requirements. All three need `POST /v1/concepts/resolve`, and none of them can invent it. Ship the alias table on day 1 with the ontology, normalised (casefold, strip punctuation, collapse whitespace) and collision-checked.

**`ontology_lint` — run in CI, not by eye.** Acyclicity on `prerequisite_of`; orphan concepts (no edges, no questions); alias collisions across concepts; edges crossing `ontology_version`; and after M5 is seeded, the **granularity check** — any concept with > 40 or < 3 bank items is mis-sized. Trap 5 says the ontology is load-bearing; a linter is how that stays true after week 3.

**Review gate:** a faculty member walks the prerequisite edges once. **Book this in week 1** — AC-4.9 gates Phase-1 exit and it is a dependency on someone else's calendar, not a task you can schedule on day 14. Give the reviewer the Streamlit ontology browser (§6.10), not a YAML file: edge-by-edge accept/reject with the affected concepts rendered is the difference between a two-hour review and one that never happens.

### 6.2 The write path (the only one)

**Idempotency first (FR-4.25).** §10 queues failed writes to `observations_pending` and replays them. Without a stable id, a replay counts the same answer twice and silently corrupts mastery — the fallback path becomes a corruption path. The id is a content hash, and the namespace constant lives **in this spec** so every caller derives the same id:

```python
OBS_NAMESPACE = uuid.UUID("6f1c1d3e-0000-4000-8000-000000000004")

def observation_id(o) -> uuid.UUID:
    return uuid.uuid5(OBS_NAMESPACE,
        f"{o.turn_id or o.session_id}|{o.concept_id}|{o.kind}|{o.rubric_version}")
```

```python
def record(obs: Observation) -> RecordResult:
    if obs.concept_id not in ontology:            # validated in memory — an FK SQLite
        raise UnknownConcept(obs.concept_id)      # does not enforce is not a check
    if not consent_active(obs.candidate_id, obs.consent_id):
        raise NoConsent(obs.candidate_id)          # FR-4.20
    for ref in obs.evidence:
        assert_evidence_resolves(ref)              # hard fail; no silent drop

    with tx():
        inserted = insert_ignore_conflict(obs)     # uuid5 PK ⇒ replay is a no-op
        if not inserted:
            return RecordResult(applied=False, reason="duplicate")

        for attempt in range(3):                   # optimistic lock, no lost updates
            m = get_or_create_mastery(obs.candidate_id, obs.concept_id)
            new = update_irt(m, obs)               # §6.3 — no-op when not theta_eligible
            if compare_and_swap(new, expected_version=m.version):
                break
        else:
            raise ContendedMastery(...)            # never silently drop

        propagate(obs, damping=0.3, max_hops=2)    # §6.4 — writes derived observations
        enqueue_outbox("mastery.updated", ...)     # a row, not a broadcast

    mark_profile_stale(obs.candidate_id)           # AFTER commit — see below
    drain_outbox()                                 # AFTER commit
    return RecordResult(applied=True, theta_after=new.theta, se_after=new.se)
```

Three things moved out of the transaction, and each was a real bug:

- **Cache invalidation after commit**, or a rolled-back transaction leaves a cache that was invalidated for a write that never happened.
- **Events after commit, via an outbox table.** `emit_event()` inside the transaction is a dual write: the event fires for work that may roll back. A table is enough here — Redis + Arq is deferred until M6 needs a queue for its own reasons (§20.2 of the master plan agrees: defer until measured pain).
- **The profile summary goes stale for the NEXT session, not this one.** See FR-4.23 and §6.6 — in-session mastery movement already reaches the interviewer through the correct channel (M5's selector reads live mastery), and it must not arrive as mutated prose mid-session.

`propagate()` walks affected concept ids **in sorted order**. Unsorted, two concurrent sessions touching overlapping neighbourhoods deadlock on Postgres.

Every other module calls `record`. There is no `UPDATE m04_concept_mastery SET theta = ...` anywhere else — enforced two ways, because a CI grep alone cannot see into the eighteen repos that write here: a **local grep** for mastery UPDATEs outside `store.py`, and a **runtime guard** — the ORM session for mastery tables is only obtainable inside `record()`.

**Batch endpoint.** M13 emits several observations per turn. `POST /observations` takes a **list**, in one transaction, and that is what the 60 ms budget in §11 refers to — per call, not per observation.

**Retraction (FR-4.26).** `retracted_at` is set; mastery for that `(candidate, concept)` is **recomputed from surviving observations**, never compensated by an inverse update. M5 EC-5.9 (student flags an item), M13 re-scores, EC-4.7 disputes and EC-4.10 account merges all route here.

### 6.3 Estimators

**Who owns the ability estimate.** M04 owns the *durable posterior* per `(candidate, concept)`: the only thing persisted, the only thing displayed, changed only through `record()`. M5 owns *item parameters* (`a`, `b`, `c`) and a *session-scoped provisional θ* held in `SessionState` — seeded from M04 at session bootstrap, updated in memory from the provisional score for item selection only, **never persisted, never displayed, discarded at session end**. M13's evaluation is async and will not have returned before the next question must be chosen, which is exactly why the provisional estimate exists and exactly why it must not be written down. At session end M04 recomputes the posterior from the observations of record; if it disagrees with the provisional estimate the posterior wins silently, and a divergence > 0.5 logits is logged as a calibration signal.

**IRT is the source of truth.** θ and SE are the posterior. Everything displayed derives from them.

```
prior:  θ ~ N(θ_prior, σ_prior²)     θ_prior from cohort/branch when n=0, σ_prior = 1.5
2PL  (binary: coding pass/fail, numeric)
        P(correct|θ) = 1/(1+exp(-a(θ-b)))
GRM  (Samejima; rubric-scored ordinal 0..K — THE dominant case)
        P(X≥k|θ) = 1/(1+exp(-a(θ-b_k)))      P(X=k) = P(X≥k) - P(X≥k+1)
3PL  (MCQ aptitude, guessing)
        P(correct|θ) = c + (1-c)/(1+exp(-a(θ-b)))
posterior on a 61-point fixed grid over θ ∈ [-4.5, 4.5], trapezoidal
θ̂ = E[θ|obs…]   SE = sd[θ|obs…]   θ clamped to [-4, 4] on write
```

> The previous draft said "41-point Gauss–Hermite quadrature on θ ∈ [-4,4]", which conflates two rules — Gauss–Hermite integrates against `exp(-x²)` over the whole line; a fixed grid on a bounded interval is Gauss–Legendre or trapezoidal. The interval was also narrow for σ_prior = 1.5.

**GRM is not optional and not deferred.** Most items are rubric-scored; M5 §3.1 Trap 2 names the failure exactly ("collapsing to right/wrong throws away most of the information and biases `b`"). It is ~20 lines on top of the 2PL, it is written on the same day, and it is the difference between a defensible Paper 2 and a reviewer's first objection. This is why `Observation` carries `raw_category` and `n_categories` and why `outcome` is explicitly **not** the likelihood input.

**When `item is None`** — free-form probes, self-reports, drills, and every M5 *grounded* item (M5 §3.2.5: "never enter the IRT bank… not for ability estimation") — the observation updates `n_direct`, `last_evidence_at` and the episodic tier, and **does not touch θ or SE**. `theta_eligible` is stored so the evidence drawer can say which answers moved the number and which did not. Where `se_b` is known, attenuate rather than pretend: `a_eff = a / sqrt(1 + a²·se_b²)`.

**Local dependence.** Five questions on one concept in one session are not conditionally independent; treating them as independent understates SE by roughly `√(1 + ρ(k−1))` — at ρ ≈ 0.2, k = 5 that is ~1.35×. It makes M5 stop early believing it knows more than it does, and it is the first thing a Paper 2 reviewer asks about. Minimum viable rule: **cap the effective count per concept per session at 3 for SE purposes**, and report the cap.

**Weighting.** `weight ∈ (0, 1]` — likelihood tempering, `logL_eff = w · logL`. Never above 1: a weight > 1 fabricates precision that no answer supplied. Hint-assisted correct answers scale `raw_category` by the published hint penalty and take `weight × 0.7`; the penalty is applied **once**, in M13, and M04 does not re-apply it.

**BKT — display-only companion, fixed priors.**

```
P(L0)=0.15   P(G)=0.20   P(S)=0.10
P(T)=0.0 WITHIN a session; between sessions P(T) = 0.15·(1 - exp(-days_gap/60)),
applied once, on the first observation of a new session.
correct:  P(L|obs) = P(L)(1-P(S)) / [P(L)(1-P(S)) + (1-P(L))P(G)]
wrong:    P(L|obs) = P(L)P(S)     / [P(L)P(S)     + (1-P(L))(1-P(G))]
then:     P(L)     = P(L|obs) + (1-P(L|obs))·P(T)
```

> **Why `P(T)=0` within a session.** `P(T)` models learning *between practice opportunities*, and nobody teaches you anything between interview question 3 and question 4. At the previously specified `P(T)=0.20` the transit dominates the evidence: a student answering **everything wrong** goes 0.15 → 0.2173 → 0.2268 → … → a hard floor of **0.2286**. A wrong answer *raised* mastery. Verified by running these exact equations with these exact priors.

Two further corrections: parameters are a **single global set**, not fitted per concept. Four free parameters × 120 concepts by EM needs thousands of sequences *per concept* and is not identifiable at any volume this project reaches — a pilot of 50–300 students is three orders of magnitude short. And `bkt_p_known` is **computed on read, never persisted as a competing belief**: decay and propagation move θ only, so a stored BKT value drifts away from the posterior with no rule saying which the UI believes. One source of truth, one arbitration problem removed.

**DKT / SAKT — Phase 4, external-validity design.** The comparison of BKT+IRT against attention-based knowledge tracing runs **primarily on public KT benchmarks**: ASSISTments 2009–10 skill-builder (corrected release) plus EdNet-KT1 subsampled for robustness, using an existing implementation (`pyKT` / `EduKTM`). Our own cohort is reported as a **descriptive replication with bootstrap CIs and an explicit power statement**, never as an adoption decision.

> The previous gate — "once ≥ 20k interactions exist" — is arithmetically unreachable: the project's own year-end target is ~8,000 responses and the Phase-3 pilot gate is 60 students. The experiment was guaranteed inconclusive before it was run. Deciding this **now** matters because it changes what must be logged from day 1, which is why `item_id` and `theta_after` are in the §5 contract rather than added later.

### 6.4 Prerequisite propagation

```python
def propagate(obs, damping=0.3, max_hops=2):
    if obs.outcome >= 0.7:
        # SUCCESS: weakly raise prerequisites' θ (you can't do DP without recursion)
        for prereq, strength, hop in walk_up(obs.concept_id, max_hops):   # sorted ids
            delta = damping**hop * strength * 0.15 * (obs.outcome - 0.5)
            emit_derived(obs, prereq, hop, strength,
                         d_theta=+min(delta, 0.20),
                         se_factor=1.02)      # a claim of evidence costs a little certainty
    else:
        # FAILURE: do NOT lower descendants' θ. Only WIDEN their SE.
        for desc, strength, hop in walk_down(obs.concept_id, max_hops):
            emit_derived(obs, desc, hop, strength,
                         d_theta=0.0,
                         se_factor=1 + damping**hop * strength * 0.25)
```

**The asymmetry is deliberate and it is the most important rule in this module.** Evidence of competence is transferable; evidence of failure is not. Failing DP does not prove you can't do recursion — it proves we should *check*. Widening SE makes the CAT selector go and check, which is exactly right.

Three constraints make it honest:

**1. Propagation writes real observations.** `emit_derived` inserts an `Observation` with `kind="propagated"`, `evidence = obs.evidence` (the *source* observation's ref — genuinely the evidence, just indirect), `source_concept_id`, `hops`, `weight = damping**hop · strength`, `item = None`, `theta_eligible = False`, `counts_toward_n_direct = False`. Without this, propagation changes a mastery value with no observation behind it and **AC-4.1 fails on M04's own write path** — the drawer that enforces Rule 3 would have nothing to render.

It also buys a better sentence than the old design allowed:

> *"0.2 of this came from your dynamic-programming answers on Jun 12, not from a recursion question — worth checking recursion directly."*

**2. `n_direct` and `n_propagated` are separate, and only `n_direct` counts (FR-4.24).** Every state, display and bottleneck rule keys off `n_direct`. **A concept whose evidence is purely propagated renders as `not_tested`** — no sixth state, no Rule 3 hole. The propagated θ still exists and is still used, by the one consumer that legitimately benefits from a prior it need not justify to a student: M5's selector.

**3. Both moves are clamped.** `se = min(se · factor, SE_PRIOR)` — multiplicative widening is otherwise unbounded, and ten failed DP questions would widen recursion's SE past the prior SD, which is incoherent: you cannot know less than nothing. `cap_abs=0.20` caps a *single* update; the **lifetime** propagated contribution to any concept is capped at 0.35 logits, tracked in `theta_propagated_total`. And raising θ while holding SE fixed is a claim of certainty no answer supplied, which is why the success branch also widens slightly.

### 6.5 Decay

```
SIGMA_DRIFT = 0.45      # logits of true-ability drift per 90 days
SE_PRIOR    = 1.5

days = (utcnow() - last_evidence_at).days
var_eff      = min(se**2 + SIGMA_DRIFT**2 * (days / 90.0), SE_PRIOR**2)
se_effective = sqrt(var_eff)
theta unchanged, always
```

`se` is **persisted**; `se_effective` is **computed on read**, from this one function, everywhere. Consumers that must use `se_effective`: `state()`, `displayable`, the CAT seed, the re-test trigger. Consumers that must use stored `se`: the golden snapshot and any replay.

**Two thresholds, not one — they are doing different jobs:**

```
retest_candidate = (se_effective >= 0.55) or (days_since_evidence >= 120)
displayable      = state not in ("not_tested", "emerging")     # se_effective < 0.90
```

> **Why the previous formula could never fire.** `se_effective = se · (1 + 0.35·(1 − exp(−days/45)))` caps at 1.35×, so crossing 0.9 required a stored `se ≥ 0.667`. But M5 stops a domain at `SE < 0.30`, so every concept the CAT actually finished sits at `se ≤ 0.30` — and `0.30 × 1.35 = 0.405`, at infinity. A concept measured *well* was mathematically incapable of ever becoming a re-test candidate, while a barely-measured one at `se = 0.85` crossed in 30 days. Exactly backwards, and it silently deleted EC-4.8, Moment 5 and the M16 hand-off while the §12 property test ("decay never lowers θ") passed throughout. The additive-drift form saturates at the prior instead: `se = 0.30` → 0.541 at 90 days, 0.708 at 183, 0.955 at 365. You can never become less certain than before you had any data.
>
> Master plan §30.2 specifies a *power-law* forgetting curve. This supersedes it; §30.2 must be amended or the thesis carries two forgetting models.

A concept crossing `retest_candidate` is enqueued in `m04_retest_queue` (§6.9, `reason='decay'`) — that is the M16 hand-off, and it is a table rather than a phrase.

**Hysteresis: a displayed concept never silently disappears.** Decay pushing `se_effective` past 0.90 would otherwise remove a bar from the map, and a vanishing bar is worse than a lowered one — it breaks the same promise §3.2's rule 3 makes. Once displayed, a concept stays displayed, greys down, and says *"not checked since March"*. The student sees *"haven't tested this since March"*, never a lowered bar and never an absence.

### 6.6 Memory tiers and retrieval

**Episodic** — every turn, evaluation, delivery vector, GD contribution, drill. Immutable rows. This is the substrate everything else can be rebuilt from.

**Semantic** — distilled facts, written by a nightly job plus inline after each session:
- break points per concept,
- story bank (STAR stories extracted from HR answers, tagged by theme — reusable across sessions, and a genuinely loved feature),
- failure signatures,
- communication fingerprint (baseline filler rate, pace, TTFT),
- preferences ("prefers written questions", "asked us to slow down").

**Working** — `m04_profile_summary` (mastery top/bottom 10, last 3 session summaries, open plan items, 5 highest-importance facts). This is what the interviewer agent gets injected at session start — it must fit in ~1,200 tokens.

It is **a table with a `stale` flag**, not a materialised view. Postgres materialised views cannot be refreshed incrementally, so "refreshed on write" is a non-starter at any write rate; Redis is an optional accelerator, never a requirement, because the module must run with zero setup. §10's "Redis down" row therefore describes an optimisation being absent, not a fallback.

**The injected context is pinned per session (FR-4.23).** `m04_session_profile_snapshot(session_id, summary_text, summary_version, built_at)` is written once when a session opens and served byte-identical for that session's life; `record()` marks the *next* session's summary stale, never the current one's. Two reasons, and the second is the expensive one: mutating prose mid-interview means the interviewer's own context changes underneath it between turns, and it invalidates M6's prompt cache on every observation — which is a real bill, not a purity argument. In-session mastery movement already reaches the interviewer through the correct channel: M5's selector reads live mastery (§2.1 moment 2). It does not need to arrive as rewritten prose.

The builder is deterministic — fixed block order, fixed sort keys, no timestamps in rendered text, per-block token caps (mastery 400 / recent sessions 300 / plan items 200 / top facts 300). AC-4.13 tests exactly that.

**Hybrid retrieval:**
```
score = 0.45·cos(q, e) + 0.20·exp(-Δdays/21) + 0.20·importance + 0.15·concept_overlap
```
Search is **candidate-scoped over a few hundred rows**, so brute-force cosine in Python is sub-millisecond and identical on both stores. No HNSW, no dedicated vector store — revisit in Phase 3 if a real profile says so.

Every vector records `embedding_model` and `embedding_version` (master plan §20.3). `VECTOR(1024)` in the previous draft silently chose a model nobody selected; recording it is what makes re-embedding on upgrade a job rather than a rebuild.

Weights live in config and are swept on a **dev split of 100 queries**; AC-4.8 is then reported on a **held-out test split of 50, touched once**. Sweeping and scoring on the same 50 was training on the test set. Two annotators label, agreement is reported, and the **ablation of each term is a figure in the memory paper** — against named baselines (vector-only, BM25, recency-only, no-memory control, and **Mem0**), because "why not just use Mem0 or Zep?" is the first question an examiner asks and the spec should answer it with a number.

`importance` at write time: break point discovered `0.9` · scored below 0.3 on a must-have `0.85` · a story the student told `0.7` · routine correct answer `0.2` · session metadata `0.1`.

### 6.6b Distillation — the four screens between a model and a stored fact

The nightly distiller is the **only** LLM in this module, and it writes prose about a student that §8 shows straight back to them. M15 already solved this exact problem — a generated block that must not contain an ungrounded number or proper noun — and its pattern ports directly. Nothing here relies on model capability; the screens are deterministic and the cheap tier is safe behind them.

1. **Constrained schema** (from `talking_points.py::build_schema`) — a per-call JSON schema whose `evidence_turn_ids` is an `enum` of exactly this candidate's turn ids in the window, and `concept_ids` an `enum` of the concepts in that window. A hallucinated id, or a turn belonging to another student, becomes *structurally impossible* rather than merely caught. `MemoryFact.kind` is a closed `Literal` for the same reason.
2. **Quote screen** (from `ingest/validate.py`) — every fact carries `quote`, which must be a verbatim substring (whitespace-collapsed only) of a turn it cites. Require the citation, then check it yourself.
3. **Ungrounded-term screen** (from `talking_points.py::ungrounded_terms`) — haystack = the cited turns' text + concept names + the student's own name. Any digit or mid-sentence proper noun in `display_sentence` that the haystack does not support drops the fact whole, with the offending terms recorded as the rejection reason.
4. **Rendering screen** — `display_sentence` is written **at distillation time and stored**, never generated at read. §11 forbids an LLM on the read path, and Moment 1's sentence is a read.

Rejections are recorded, not silently dropped: a nightly batch that quietly produces nothing is a gap in tomorrow's sessions that nobody notices. **Trigger on session-completed, not on the calendar** (see §11 for why that is also the cost control).

### 6.7 Versioning and re-scoring

**Five versions can invalidate a θ, not one.** Every observation carries M19's `VersionStamp` — `rubric_version`, `prompt_version`, `model_id`, `calibration_version`, `item_bank_version`, `code_sha` — plus `estimator_version`, `ontology_version` and `STATE_THRESHOLDS_VERSION`. Stamping only the rubric would leave "you improved 30%" quietly false the first time the estimator or the item bank moved, which is Trap 4 with a different subject.

Longitudinal queries filter on `rubric_version ∈ compatible_set(v)`. A rubric bump inserts a `rescore_job` over affected turns; both old and new scores are retained; the UI shows the new one with a small "re-scored under rubric v2.1" note if a student's history spans the boundary. Silence here would be a lie by omission.

An `estimator_version` bump does **not** re-score — it **replays**: observations are immutable, so mastery is recomputed from them, and the golden snapshot (§12) is expected to move. Any move must be deliberate and reviewed.

### 6.8 Bottleneck query (powers the map's one call-to-action)
```sql
-- earliest unmastered prerequisite blocking the most targets.
-- WITH RECURSIVE works on SQLite too, so this stays inside clone-and-run.
WITH RECURSIVE target AS (              -- weak OR untested, matching what §2.3 renders
  SELECT c.id FROM m04_concepts c
  LEFT JOIN m04_concept_mastery m
         ON m.concept_id = c.id AND m.candidate_id = :cid
  WHERE c.ontology_version = :ov
    AND (m.concept_id IS NULL OR (m.n_direct >= 2 AND m.theta < -0.3))
), up(target_id, blocker, hop, path_strength) AS (
  SELECT t.id, e.src, 1, e.strength
    FROM target t JOIN m04_concept_edges e ON e.dst = t.id
   WHERE e.kind = 'prerequisite_of'
  UNION ALL
  SELECT u.target_id, e.src, u.hop + 1, u.path_strength * e.strength
    FROM up u JOIN m04_concept_edges e ON e.dst = u.blocker
   WHERE e.kind = 'prerequisite_of' AND u.hop < 3
)
SELECT u.blocker,
       count(DISTINCT u.target_id) AS blocks,
       sum(u.path_strength)        AS weighted_blocks,
       m.theta, m.se
  FROM up u
  JOIN m04_concepts c ON c.id = u.blocker AND c.foundational_floor = false
  LEFT JOIN m04_concept_mastery m
         ON m.concept_id = u.blocker AND m.candidate_id = :cid
 GROUP BY u.blocker, m.theta, m.se
HAVING m.theta IS NULL OR m.theta < 0.2
 ORDER BY weighted_blocks DESC, m.theta ASC NULLS FIRST
 LIMIT 3;
```

Four semantics that are the *reason* it is recursive, and each must be in prose because the SQL alone does not say them:

- **Stop walking a path once the blocker is itself mastered** (`θ ≥ 0.2`), so you surface the earliest *unmastered* ancestor rather than always surfacing `concept:arrays`.
- **Rank by strength-decayed `weighted_blocks`**, not raw count, so a hop-2 blocker behind a 0.4 edge does not outrank a hop-1 blocker behind a 0.9 one.
- **`foundational_floor` concepts are excluded.** M16 §6.4a is right that "work on variables" is insulting advice; the floor belongs here, in the query every consumer shares, not as a patch in one downstream module. (M16 currently cites "M4 §30.8", which exists in neither document — fix the reference to this section.)
- **`target` includes untested concepts**, because §2.3's own mock counts `Backtracking — not tested` among the four that recursion blocks. Excluding them made the number in the SQL differ from the number on screen, on the module's only call to action.

**If the top blocker has `blocks < 2`, report no bottleneck** rather than a weak one. A unit test asserts the number this query returns equals the number `BottleneckCard` renders.

### 6.9 The re-test queue

§2.4 promises dispute → re-test → notification. That needs an owner, and M04 is the module every producer already writes to, so one table serves five of them. M16 (Phase 4) reads it; it does not own it, or the promise cannot be kept until Phase 4.

```python
m04_retest_queue:
  id, candidate_id, concept_id
  reason: Literal["dispute","inconsistent","decay","propagated_unverified","counselor"]
  requested_by: str            # 'M04' | 'M13' | 'M16'
  source_ref: dict             # dispute id / evaluation id
  priority: float = 1.0
  bypass_freshness: bool = True    # overrides M5's 90-day no-repeat filter
  created_at, expires_at           # don't chase a re-test forever
  resolved_at, resolved_by_observation_id
```

`bypass_freshness` is not a detail: M5 never repeats an item within 90 days, so **without it a disputed value can never be re-tested** and the promise in §2.4 is empty. M5 reads this queue as a selection input.

The student-facing state exists too, which is what makes disputing feel like being heard rather than shouting: *"We've queued a recursion question for your next session."*

### 6.10 The ops app (Streamlit, `:8304`)

Three internal surfaces that would each cost a day as React screens and earn nothing from being one:

- **Ontology browser** — edge-by-edge accept/reject with affected concepts rendered. This is what makes AC-4.9's faculty sign-off a two-hour review instead of a review that never happens.
- **Simulation dashboard** — θ recovery under each mis-specification cell (§12), read as a grid.
- **Retrieval eval workbench** — query, ranked facts, labels, per-term ablation.

Internal only, never student-facing, not on the module's critical path for a student. 1.5 days total.

---

## 7. API surface

| Endpoint | Access |
|---|---|
| `GET /health` → `{"status","ontology_version"}` | public |
| `GET /v1/deps` | public |
| `GET /v1/concepts` · `GET /v1/concepts/{id}` — ontology, cached | public |
| `POST /v1/concepts/resolve` `{"labels":[…]}` → `{label: concept_id \| null}` | public |
| `GET /v1/skill-graph/theta?candidate=&concepts=` | service |
| `GET /v1/candidates/{id}/mastery?domain=&state=` | self |
| `GET /v1/candidates/{id}/mastery/{concept_id}/evidence` ← "why is this?" | self |
| `GET /v1/candidates/{id}/bottlenecks` | self |
| `GET /v1/candidates/{id}/profile-summary?session_id=` ← pinned, for agents | service |
| `POST /v1/candidates/{id}/observations` — **list**, one transaction | service |
| `GET /v1/candidates/{id}/memory/search?q=&k=&tiers=` | self |
| `GET /v1/candidates/{id}/facts?kind=story` | self |
| `DELETE /v1/candidates/{id}/facts/{fact_id}` — supersede + suppress (§15.7) | self |
| `POST /v1/candidates/{id}/mastery/{concept_id}/dispute` `{reason}` | self |
| `GET /v1/candidates/{id}/retests` — queued re-tests and their state | self · service |
| `GET /v1/candidates/{id}/trajectory?concept=&from=&to=` | self |
| `GET /v1/candidates/{id}/export` — full export (FR-4.18a) | self |
| `DELETE /v1/candidates/{id}/memory` — hard delete (FR-4.18b) | self |
| `DELETE /v1/candidates/{id}/memory?purpose=research` — revocation (FR-4.18c) | self |

**`/health` and `/v1/deps` are not boilerplate** — `module.json` probes `health_path: "/health"` on every upstream, and M15 ships that probe today. Without them M04 reads as permanently down to every module that degrades gracefully around it.

**`GET /v1/skill-graph/theta` is the path M15 already calls.** Adopt it rather than inventing a parallel one, and return objects rather than bare floats:

```json
{ "per_topic": { "concept:recursion": {
      "theta": -1.2, "se": 0.7, "mastery_p": 0.23, "state": "weak",
      "n_direct": 4, "last_evidence_at": "2026-06-28T…" } },
  "unresolved": ["blockchain"],
  "ontology_version": "1.0" }
```

`unresolved` matters: M15 keys its corpus on free-text topics students typed, and a label M04 cannot resolve must come back as *unresolved*, never as `theta = 0.0`. A silent zero is a confident claim of ignorance, and it is Rule 2 violated at an API boundary.

**Auth.** Everything under `/v1/candidates/{id}/` is **self** only. `service` endpoints take a shared secret from `keys.txt` (M15's `keys.py` pattern), checked by one dependency, and that check is tested. `FailureSignature` is reachable from **no** endpoint any third party can call — see AC-4.10.

**`observations_pending`** (§10's fallback) lives in **M04's own database**. Anywhere else and the fallback fails together with the thing it was meant to survive.

---

## 8. UI specification

**Components:** `MasteryMap` (domain-tabbed, prerequisite-indented, measured-first) · `MasteryBar` (five states, §5.3) · `EvidenceDrawer` (tap a bar → the sessions and answers behind it) · `BottleneckCard` · `MemoryTimeline` ("what I remember about you" — see below) · `DisputeDialog` *(Phase 2)* · `TrajectoryChart` *(Phase 2 — M19 owns charts; M04 ships `GET /trajectory`, the contract M19 needs)*

**`MasteryBar` belongs in `Platform_Core`.** "Not tested is not zero" is FR-4.9, AC-4.2 and platform Rule 2 — a promise five surfaces make. By M15's own test (provenance components are a platform contract; layout is not), the five-state rendering is a contract and a nineteenth copy is how it quietly stops being true in whichever repo falls behind while its own tests keep passing.

**Every state, per component:**

| Component | loading | empty | sparse | degraded | error |
|---|---|---|---|---|---|
| `MasteryMap` | skeleton rows, named ("reading your profile") | onboarding card, never empty bars (EC-4.1) | measured-first + collapsed untested count | domain tab shown, "not measured yet" | retry, last-known-good from cache |
| `EvidenceDrawer` | named spinner | — | — | "evidence expired" (EC-4.9) | — |
| `BottleneckCard` | — | hidden entirely when `blocks < 2` | — | hidden | hidden |
| `MemoryTimeline` | skeleton | "Nothing yet — we start remembering after your first session" | — | — | retry |

**Mobile.** The map is the only screen that needs work: bars go full-width with the label above, the domain tabs become a select, prerequisite indentation becomes a nested list (indentation below ~360px reads as damage), and the bottleneck card pins to the bottom as the single CTA. The evidence drawer is a bottom sheet, not a side drawer.

### The "what I remember about you" screen (build it, it's worth it)

A plain-language, scrollable list of the semantic facts, each deletable:

```
  What I remember about you                          [ Manage ]

  · You broke on database indexing twice — Jun 12 and Jun 28
  · You have a strong story about the hostel fest logistics
    (you use it for teamwork and for conflict)
  · You speak faster when you're unsure                       [ ✕ ]
  · You asked me to stop interrupting                          [ ✕ ]
  · Your recursion is the thing blocking DP and trees
```

Two reasons this exists: it makes the memory **legible and correctable** (a wrong fact is a bug the user can fix in one click), and it makes the "it knows me" feeling explicit rather than uncanny. It is also the module's responsible-AI artefact and its best demo — do not cut it.

**Three operations share the word "delete", and they are different. Say which one is happening:**

| Action | What happens | What the student is told |
|---|---|---|
| ✕ on a fact | superseded, excluded from retrieval, `suppressed_until = +30d`, `delete_count += 1` | *"I'll stop using this. If it shows up again in a future session I may notice it again — delete it twice and I'll stop for good."* |
| Revoke research consent | `WHERE purpose='research'`; practice data untouched | *"Your practice history stays. We'll stop using it in the study."* |
| Delete account | hard delete of facts and observations | *"Gone. Cohort statistics already computed aren't recalculated — we can't unmix them."* (EC-4.13) |

Deletion is real, and it is **not** a promise the nightly distiller can quietly break: it re-derives from the same evidence, so without the suppression window the fact returns tomorrow and the button is a lie. Two deletions of the same `kind` + `concept_ids` suppress it permanently.

**Accessibility:** every bar carries its state as text, never colour alone, and the three "measured" states differ by texture as well as hue. The map is a real `<table>`: prerequisite depth is a **column** (`Depends on: Recursion`), not `aria-level` — `aria-level` is a `treeitem`/`heading` attribute and does nothing on a table row, so the previous draft's ARIA would have shipped an accessibility claim that was inert. If a tree is preferred, use `role="tree"` and `aria-level` together, but pick one and test it with a screen reader before Phase-1 exit.

---

## 9. Edge cases

| ID | Case | Behaviour |
|---|---|---|
| EC-4.1 | Brand-new student, zero observations | All `not_tested`; cohort prior used internally; map shows an onboarding state, not empty bars |
| EC-4.2 | One observation on a concept | Stored; state = `emerging` ("just started"), hatched bar, no number. The SE gate binds before the count does: with σ_prior = 1.5 it takes 3–5 well-targeted items to reach se < 0.9, so `n ≥ 2` alone is not the rule |
| EC-4.3 | Contradictory observations (fails easy, passes hard) | Both recorded; SE widens; CAT prioritises a tiebreak item; if it persists, flag `inconsistent` for review |
| EC-4.4 | Concept removed from ontology in v2 | Mastery retained, hidden from UI, mapped to a successor if one exists |
| EC-4.5 | Concept split into two | Migration script duplicates mastery to both with widened SE |
| EC-4.6 | Rubric version bump | Batch re-score; UI notes the boundary on the trajectory chart |
| EC-4.7 | Student disputes a value | Flag, schedule a re-test item at that concept in the next session, notify when resolved |
| EC-4.8 | 6 months of inactivity | SE widened to the cap; welcome-back copy: "let's re-check a few things" |
| EC-4.9 | Evidence artifact deleted (retention) | Observation retained with a tombstoned evidence ref; the value stays, "why" says "evidence expired" |
| EC-4.10 | Two candidates merged (duplicate accounts) | Observations unioned; mastery recomputed from scratch, not averaged |
| EC-4.11 | Propagation would create a cycle | Impossible — DAG enforced at edge write; unit-tested |
| EC-4.12 | Mastery requested for all 120 concepts at once | Paginated by domain, served from `m04_profile_summary`; never an N+1 |
| EC-4.13 | Deletion request | Hard delete of facts and observations; aggregate cohort stats already computed are not recomputed, and we say so |
| EC-4.14 | Same observation replayed from `observations_pending` | uuid5 PK ⇒ insert is a no-op; `RecordResult(applied=False, reason="duplicate")`. Mastery moves once |
| EC-4.15 | Two observations for one `(candidate, concept)` land concurrently | Optimistic lock, 3 retries, then `ContendedMastery` — never a silent lost update |
| EC-4.16 | Concept has only propagated evidence | Renders `not_tested`; θ still used by M5's selector; drawer explains the inheritance |
| EC-4.17 | Observation arrives with no `item` (probe, drill, grounded item) | Recorded, counts toward `n_direct` and recency, **does not move θ or SE**; drawer marks it "not used for the estimate" |
| EC-4.18 | Free-text topic M04 cannot resolve (M15, M1, M2) | Returned in `unresolved`, never as `theta = 0.0`. Caller degrades that term to zero weight and says so |
| EC-4.19 | Decay pushes a displayed concept past the display threshold | Bar stays, greys, says "not checked since March", and is queued for re-test. It never disappears |
| EC-4.20 | Student deletes the same fact twice | Permanently suppressed; never re-derived; the second delete says so |
| EC-4.21 | Research consent revoked | Facts and observations with `purpose='research'` deleted within 30 days; practice history untouched; exports already released are listed, not recalled |
| EC-4.22 | Ontology version bumped mid-session | Session keeps the version it opened with; new version applies from the next session. Beliefs carry their version |
| EC-4.23 | Distillation produces a fact that fails a screen | Dropped whole, rejection recorded with its reason; a silently empty batch is a P1 alert, not a quiet night |

---

## 10. Failure modes & fallbacks

| Failure | Fallback | User impact |
|---|---|---|
| Redis absent (the default) | Read `m04_profile_summary` directly | ~300 ms session start, no visible change. Redis is an accelerator, never a requirement |
| Profile summary stale | Compute live with a 2 s budget, then write it back | Slower once |
| Mastery write fails mid-session | Observation queued to `observations_pending` (**in M04's own DB**), replayed by a worker; uuid5 makes replay safe | None — scores still appear in the report |
| Embedding service down | Retrieval degrades to recency + importance + concept overlap; the missing term is named in the response | Slightly worse memory recall, honestly labelled |
| Distillation model unavailable | No facts written that night; yesterday's stand; the run records why | Moment 1 falls to a lower rung of the ladder (§2.1) |
| Ontology load fails | Last-known-good cached copy | None |
| Propagation bug produces absurd values | Clamps: `θ ∈ [-4,4]`, `se ≤ SE_PRIOR`, lifetime propagated ≤ 0.35 logits; alert on any \|Δθ\| > 0.5 in one update | None |
| Contended mastery write (3 CAS retries lost) | `ContendedMastery` raised, observation queued for replay | None — never a silent lost update |
| M13 unavailable (Phase 1 — it may not exist yet) | Episodic writes come from a fixture/adapter seam; M04 runs and demos standalone | None — the module clones and runs alone, per platform convention |

---

## 11. Performance & cost budget

| Operation | p95 | Notes |
|---|---|---|
| `profile-summary` read (pinned) | 40 ms | Table read, or Redis if present |
| Mastery slice (20 concepts) | 90 ms | `m04_profile_summary` |
| Full map (120 concepts) | 250 ms | Paginated by domain |
| `record()` batch write + propagate | 60 ms | **Per call**, not per observation — M13 posts a list in one transaction |
| Hybrid semantic search (k=10) | 320 ms | Brute-force cosine over a candidate's facts (~300 rows); **excludes** the query-embedding round trip |
| Query embedding | 200 ms | External call — the one thing on a read path that leaves the process |
| Bottleneck query | 120 ms | Recursive CTE, ≤ 3 hops |
| Semantic distillation | — | Triggered on session-completed, ~₹0.5–1.3 per session (cheap tier behind the §6.6b screens) |

**No LLM on any *mastery* read path.** That is deliberate: the graph must be fast and deterministic, because everything else depends on it. The precise claim matters — `/memory/search` *does* embed the query, which is why FR-4.17's 400 ms budget is stated for search inclusive of that hop, and why §10 has a row for the embedder being down.

**Cost control, because "nightly" is a bill.** Calendar-triggered distillation at ₹0.8/active student/night is 300 students × 365 = **₹87,600/year**, most of it re-distilling students who did nothing that day. Two controls, both one line: **trigger on session-completed**, and **cap per student per month**. Same work, roughly ₹6–10k/year. Model-call cost is recorded per call (M15's `cost_inr` and its telemetry tables, promoted to `ai_core`), so the budget is a number you can check rather than one you assert.

---

## 12. Test plan

Everything runs **offline** — `llm.get_llm()` is injectable and a session fixture forces `NullLLM`, per the platform convention. A suite that needed a key is a suite nobody else can run.

**Unit** — BKT update against hand-computed values, **including the all-wrong sequence** (it must monotonically fall, which is what catches a bad `P(T)`) · IRT EAP against a reference implementation (`girth`) on 50 synthetic response patterns · GRM category probabilities sum to 1 and reduce to 2PL at K=2 · DAG acyclicity · decay never lowers θ (property test, 10k random inputs) · **decay's re-test trigger fires for a well-measured concept within 120 days** (the test the old formula would have failed) · propagation asymmetry · propagation never increments `n_direct` · `se` never exceeds `SE_PRIOR` · `not_tested` never serialises as 0 · `state()` boundaries at every threshold · uuid5 stability across processes.

**Integration** — simulate 200 students × 30 sessions with known true abilities; assert θ recovery and that the CAT (M5) converges. **Run the mis-specification grid, not just the matched case** — simulating from the model you then fit tests your quadrature, not your estimator:

| Cell | Simulated under | Scored under | Expected |
|---|---|---|---|
| matched | 2PL | 2PL | r ≥ 0.90 (sanity, not a result) |
| model mis-spec | GRM | 2PL | r ≥ 0.80, bias reported |
| local dependence | ρ = 0.2 within session | independent | SE understated ≤ 1.4×, reported |
| parameter drift | 20% drift in `b` | stale params | r ≥ 0.75 |
| non-normal ability | bimodal cohort | normal prior | r ≥ 0.80 |
| cold start | branch prior, true θ ⊥ branch | branch prior | **prior washes out by n = 3** |

That last row is the fairness check for §15.3 and it is a pass/fail gate, not a note.

**Golden** — a fixed observation sequence → a frozen expected mastery snapshot, in CI. Any estimator change that moves it must be deliberate; an `estimator_version` bump is how you declare that.

**Adversarial** — an observation with an unresolvable evidence ref (must raise) · one with a tombstoned ref (must record, and the drawer must say "evidence expired") · a batch of 1,000 observations on one concept (must not deadlock, must not lose an update — assert final θ equals the serial replay) · the same observation posted twice (mastery must move once) · a concept edge that would create a cycle (must reject) · a direct SQL update outside `record()` (local grep + runtime guard must both fail it) · a distillation response citing another student's turn id (must be structurally impossible, then also caught) · a `service` endpoint called without the shared secret (must 401).

**Manual QA** (6 min): complete two sessions as a test student → confirm session 2 opens by referencing session 1's break point → open the map → confirm untested concepts are collapsed, not rendered as empty bars → tap a bar → confirm the evidence drawer shows the real answer → tap a propagated concept → confirm it reads `not_tested` and the drawer explains the inheritance → dispute a value → confirm a `retest_queue` row exists and the UI says so → delete a fact → confirm the sentence names what changes.

---

## 13. Metrics & acceptance gates

| ID | Metric | Target |
|---|---|---|
| AC-4.1 **[GATE]** | Every mastery change traces to a resolvable evidence ref — including propagated ones | 100% |
| AC-4.2 **[GATE]** | `not_tested` never rendered as a numeric score, and never returned as `0.0` by any endpoint | UI + API test |
| AC-4.3 **[GATE]** | No mastery write outside `MemoryStore.record()` | local grep **+ runtime guard** |
| AC-4.4 | θ recovery under the mis-specification grid (§12) | matched r ≥ 0.90; every mis-spec cell ≥ its stated floor |
| AC-4.5 | Working-tier read p95 | ≤ 120 ms |
| AC-4.6 | Session 2 opens with a personalised reference | 100%; **rungs 1–2 of the ladder ≥ 70%**, reported separately |
| AC-4.7 | Disputes **upheld** (re-test moved the value materially) | reported, with n — not a threshold |
| AC-4.8 | Retrieval nDCG@5 on the **held-out 50**, vs named baselines | ≥ 0.75 **and** > vector-only |
| AC-4.9 | Faculty sign-off on prerequisite edges | Completed before Phase 1 exit |
| AC-4.10 **[GATE]** | No `FailureSignature` reachable from any non-self endpoint; no endpoint under `/v1/candidates/{id}/` resolves for a third party | 0 |
| AC-4.11 **[GATE]** | No observation or fact written without an active consent record | 0 |
| AC-4.12 **[GATE]** | Distilled facts reaching a student without passing all four screens (§6.6b) | 0 |
| AC-4.13 **[GATE]** | `profile-summary` for a fixed `session_id` is byte-identical across 10 calls with `record()` interleaved | pass |
| AC-4.14 | Replayed observation changes mastery | 0 times |
| AC-4.15 | Map legibility: 5 test students shown the map for 5 seconds name their weakest area | 5 of 5 |

> AC-4.7 was "dispute rate < 5%", which is passed most easily by hiding the dispute button. The *upheld* rate is the honest metric and it is a free mini-result for the paper.

---

## 14. Build order

**~18 days, in milestones, not 14 in days.** The previous order booked one day for the entire distillation pipeline and one for retrieval plus hand-labelling an eval set, put three React screens in three days, and placed the simulation harness — the backbone of two papers — last, sharing a day with a meeting that depends on someone else's calendar. It also made day 8 depend on M13, a module that may not exist yet, which breaks the platform's own rule that every module clones and runs alone.

Two calendar dependencies start in **week 1** because they are not tasks: the faculty review booking, and the ethics annexe.

| Milestone | Days | Demoable outcome |
|---|---|---|
| **M0 — Contracts** | 1–2 | `ai_core` v0.2.0 published: `EvidenceRef`, `EvidenceSpan`, `Concept`, `ConceptEdge`, `MasteryBar`, `state()`. **Ethics annexe filed. Faculty review booked.** |
| **M1 — Ontology** | 2–4 | 120 concepts in YAML, loader, DAG validation, `ontology_lint` in CI, alias table, `POST /concepts/resolve`. `GET /health` + `/v1/deps` green — M15 stops reporting M04 as down. |
| **M2 — Store & write path** | 4–7 | SQLModel schema (both stores), `record()` with evidence enforcement, uuid5 idempotency, optimistic lock, outbox, batch endpoint. Adversarial tests pass. |
| **M3 — Simulation first** | 7–8 | 200 synthetic students, known abilities, **the full mis-specification grid**. Built *before* the estimators are finished — this is the harness that catches a bad decay curve or a bad `P(T)` in an afternoon instead of in a pilot. |
| **M4 — Estimators** | 8–11 | IRT EAP (2PL **+ GRM**), BKT as a read-time companion, asymmetric propagation writing derived observations, additive-drift decay, all clamps. Golden snapshot frozen. |
| **M5 — Read paths** | 11–13 | Working-tier table + pinned session snapshot, `/skill-graph/theta`, `/profile-summary`, evidence drawer, recursive bottleneck query, `retest_queue`. **M15's "Your preparation" block lights up.** |
| **M6 — Memory tiers** | 13–16 | Episodic writes behind an adapter seam (fixture-fed, M13 optional), distillation with the four screens, hybrid retrieval, 150-query eval set, the ~120-line IR harness. |
| **M7 — Surfaces** | 16–18 | Mastery map with the sparse state, "what I remember about you" with real deletion, dispute endpoint + queue state. Streamlit ops app (§6.10). |

**Deferred past Phase 1:** `TrajectoryChart` (M19 owns charts; M04 ships the endpoint), `DisputeDialog` UI (the endpoint and queue ship; the evidence drawer is the trust defence that actually carries §2.4), pgvector/HNSW/Redis, DKT.

---

## 15. Open decisions

Nine decisions, each with the call already made — a decision list without recommendations is a delay list.

| # | Decision | Call |
|---|---|---|
| 1 | Ontology size for Phase 1 | **120**, DSA + CS core + communication. 450 is the year-end target. At 180 the granularity check in §6.1 fails by construction, because M5 cannot seed 3+ calibrated items per concept that fast. |
| 2 | Expose θ (logit) to students? | **No.** Five-state label + `mastery_p`. Logits are meaningless to a 20-year-old and invite gaming. |
| 3 | Cohort priors — which cohort? | **Branch**, institute fallback at n < 30 — **plus the published wash-out test** (§12, cold-start row): the prior must be gone by n = 3. Without that test a branch-level prior is a fairness problem sitting inside Paper 2, not a Paper 3 topic. |
| 4 | Keep BKT in Phase 1? | **Yes, but display-only**, fixed global priors, `P(T) = 0` within session, computed on read. Two persisted beliefs about one latent quantity with no arbitration rule is a bug, not a feature. Cutting it entirely is also defensible. |
| 5 | Who owns the in-session ability estimate? | **M5** (provisional, in-memory, discarded at session end). M04 owns the durable posterior. Written into §6.3. |
| 6 | Decay curve | **Additive variance drift** (§6.5). Master plan §30.2 says power-law and must be amended, or the thesis carries two forgetting models. |
| 7 | DKT comparison | **Public KT benchmarks primarily** (ASSISTments, EdNet-KT1), own cohort as a powered descriptive replication. Decided now, not in Month 10, because it changes what is logged from day 1. |
| 8 | Memory paper: Paper 2 or separate? | **Fold into Paper 2** as the retrieval-ablation section. Deferring to Month 6 is after the annotation it requires must already have started. |
| 9 | Fact deletion re-derivation | **Yes after a 30-day suppression window; never after a second deletion** — and the student is told which promise they are getting, in the words in §8. |
| 10 | Does a placement cell ever see a failure signature? | **No.** AC-4.10, a gate and a test, not an assumption. |
