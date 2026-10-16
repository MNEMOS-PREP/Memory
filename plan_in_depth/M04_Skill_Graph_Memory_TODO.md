# M04 — TODO · Candidate Skill Graph & Memory Core


> **Completion: 95%** — 25 of 28 functional requirements met, 3 partially. Three requirements are declared and unfed: the semantic tier's fields, its versioning and its failure signatures all exist and are read, and nothing writes a `MemoryFact` because the nightly distiller is not built. The skill graph has had a screen since 2026-10-03 (`/skills` in the shell); the spec's six UI moments sit outside the FR table, so this figure does not count them either way.
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-08-28; re-checked 2026-10-04 and 2026-10-17: unchanged, the distiller is still not built. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Running list for **M04 Candidate Skill Graph & Memory Core**.
Spec: [M04_Skill_Graph_Memory.md](M04_Skill_Graph_Memory.md)

> **Read this first when starting a session on M04.** It is the running state
> of the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1 · **Owner:** E3 · **Ports:** API `8104`, web `5204`
- **Repo:** `Memory`

Legend: ✅ done · 🟡 partly done · ⬜ not started

### 2026-10-07/13 — machine-learning concepts, the college's curricula, an honest count

- ✅ **36 machine-learning concepts** (`f710a2c`, the user's decision): the `ml`
  domain was declared with none, so asking for a machine-learning interview
  gave DSA. Added from public syllabi (CS229, Google's ML Crash Course,
  CS231n/CS224n), topic names only — foundations, models, deep learning.
  Prerequisite edges acyclic, no alias collisions, `reviewed: false` like
  every other edge. The ontology is 120 + 36.
- ✅ **Curricula from the college's own PDFs** (`55a01bd`): `jobs/curricula.py`
  builds `packages/knowledge/curricula/<id>.json` for B.Tech CSE 2023 and
  B.Tech CSE-AI 2022 — every semester's courses, elective slots and baskets,
  and each course's ontology concepts with the syllabus words that matched.
  Tables are read by their cells (PyMuPDF) and every title is checked against
  its syllabus page; a single word maps only where the same syllabus teaches
  that domain by phrase ("functions" in Calculus maps to nothing).
  `GET /v1/curricula[/{id}]`; the profile gains `curriculum_id`, `semester`
  and `courses` (an unknown code is a 422); `GET /v1/candidates/{id}/coursework`
  answers what the student's courses have taught so far, and M06 plans a
  mixed interview from it. The shell's welcome step and Settings ask for them.
- ✅ **The skill graph counts what was tested** (`a7a9efe`): a topic moved only
  by its neighbours' answers is listed with the untested ones, so the count is
  the rows shown; every bar starts at one x (Core's `labelWidth`). Frontend on
  `@ai/core` v0.36.0.
- No requirement moves: the curricula and the profile sit outside §4, and the
  distiller is still not built (checked 2026-10-17: `jobs/` holds curricula,
  decay and simulate, and nothing writes a `MemoryFact`).

### 2026-10-04 — the student's profile, and a skill graph that teaches

- ✅ **A student profile** — `GET/PUT /v1/candidates/{id}/profile`: name, target
  role, companies, drives with dates, weekly goal, reminder time. Empty rather
  than 404 before onboarding; it goes with the export and the hard delete like
  every row about the student. The shell's welcome and settings screens call
  it — until now M04's consent, export and delete had no caller but curl.
- ✅ `/v1/concepts/{id}` names its neighbours, so no screen shows an id.
- ✅ The drawer's **Learn** section: what the topic builds on (with the
  student's own state on each), what it unlocks, its other names, a focused
  interview on it, a reading link. The estimator's numbers fold under Details.
- ✅ A concept moving up while the page is open gets a toast (no sparks under
  reduced motion); one moving down is shown, never celebrated or scolded.
- ✅ Answer bands as ink with a coloured dot (orange text measured 3.75:1); the
  drawer's bar has a fixed-width track.
- No requirement moves: the profile and the screens sit outside §4.

### 2026-10-03 — the first screen, and the key file beside the repos

- ✅ **A UI: the skill graph at `/skills`** (`Frontend/frontend_M04_Skill_Graph_Memory`,
  web `5204`, mounted in Platform_Shell). The student's own beliefs, grouped
  by domain with core's `MasteryBar`; **what moved since the page opened**
  first (it polls while open, so an interview scored elsewhere shows up as it
  lands); "what is blocking you" from `/bottlenecks`; every bar opens its
  evidence — θ with its error, each observation, the student's own quoted
  words, and a link to how M13 scored that answer. Untested is a count
  (`NotYetTested`), never a zero. A placement officer is told it is a
  student's own view; an admin sees the seeded student. `m04-web` is on in
  `scripts/services.txt`.
- ✅ **`keys.py` reads the `keys.txt` beside the repos** (and `AI_KEYS_FILE`),
  as M02 and M06 already did. On a fresh demo machine that file is the only
  one. `test_keys_location.py`.
- ✅ `seed.py` is run by `Platform_Shell/start.bat seed` with every other
  module's; it was already idempotent.

### 2026-10-02 — the service secret moves to Platform_Core (v0.12.0)

- ✅ `require_service` is `ai_core.service`'s now; `keys.py` keeps only
  `load_keys`. **The rule changed:** an unset secret used to leave the four
  service routes OPEN, with a warning; now every module on one machine shares a
  machine secret nobody configures, so the routes are never open and a fresh
  clone still works. M06, M13 and M15 send it from the same place.
  `required_keys.txt` no longer ships a placeholder value, since setting it in
  one module's `keys.txt` only would 401 every call between modules.
  `test_every_route_another_module_calls_refuses_a_browser` runs the shared
  check (`assert_service_only`), and ungating one route fails it.

### 2026-10-02 — an ask from M06

- ⬜ (standing, M06 review Part 5) Source `recent_sessions` from M06.
  `GET /v1/interviews/by-candidate/{id}/recent` exists for exactly this slot.
- **Confirmed live** (2026-10-02, the guard on with a shared service secret):
  M06's artifacts registered (201), M13's observations accepted, and the skill
  graph moved. An anonymous read and another student's read were refused
  (403), and theta without the service secret was refused (401).

---

## 0. Ideas and scouting

Things worth building that did not come from the spec — usually from reading
somebody else's implementation. **New ideas go at the top of this section.**

The rule we keep arriving at: borrow a **technique**, not a **component**. The
platform's contracts — character offsets, per-fact provenance, permanent
evidence — are more demanding than general-purpose tools assume, so integration
usually costs more than reimplementing the one idea we actually wanted.

### ⬜ Reciprocal Rank Fusion for recall — worth taking

From [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) (TS, Apache-2.0,
27k stars). **Do not adopt the system** — see the verdict below — but its retrieval
technique is good and free.

It fuses three ranked lists (BM25 keyword, vector cosine, graph traversal) with
Reciprocal Rank Fusion at k=60: score each item as the sum of `1 / (k + rank)`
across the lists it appears in. Reported R@5 of 95.2% against 86.2% for BM25
alone on LongMemEval-S.

About fifteen lines, no dependency. Useful anywhere several ranking signals
exist and nothing principled combines them.

### ⬜ Contradiction detection between observations

When two observations about the same concept disagree, that is information, not
noise. `Platform_Core` already ships `ContestedFact` for rendering exactly this
in M15 — M04 should be able to produce it.

---

## Scouting verdict: agentmemory — **do not adopt**

Superficially a close match: cross-session memory, decay, graph, evidence
provenance. It is a different problem underneath.

It remembers **what an agent did** — tool calls, file edits, decisions —
retrieved by similarity. M04 must hold a **calibrated belief about a person's
mastery of a concept**, with uncertainty, updated by evidence-linked
observations. Psychometrics, not retrieval.

**The decay is the opposite kind, and that is disqualifying.** AgentMemory runs
an Ebbinghaus curve and stale memories **auto-evict**; forgetting is the
feature. Here, the *belief* decays toward uncertainty and the *evidence is
permanent*. A student who proved they knew binary search in March is less
certain in August, and the March observation never goes away.

`ai_core.mastery.se_effective(se, last_evidence_at, now)` already implements the
right model, with `SE_PRIOR` as the ceiling on decayed uncertainty — and it
raises uncertainty without lowering the displayed bar. `ai_core.evidence` has a
three-valued `ArtifactState` (present / tombstoned / absent) specifically so
"deleted on purpose" stays distinguishable from "never existed". A store that
evicts on a TTL puts holes in M19's ledger and breaks Rule 3.

Operationally it is also wrong for us: TypeScript/Node on a pinned `iii` engine
binary (v0.11.2), where native Windows needs manual `iii.exe` extraction and the
docs recommend WSL2 or Docker. The platform is Python/FastAPI/SQLModel.

Three smaller confirmations we are already doing the right thing: version
chaining (superseded leaves the search index, stays in history), an immutable
origin channel stamped at capture, and a privacy filter before storage.

---

## 1. Where the module stands

| | |
|---|---|
| Status | **Built.** FR coverage was audited on 2026-08-28 (the header's counts) and re-checked on 2026-10-04 and 2026-10-17. The per-requirement table was never written into this file, and the §13 acceptance gates have not been walked one by one |
| Backend tests passing | **170** |
| Release gates (`-m gate`) | **16** |
| Frontend | **`/skills`** — the skill graph, mounted in the shell (2026-10-03) |

*Counted 2026-10-17 by running the suite, not by reading this file.*

> **Re-checked 2026-10-17:** the semantic tier is still unfed. `MemoryFact`
> has readers (`service.py`) and no writer, because the nightly distiller does
> not exist — so the header's three partial requirements stand.

---

## 2. Next

1. **The nightly distiller** — the one writer `MemoryFact` lacks. It completes
   the three partial requirements (the semantic tier's fields, its versioning,
   its failure signatures), which is what stands between M04 and 100% of §4.
2. **Walk the §13 acceptance gates** one at a time and write what each needs here.
3. The two scouting items above (RRF for recall, contradiction detection),
   once the distiller exists to feed them.

---

## 3. Deferred — inter-module

Not gaps in M04. Each needs a module that is not built or not wired yet, and
each is listed so it is not mistaken for an oversight.

_To fill in._
