# M04 — TODO · Candidate Skill Graph & Memory Core


> **Completion: 95%** — 25 of 28 functional requirements met, 3 partially. Three requirements are declared and unfed: the semantic tier's fields, its versioning and its failure signatures all exist and are read, and nothing writes a `MemoryFact` because the nightly distiller is not built. **No UI at all** — the spec's six moments sit outside the FR table, so this figure does not count them.
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-08-28. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Running list for **M04 Candidate Skill Graph & Memory Core**.
Spec: [M04_Skill_Graph_Memory.md](M04_Skill_Graph_Memory.md)

> **Read this first when starting a session on M04.** It is the running state
> of the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1 · **Owner:** E3 · **Ports:** API `8104`, web `5204`
- **Repo:** `Memory`

Legend: ✅ done · 🟡 partly done · ⬜ not started

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
| Status | **Built, and not yet audited against the spec.** |
| Backend tests passing | **137** |
| Release gates (`-m gate`) | **16** |
| Route decorators | **19** |
| Frontend | **none on disk** |

*Counted 2026-08-25, by running the suite — not by reading this file. This row
replaced "Not started", which was written before the module was and had become
the kind of line the header above warns about: the next session trusts it.*

> **What has NOT been done is the audit.** Nobody has walked M04's functional
> requirements one at a time and checked each against the code. A green suite
> says the tests that exist pass; it does not say which requirements have tests.
> M01 learned that the expensive way — its FR table read 98% complete while the
> §13 KPI had no numerator, the semantic tier was absent and ten endpoints had
> no client. Every one of those was invisible from a passing suite.
>
> The next session on M04 should start there, and write what it finds here.
| Spec | Written — see the link above |

_Fill this in when work on M04 begins: tests passing, gates, FR coverage,
and what is actually blocking._

---

## 2. Next

_To fill in._ The spec's §4 functional requirements and §13 acceptance
gates are the natural first pass — copy them in as a checklist, then mark what
already exists.

---

## 3. Deferred — inter-module

Not gaps in M04. Each needs a module that is not built or not wired yet, and
each is listed so it is not mistaken for an oversight.

_To fill in._
