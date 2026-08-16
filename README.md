# M04 — Skill Graph & MNEMOS Memory

Part of the [AI Interviewer](https://github.com/MNEMOS-PREP) platform. **This
repo holds one module.** It clones, installs and runs on its own — you do not
need the other eighteen to work on it, and this one needs them less than most:
M04 is the root of the dependency graph. Eighteen modules read it and it reads
none of them.

Built on one rule: **if we cannot show you the answer that moved a number, the
number does not move.**

This is the module the project is named after. It holds a concept graph — what
there is to know and what depends on what — and, per student, a *belief* about
what they know. Not a score: a posterior with uncertainty, that decays. Every
module reads it before acting and writes evidence-linked observations after. It
is why the HR round knows what the technical round found, and why a student's
second session can open with *"last time you broke on how indexes work."*

Students never see the words "skill graph". They see an interviewer that
remembers them.

---

## Run it

```bat
start_graph.bat       this module only      API :8104
start_all.bat         everything            + any sibling module repo on disk
```

Both open **one** Windows Terminal window, one tab per service, and the **last
tab is the control tab**: **Y** closes exactly what was opened, **N** leaves it
running. Shutdown is **by PID, never by window title** — on Windows 11 a console
window's title belongs to the terminal host, so a title-matched `taskkill` takes
down the whole terminal.

First time, or any time the API has nothing to say:

```bat
cd Backend
.venv\Scripts\python seed.py
```

| | |
|---|---|
| API | http://127.0.0.1:8104 |
| API docs | http://127.0.0.1:8104/docs |
| Upstream health | http://127.0.0.1:8104/v1/deps |

Ports come from [`PORTS.txt`](PORTS.txt) — every module has a reserved pair.

### From scratch

```bat
cd Backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python seed.py
```

---

## What the seed shows you

`seed.py` writes a demo student with a deliberately uneven history — solid on
hashing and sorting, breaking on recursion, untouched across most of the
ontology. It goes through `record()` for every observation rather than
inserting mastery rows, which is slower and is the point: a seed script that
bypasses the write path is the first place someone copies the wrong pattern
from, and going through it means the evidence drawer works on the demo.

```bash
curl http://127.0.0.1:8104/v1/candidates/4d0aa1c0-0000-4000-8000-000000000004/mastery
```

```
Recursion              weak         needs work      p=0.21  n=2
Hashing                adequate     solid           p=0.63  n=2
Arrays                 emerging     just started    p=null  n=2  prop=4
Control Flow           not_tested   not tested yet  p=null  n=0  prop=6
not yet tested: 112 of 120
```

Four things in that output are the whole module:

**`p=null`, never `0`.** A student who was never asked about graphs did not
score zero on graphs. `mastery_p` is `None` for anything we cannot claim, at
every API and UI boundary (FR-4.9, AC-4.2).

**Arrays is `emerging` after two correct answers.** Both were top-rubric
responses on easy items, and a top category is a censored observation — it says
"at least this good" and puts no ceiling on ability, so SE stays wide. Two
right answers on easy questions genuinely do not pin down what someone knows.
Adaptive selection (M05) fixes that by asking something harder; the honest
state until then is "just started".

**Control Flow is `not_tested` with `prop=6`.** Six of the student's answers
implied something about it and nobody ever asked them about it directly. A
concept whose evidence is purely inherited renders `not_tested` (FR-4.24,
EC-4.16) — the inherited θ still exists and M05's selector still uses it,
because a selector does not have to justify a prior to a student.

**112 of 120 collapse to a count.** At 120 concepts with 8 measured, a full
grid is 93% empty, and an empty grid teaches a student the product is broken.

```bash
curl .../bottlenecks
  → Recursion blocks 20 · weighted 17.2 · θ=-1.30
```

---

## The rules this module keeps

1. **Every number traces to something the student said or did.** One write
   path, `record()`. An observation without a resolvable evidence reference is
   rejected by the type system, and the mutation helper refuses to run outside
   that path *at runtime* — because a CI grep cannot see into the eighteen
   repos that write here.
2. **"Not tested" is not zero.** Five states, one published definition, in
   `ai_core.mastery` because five surfaces render it.
3. **Decay widens the error bar; it never lowers the estimate.** A student must
   never appear to get worse by doing nothing. And a bar never *vanishes*
   either — once shown it greys and says when it was last checked.
4. **Evidence of competence transfers; evidence of failure does not.** A
   correct DP answer weakly raises recursion. A wrong one does **not** lower
   DP's descendants — it widens their uncertainty, so the selector goes and
   checks. This is the most important rule in the module.

---

## Layout

```
plan_in_depth/M04_Skill_Graph_Memory.md   the spec — source of truth
packages/knowledge/ontology/concepts.yaml 120 concepts, hand-curated, in git
module.json                               dependencies (none), machine-readable

Backend/backend_M04_Skill_Graph_Memory/
  app.py          runs this module on :8104
  router.py       §7 API surface — public / service / self
  models.py       §5 data contracts, §5.4 one schema for both stores
  ontology.py     §6.1 loading, linting, the graph walks
  store.py        §6.2 THE write path. Everything else reads.
  estimators.py   §6.3 IRT (2PL + GRM + 3PL) and BKT. Pure arithmetic.
  propagation.py  §6.4 the asymmetry, and its clamps
  service.py      read paths, §6.8 bottleneck, §6.9 re-test queue
  keys.py         credential loading, the service secret
  simulation.py   §12 the mis-specification grid; priors.py the cohort prior
  jobs/           offline runners — nothing here is on a request path
                  simulate.py the grid · decay.py the nightly §6.5 sweep
  tests/          117 tests, 15 of them release gates
Backend/seed.py   a demo student, through the real write path
```

`estimators.py`, `propagation.py` and `ontology.py` are pure logic over
in-memory values, so the arithmetic tests without a database. That is
deliberate: two constants in the previous revision of the spec were *provably*
wrong — a decay curve that could never fire, and a BKT transit that made wrong
answers raise mastery — and both were invisible to the tests written for them.
Arithmetic you can only reach through a web request does not get checked.

---

## Shared code is a dependency, not a copy

```
ai-core    git+https://github.com/MNEMOS-PREP/Platform_Core@v0.3.0#subdirectory=python
```

[Platform_Core](https://github.com/MNEMOS-PREP/Platform_Core) v0.3.0 carries
the two contracts M04 is not allowed to own, because more than one module
speaks them:

| | |
|---|---|
| `ai_core.evidence` | `EvidenceRef` and its resolution. M13 produces them, M04 stores them, M19 projects over them, M16 renders them. |
| `ai_core.mastery` | The five states, `mastery_p`, decay, hysteresis. Rendered by M04, M05, M15, M16 and M19. |

**Pinned by tag on purpose.** Nineteen repos on different versions is fine;
they move on *your* schedule.

### Working on both repos at once

Until the `v0.3.0` tag is pushed, or whenever you are editing `Platform_Core`
and this module together, install the local checkout over the pin:

```bat
cd Backend
.venv\Scripts\python -m pip install -e "..\..\Platform_Core\python"
.venv\Scripts\python -m pip install -e . --no-deps
```

Do **not** relax the pin in `pyproject.toml` to make the loop faster. That is
how a module ends up tracking `main` and getting a surprise breakage on a
Tuesday.

---

## Checks

```bat
cd Backend
.venv\Scripts\python -m pytest -q          :: 117 tests
.venv\Scripts\python -m pytest -m gate -q  :: 15 release gates
.venv\Scripts\python -m ruff check .
```

Every test runs **offline and against an in-memory database**. The only model
call in this module is the nightly distiller, which is on no read path, so a
suite needing a key would be a suite nobody else can run.

The gates encode the module's contract with the other eighteen. Any failure is
a P0:

| Gate | Asserts |
|---|---|
| AC-4.1 | Every mastery change traces to a resolvable evidence ref — **including propagated ones** |
| AC-4.1b | No mastery row exists without an observation behind it — **0** |
| AC-4.2 | `not_tested` rendered as a number, or returned as `0.0`, by any endpoint — **0** |
| AC-4.3 | Mastery written outside `record()` — **0**, by local grep **and** runtime guard |
| AC-4.10 | `FailureSignature` reachable from any endpoint — **0**; every candidate route identifies its caller |
| AC-4.11 | Observations written without an active consent record — **0** |
| §6.1 | The shipped ontology lints clean: no cycles, no alias collisions |
| §6.8 | The bottleneck query returns what the card renders — and nothing for a student with no measurements |

---

## What is not built yet

Against the spec's own build order (§14), M0–M4 are done. Still open, in order:

- **M5 — the working tier.** The `m04_profile_summary` table exists; the
  session-pinned snapshot (FR-4.23), `GET /profile-summary` and gate AC-4.13
  do not. M06 needs it; nothing else does yet.
- **M6 — memory tiers.** Distillation behind the four screens (§6.6b), hybrid
  retrieval, the 150-query eval set.
- **M7 — surfaces.** The mastery map, "what I remember about you", the
  Streamlit ops app (§6.10).

Two calendar items are on the critical path and are **not** code: the faculty
walk of the prerequisite edges (AC-4.9, gates Phase-1 exit) and the ethics
annexe. The ontology currently ships `reviewed: false` and every endpoint that
serves it says so.

If a behaviour is not in the spec, change the spec first.
