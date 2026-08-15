"""The concept graph: loading it, linting it, and walking it.

Spec: §6.1 (the ontology), §6.4 (propagation walks), FR-4.1, FR-4.2, FR-4.21.

The ontology is a hand-curated YAML file under version control, reviewed edge
by edge by a faculty member (AC-4.9). It is loaded once into an immutable
in-memory object, because:

* every write validates its `concept_id` against it (§6.2 — SQLite does not
  enforce a foreign key by default, so "the FK will catch it" is not a check);
* propagation walks it on every observation;
* `POST /v1/concepts/resolve` is called by four other modules on their own
  hot paths.

A few hundred nodes in a dict is microseconds and needs no cache, no table and
no invalidation rule. It is re-read only on process start, which is also what
makes §10's "ontology load fails -> last-known-good" implementable: the last
successfully parsed graph stays in memory and the process keeps serving.

**Edge direction is the thing to get right**, because reversing it silently
inverts the bottleneck query rather than breaking it:

    prerequisites: [{id: X}]  under C   =>   X --prerequisite_of--> C
    specialises:   [X]        under C   =>   X --specialises-->     C

so `walk_up(C)` (what C depends on) follows edges *into* C, and `walk_down(C)`
(what depends on C) follows edges *out of* C.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from ai_core.concepts import Concept, ConceptEdge, EdgeKind, normalise_alias

log = logging.getLogger(__name__)

#: Searched upwards from this file, so the module works from Backend/ (uvicorn),
#: from the repo root (pytest) and from a job runner without a path argument.
ONTOLOGY_RELATIVE = Path("packages/knowledge/ontology/concepts.yaml")


class OntologyError(RuntimeError):
    """The ontology is unusable. Raised at load, never at request time."""


class UnknownConcept(KeyError):
    """A write named a concept that does not exist in the loaded ontology.

    Hard failure, deliberately: accepting an observation about
    `concept:dynamic_programing` (one 'm') would create a belief nobody ever
    reads and quietly halve the evidence behind the one they do.
    """

    def __init__(self, concept_id: str) -> None:
        super().__init__(concept_id)
        self.concept_id = concept_id

    def __str__(self) -> str:
        return f"unknown concept: {self.concept_id}"


@dataclass(frozen=True)
class LintIssue:
    severity: str  # "error" blocks CI; "warning" is reported and allowed
    code: str
    message: str


@dataclass(frozen=True)
class Neighbour:
    concept_id: str
    #: Product of edge strengths along the path — a hop-2 blocker behind a 0.4
    #: edge must not outrank a hop-1 blocker behind a 0.9 one (§6.4, §6.8).
    strength: float
    hops: int


@dataclass
class Ontology:
    version: str
    reviewed: bool
    concepts: dict[str, Concept]
    edges: list[ConceptEdge]
    #: normalised alias -> concept id. Includes each concept's own name and id.
    alias_index: dict[str, str] = field(default_factory=dict)
    _prereqs_of: dict[str, list[ConceptEdge]] = field(default_factory=dict)
    _dependents_of: dict[str, list[ConceptEdge]] = field(default_factory=dict)
    source_path: Path | None = None

    # ── construction ─────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        for edge in self.edges:
            if edge.kind is not EdgeKind.prerequisite_of:
                continue
            self._prereqs_of.setdefault(edge.dst, []).append(edge)
            self._dependents_of.setdefault(edge.src, []).append(edge)
        # Sorted so that two concurrent sessions touching overlapping
        # neighbourhoods take row locks in the same order (§6.2). Unsorted,
        # that is a deadlock on Postgres and a puzzling intermittent on SQLite.
        for bucket in (self._prereqs_of, self._dependents_of):
            for key in bucket:
                bucket[key].sort(key=lambda e: (e.src, e.dst))

    # ── lookups ──────────────────────────────────────────────────────────

    def __contains__(self, concept_id: object) -> bool:
        return concept_id in self.concepts

    def __len__(self) -> int:
        return len(self.concepts)

    def get(self, concept_id: str) -> Concept:
        try:
            return self.concepts[concept_id]
        except KeyError:
            raise UnknownConcept(concept_id) from None

    def require(self, concept_id: str) -> None:
        if concept_id not in self.concepts:
            raise UnknownConcept(concept_id)

    def by_domain(self, domain: str | None = None) -> list[Concept]:
        values = sorted(self.concepts.values(), key=lambda c: (c.domain, c.name))
        return [c for c in values if domain is None or c.domain == domain]

    def resolve(self, label: str) -> str | None:
        """A free-text topic label to a concept id, or None (EC-4.18).

        None is a real answer and callers must render it as one. A label this
        cannot match comes back `unresolved`, never as `theta = 0.0` — a silent
        zero is a confident claim of ignorance, and it is platform Rule 2
        violated at an API boundary.
        """
        return self.alias_index.get(normalise_alias(label))

    def resolve_all(self, labels: list[str]) -> dict[str, str | None]:
        return {label: self.resolve(label) for label in labels}

    # ── walks (§6.4) ─────────────────────────────────────────────────────

    def walk_up(self, concept_id: str, max_hops: int = 2) -> list[Neighbour]:
        """Prerequisites of a concept: what it is built on.

        Success propagates UP this walk — you cannot do DP without recursion,
        so a correct DP answer is weak evidence about recursion.
        """
        return self._walk(concept_id, max_hops, self._prereqs_of, take="src")

    def walk_down(self, concept_id: str, max_hops: int = 2) -> list[Neighbour]:
        """Dependents of a concept: what is built on it.

        Failure propagates DOWN this walk, and only as widened uncertainty
        (§6.4). Failing recursion does not prove you cannot do DP — it proves
        we should check.
        """
        return self._walk(concept_id, max_hops, self._dependents_of, take="dst")

    def _walk(
        self,
        start: str,
        max_hops: int,
        adjacency: dict[str, list[ConceptEdge]],
        *,
        take: str,
    ) -> list[Neighbour]:
        self.require(start)
        best: dict[str, Neighbour] = {}
        queue: deque[tuple[str, float, int]] = deque([(start, 1.0, 0)])

        while queue:
            node, strength, hops = queue.popleft()
            if hops >= max_hops:
                continue
            for edge in adjacency.get(node, []):
                nxt = edge.src if take == "src" else edge.dst
                if nxt == start:
                    continue  # a cycle would be a lint error; do not loop on one
                carried = strength * edge.strength
                seen = best.get(nxt)
                # Keep the STRONGEST path to each neighbour, not the first one
                # found. Two routes to the same concept are common (DP reaches
                # arrays directly and through recursion) and the weaker one
                # would otherwise decide how much evidence transfers.
                if seen is None or carried > seen.strength:
                    best[nxt] = Neighbour(concept_id=nxt, strength=carried, hops=hops + 1)
                    queue.append((nxt, carried, hops + 1))

        return sorted(best.values(), key=lambda n: n.concept_id)

    # ── linting (§6.1, FR-4.2) ───────────────────────────────────────────

    def lint(self) -> list[LintIssue]:
        """Everything a linter can check without M05's item bank.

        Runs in CI, not by eye. Trap 5 says the ontology is load-bearing; this
        is how that stays true after week 3, when someone appends forty
        concepts on a Friday.

        The granularity check (any concept with > 40 or < 3 bank items is
        mis-sized) needs M05 seeded and is reported as skipped until then —
        stated rather than silently omitted, so nobody believes it passed.
        """
        issues: list[LintIssue] = []

        for edge in self.edges:
            for end in (edge.src, edge.dst):
                if end not in self.concepts:
                    issues.append(
                        LintIssue("error", "unknown-edge-end", f"edge names missing concept {end}")
                    )
            if edge.ontology_version != self.version:
                issues.append(
                    LintIssue(
                        "error",
                        "version-crossing-edge",
                        f"edge {edge.src}->{edge.dst} is v{edge.ontology_version}, file is v{self.version}",
                    )
                )
            if edge.src == edge.dst:
                issues.append(LintIssue("error", "self-edge", f"{edge.src} depends on itself"))

        for cycle in self.find_cycles():
            issues.append(
                LintIssue("error", "cycle", "prerequisite cycle: " + " -> ".join(cycle))
            )

        seen: dict[str, str] = {}
        for concept in self.concepts.values():
            for alias in self._alias_keys(concept):
                owner = seen.get(alias)
                if owner is not None and owner != concept.id:
                    issues.append(
                        LintIssue(
                            "error",
                            "alias-collision",
                            f'"{alias}" claimed by both {owner} and {concept.id}',
                        )
                    )
                seen[alias] = concept.id

        connected = {e.src for e in self.edges} | {e.dst for e in self.edges}
        for concept in self.concepts.values():
            if concept.id not in connected:
                # A warning, not an error: a genuinely standalone concept is
                # legitimate (several communication ones are). It is worth
                # seeing because it is also what an accidental typo in a
                # prerequisite id looks like.
                issues.append(
                    LintIssue("warning", "orphan", f"{concept.id} has no edges in either direction")
                )

        issues.append(
            LintIssue(
                "skipped",
                "granularity",
                "needs M05's item bank: flags any concept with > 40 or < 3 calibrated items",
            )
        )
        return issues

    def find_cycles(self) -> list[list[str]]:
        """Cycles in `prerequisite_of`. FR-4.2, and EC-4.11's "impossible"."""
        colour: dict[str, int] = {}  # 0 = visiting, 1 = done
        cycles: list[list[str]] = []
        stack: list[str] = []

        def visit(node: str) -> None:
            colour[node] = 0
            stack.append(node)
            for edge in self._dependents_of.get(node, []):
                nxt = edge.dst
                if colour.get(nxt) == 0:
                    start = stack.index(nxt)
                    cycles.append([*stack[start:], nxt])
                elif nxt not in colour:
                    visit(nxt)
            stack.pop()
            colour[node] = 1

        for concept_id in sorted(self.concepts):
            if concept_id not in colour:
                visit(concept_id)
        return cycles

    @staticmethod
    def _alias_keys(concept: Concept) -> list[str]:
        keys = [normalise_alias(concept.name), normalise_alias(concept.id.split(":", 1)[-1])]
        keys += [normalise_alias(a) for a in concept.aliases]
        return [k for k in keys if k]


