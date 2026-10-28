"""The concept graph (§6.1) — loading, linting, resolving, walking."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend_M04_Skill_Graph_Memory import ontology as ontology_module
from backend_M04_Skill_Graph_Memory.ontology import (
    Ontology,
    OntologyError,
    UnknownConcept,
    parse,
)

DP = "concept:dynamic_programming"
RECURSION = "concept:recursion"


def test_the_shipped_ontology_is_phase_one_sized(graph):
    """Open decision 1: 120 concepts, DSA + CS core + communication — and,
    by the user's decision of 2026-10-07, 36 for machine learning, because an
    ML interview had nothing in ML to ask about. At 180 the granularity check
    fails by construction, because M05 cannot seed 3+ calibrated items per
    concept that fast. 2026-10-29: 9 for reinforcement learning, from the RL
    course's syllabus, because a viva on it (M20) had nothing to file under."""
    assert len(graph) == 165
    domains = {str(c.domain) for c in graph.concepts.values()}
    assert domains == {"dsa", "cs_core", "communication", "ml"}
    assert sum(1 for c in graph.concepts.values() if str(c.domain) == "ml") == 45


def test_it_says_it_has_not_been_reviewed(graph):
    """AC-4.9 gates Phase-1 exit on a faculty walk of the prerequisite edges.
    Until that happens the graph must not imply an authority it does not have —
    including to the four modules that call `/v1/concepts`."""
    assert graph.reviewed is False


def test_no_cycles_in_the_prerequisite_graph(graph):
    """FR-4.2 and EC-4.11's "impossible": a cycle makes propagation loop and
    the bottleneck walk never terminate."""
    assert graph.find_cycles() == []


def test_aliases_do_not_collide(graph):
    """A collision silently sends a student's topic to another concept's belief
    — the kind of bug that produces a confidently wrong number rather than an
    error."""
    collisions = [i for i in graph.lint() if i.code == "alias-collision"]
    assert collisions == []


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("DP", DP),
        ("dp", DP),
        ("Dynamic Programming", DP),
        ("dynamic programing", DP),  # the misspelling, on purpose
        ("memoization", DP),
        ("recursion", RECURSION),
        ("BST", "concept:binary_search_trees"),
        ("dsu", "concept:union_find"),
        ("acid", "concept:transactions_acid"),
    ],
)
def test_the_ways_students_actually_type_a_topic(graph, typed, expected):
    """FR-4.21. M15 keys its corpus on free-text labels students typed into a
    post-drive form; M01 maps resume surface forms; M02 maps JD requirements.
    None of them can invent this table."""
    assert graph.resolve(typed) == expected


def test_an_unknown_label_resolves_to_none_not_to_a_guess(graph):
    """EC-4.18. A resolver that guesses is worse than one that says it does not
    know: the caller can degrade an unmatched term to zero weight and SAY so,
    but it cannot un-learn a wrong match."""
    assert graph.resolve("blockchain") is None
    assert graph.resolve("competitive programming vibes") is None


def test_walking_up_finds_what_a_concept_is_built_on(graph):
    prereqs = {n.concept_id for n in graph.walk_up(DP, max_hops=1)}
    assert RECURSION in prereqs
    assert "concept:arrays" in prereqs


def test_walking_down_finds_what_depends_on_a_concept(graph):
    dependents = {n.concept_id for n in graph.walk_down(RECURSION, max_hops=1)}
    assert DP in dependents
    assert "concept:backtracking" in dependents


def test_a_walk_carries_strength_and_decays_with_distance(graph):
    two_hops = {n.concept_id: n for n in graph.walk_up(DP, max_hops=2)}
    assert "concept:functions_and_scope" in two_hops
    assert two_hops["concept:functions_and_scope"].hops == 2
    assert two_hops["concept:functions_and_scope"].strength < two_hops[RECURSION].strength


def test_a_walk_keeps_the_strongest_route_not_the_first_one(graph):
    """Two routes to the same concept are common — DP reaches arrays directly
    and through recursion — and the weaker one must not decide how much
    evidence transfers."""
    reached = {n.concept_id: n for n in graph.walk_up(DP, max_hops=2)}
    direct = 0.4  # DP -> arrays, from the YAML
    assert reached["concept:arrays"].strength >= direct


def test_an_unknown_concept_raises(graph):
    with pytest.raises(UnknownConcept):
        graph.get("concept:quantum_flapdoodle")


def test_a_cycle_is_refused_at_load(tmp_path: Path):
    """The linter runs at load, not by eye, and a graph with a cycle is not
    "mostly fine": propagation would loop on it."""
    bad = tmp_path / "concepts.yaml"
    bad.write_text(
        textwrap.dedent(
            """
            version: "9.9"
            concepts:
              - id: concept:a
                name: A
                domain: dsa
                level: foundational
                prerequisites: [{id: concept:b, strength: 1.0}]
              - id: concept:b
                name: B
                domain: dsa
                level: foundational
                prerequisites: [{id: concept:a, strength: 1.0}]
            """
        ),
        encoding="utf-8",
    )
    ontology_module.reset_cache()
    with pytest.raises(OntologyError, match="cycle"):
        ontology_module.load(bad, force=True)
    ontology_module.reset_cache()


def test_a_broken_reload_keeps_the_last_good_graph(tmp_path: Path, graph):
    """§10: a parse error after a bad edit must not take the module down. Every
    running session is reading this graph."""
    broken = tmp_path / "broken.yaml"
    broken.write_text("this: [is not: valid", encoding="utf-8")

    still_serving = ontology_module.load(broken, force=True)

    assert still_serving.version == graph.version
    assert len(still_serving) == len(graph)


def test_duplicate_ids_are_refused():
    document = {
        "version": "1.0",
        "concepts": [
            {"id": "concept:x", "name": "X", "domain": "dsa", "level": "foundational"},
            {"id": "concept:x", "name": "X again", "domain": "dsa", "level": "foundational"},
        ],
    }
    with pytest.raises(OntologyError, match="duplicate"):
        parse(document)


def test_foundational_floors_are_marked(graph):
    """M16 §6.4a: "work on variables" is insulting advice. The floor lives in
    the shared query, and it is only meaningful if the YAML marks it."""
    floors = {c.id for c in graph.concepts.values() if c.foundational_floor}
    assert floors == {
        "concept:variables_and_types",
        "concept:control_flow",
        "concept:functions_and_scope",
    }


def test_edges_are_projected_into_tables_for_the_recursive_walk(session, graph):
    """The YAML is the source of truth and the in-memory graph is what the write
    path validates against; these rows exist so §6.8's CTE has something to
    join."""
    from sqlmodel import select

    from backend_M04_Skill_Graph_Memory.models import ConceptEdgeRow, ConceptRow

    assert len(session.exec(select(ConceptRow)).all()) == len(graph)
    assert len(session.exec(select(ConceptEdgeRow)).all()) == len(graph.edges)


def test_syncing_twice_does_not_duplicate(session, graph):
    from sqlmodel import select

    from backend_M04_Skill_Graph_Memory.models import ConceptEdgeRow
    from backend_M04_Skill_Graph_Memory.service import sync_ontology

    before = len(session.exec(select(ConceptEdgeRow)).all())
    sync_ontology(session, graph)
    assert len(session.exec(select(ConceptEdgeRow)).all()) == before


def test_alias_keys_include_the_id_and_the_name(graph):
    concept = graph.get(DP)
    keys = Ontology._alias_keys(concept)
    assert "dynamic programming" in keys
