import networkx as nx
import pytest

from braess.frank_wolfe import frank_wolfe
from braess.models import EdgeId, ODPair
from braess.removal import (
    RemovalCandidate,
    all_od_pairs_are_connected,
    run_single_removal,
    select_removal_candidates,
)
from braess.synthetic import build_braess_network


DEMAND = [
    ODPair(
        origin="O",
        destination="D",
        demand=4000.0,
    )
]


def test_removing_connector_detects_braess_effect() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    baseline = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    candidate = RemovalCandidate(
        edge=EdgeId("A", "B", 0),
        baseline_flow=4000.0,
        name="Conexão sintética",
        highway="synthetic",
    )

    result = run_single_removal(
        graph,
        DEMAND,
        baseline,
        candidate,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert result.connected
    assert result.error is None
    assert result.solver_result is not None
    assert result.solver_result.converged

    assert baseline.average_travel_time == pytest.approx(
        80.0,
        abs=1e-5,
    )

    assert (
        result.solver_result.average_travel_time
        == pytest.approx(
            65.0,
            abs=1e-5,
        )
    )

    assert result.absolute_improvement == pytest.approx(
        60000.0,
        abs=1e-2,
    )

    assert result.relative_improvement == pytest.approx(
        0.1875,
        abs=1e-8,
    )

    assert result.possible_braess


def test_removing_required_edge_disconnects_od_pair() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        "O",
        "D",
        key=0,
    )

    assert all_od_pairs_are_connected(
        graph,
        [ODPair("O", "D", 100.0)],
    )

    graph.remove_edge(
        "O",
        "D",
        0,
    )

    assert not all_od_pairs_are_connected(
        graph,
        [ODPair("O", "D", 100.0)],
    )


def test_selects_candidates_by_highest_flow() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    baseline = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    candidates = select_removal_candidates(
        graph,
        baseline,
        limit=3,
    )

    assert len(candidates) == 3

    assert all(
        candidates[index].baseline_flow
        >= candidates[index + 1].baseline_flow
        for index in range(
            len(candidates) - 1
        )
    )


def test_original_graph_is_not_modified() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    baseline = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    candidate = RemovalCandidate(
        edge=EdgeId("A", "B", 0),
        baseline_flow=4000.0,
        name="Conexão sintética",
        highway="synthetic",
    )

    run_single_removal(
        graph,
        DEMAND,
        baseline,
        candidate,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert graph.has_edge(
        "A",
        "B",
        0,
    )