# ── loading ──────────────────────────────────────────────────────────────


def default_path(start: Path | None = None) -> Path:
    """Find `packages/knowledge/ontology/concepts.yaml` from wherever we run."""
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        candidate = parent / ONTOLOGY_RELATIVE
        if candidate.exists():
            return candidate
    return Path.cwd() / ONTOLOGY_RELATIVE


def parse(document: dict) -> Ontology:
    version = str(document.get("version") or "1.0")
    concepts: dict[str, Concept] = {}
    edges: list[ConceptEdge] = []

    entries = document.get("concepts") or []
    if not entries:
        raise OntologyError("ontology file declares no concepts")

    for entry in entries:
        concept = Concept(
            id=entry["id"],
            name=entry["name"],
            domain=entry["domain"],
            level=entry["level"],
            aliases=list(entry.get("aliases") or []),
            foundational_floor=bool(entry.get("foundational_floor", False)),
            typical_question_time_s=int(entry.get("typical_question_time_s", 300)),
            ontology_version=version,
        )
        if concept.id in concepts:
            raise OntologyError(f"duplicate concept id: {concept.id}")
        concepts[concept.id] = concept

        for prereq in entry.get("prerequisites") or []:
            edges.append(
                ConceptEdge(
                    src=prereq["id"],
                    dst=concept.id,
                    kind=EdgeKind.prerequisite_of,
                    strength=float(prereq.get("strength", 1.0)),
                    ontology_version=version,
                )
            )
        for narrower in entry.get("specialises") or []:
            edges.append(
                ConceptEdge(
                    src=narrower,
                    dst=concept.id,
                    kind=EdgeKind.specialises,
                    strength=1.0,
                    ontology_version=version,
                )
            )

    ontology = Ontology(
        version=version,
        reviewed=bool(document.get("reviewed", False)),
        concepts=concepts,
        edges=edges,
    )
    ontology.alias_index = _build_alias_index(ontology)
    return ontology


