import pytest

from braess.frank_wolfe import frank_wolfe
from braess.models import EdgeId, ODPair
from braess.synthetic import build_braess_network


DEMAND = [
    ODPair(
        origin="O",
        destination="D",
        demand=4000.0,
    )
]


def test_frank_wolfe_converges_without_connector() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    result = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert result.converged
    assert result.relative_gap <= 1e-8

    assert result.average_travel_time == pytest.approx(
        65.0,
        abs=1e-5,
    )

    assert result.total_system_travel_time == pytest.approx(
        260000.0,
        abs=1e-2,
    )


def test_frank_wolfe_distributes_flow_equally_without_connector() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    result = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert result.flows[
        EdgeId("O", "A", 0)
    ] == pytest.approx(
        2000.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("A", "D", 0)
    ] == pytest.approx(
        2000.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("O", "B", 0)
    ] == pytest.approx(
        2000.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("B", "D", 0)
    ] == pytest.approx(
        2000.0,
        abs=1e-3,
    )


def test_frank_wolfe_converges_with_connector() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    result = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert result.converged
    assert result.relative_gap <= 1e-8

    assert result.average_travel_time == pytest.approx(
        80.0,
        abs=1e-5,
    )

    assert result.total_system_travel_time == pytest.approx(
        320000.0,
        abs=1e-2,
    )


def test_frank_wolfe_uses_connector() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    result = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert result.flows[
        EdgeId("O", "A", 0)
    ] == pytest.approx(
        4000.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("A", "B", 0)
    ] == pytest.approx(
        4000.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("B", "D", 0)
    ] == pytest.approx(
        4000.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("O", "B", 0)
    ] == pytest.approx(
        0.0,
        abs=1e-3,
    )

    assert result.flows[
        EdgeId("A", "D", 0)
    ] == pytest.approx(
        0.0,
        abs=1e-3,
    )


def test_connector_worsens_average_travel_time() -> None:
    graph_without = build_braess_network(
        include_connector=False,
    )

    graph_with = build_braess_network(
        include_connector=True,
    )

    result_without = frank_wolfe(
        graph_without,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    result_with = frank_wolfe(
        graph_with,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert (
        result_with.average_travel_time
        > result_without.average_travel_time
    )

    assert (
        result_with.average_travel_time
        - result_without.average_travel_time
    ) == pytest.approx(
        15.0,
        abs=1e-5,
    )


def test_frank_wolfe_records_iteration_history() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    result = frank_wolfe(
        graph,
        DEMAND,
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    assert result.history
    assert result.history[-1].relative_gap <= 1e-8

    assert all(
        0.0 <= iteration.step_size <= 1.0
        for iteration in result.history
    )


def test_frank_wolfe_rejects_empty_od_pairs() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    with pytest.raises(ValueError):
        frank_wolfe(
            graph,
            [],
        )


def test_frank_wolfe_rejects_invalid_tolerance() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    with pytest.raises(ValueError):
        frank_wolfe(
            graph,
            DEMAND,
            relative_gap_tolerance=0.0,
        )