def _build_alias_index(ontology: Ontology) -> dict[str, str]:
    index: dict[str, str] = {}
    for concept in ontology.concepts.values():
        for key in Ontology._alias_keys(concept):
            # First writer wins, and `lint()` reports the collision. Silently
            # letting the last one win would make resolution depend on YAML
            # ordering, which is the least debuggable failure available.
            index.setdefault(key, concept.id)
    return index


_cache: Ontology | None = None


def load(path: Path | None = None, *, force: bool = False) -> Ontology:
    """Load the ontology, keeping the last good copy on failure (§10).

    A parse error after a bad edit must not take the module down: every
    running session is reading this graph, and the honest behaviour is to keep
    serving the version we already validated and shout in the log.
    """
    global _cache
    if _cache is not None and not force:
        return _cache

    target = path or default_path()
    try:
        document = yaml.safe_load(target.read_text(encoding="utf-8"))
        ontology = parse(document)
        ontology.source_path = target
    except Exception as exc:  # noqa: BLE001 — every failure mode gets the same answer
        if _cache is not None:
            log.error("ontology reload failed (%s); keeping v%s in memory", exc, _cache.version)
            return _cache
        raise OntologyError(f"could not load ontology from {target}: {exc}") from exc

    errors = [i for i in ontology.lint() if i.severity == "error"]
    if errors:
        # An ontology with a cycle or a colliding alias is not "mostly fine":
        # propagation would loop and a student's topic would land on another
        # concept's belief. Refuse it at load, where a human is watching.
        detail = "; ".join(f"[{i.code}] {i.message}" for i in errors[:5])
        if _cache is not None:
            log.error("ontology v%s failed lint (%s); keeping previous", ontology.version, detail)
            return _cache
        raise OntologyError(f"ontology failed lint: {detail}")

    _cache = ontology
    log.info(
        "ontology v%s loaded: %d concepts, %d edges, reviewed=%s",
        ontology.version,
        len(ontology.concepts),
        len(ontology.edges),
        ontology.reviewed,
    )
    return ontology


def reset_cache() -> None:
    """Test seam. Production reloads only on process start."""
    global _cache
    _cache = None
