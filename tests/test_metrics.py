import pytest

from braess.metrics import (
    average_travel_time,
    beckmann_objective,
    relative_gap,
    total_system_travel_time,
)
from braess.models import EdgeId, ODPair
from braess.synthetic import (
    build_braess_network,
    create_zero_flows,
    update_travel_times,
)


def test_metrics_at_equilibrium_without_connector() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)

    flows[EdgeId("O", "A", 0)] = 2000.0
    flows[EdgeId("A", "D", 0)] = 2000.0

    flows[EdgeId("O", "B", 0)] = 2000.0
    flows[EdgeId("B", "D", 0)] = 2000.0

    update_travel_times(graph, flows)

    od_pairs = [
        ODPair("O", "D", 4000.0),
    ]

    assert total_system_travel_time(
        graph,
        flows,
    ) == pytest.approx(260000.0)

    assert average_travel_time(
        graph,
        flows,
        od_pairs,
    ) == pytest.approx(65.0)

    assert relative_gap(
        graph,
        flows,
        od_pairs,
    ) == pytest.approx(0.0)


def test_beckmann_objective_is_positive() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)

    flows[EdgeId("O", "A", 0)] = 2000.0
    flows[EdgeId("A", "D", 0)] = 2000.0

    flows[EdgeId("O", "B", 0)] = 2000.0
    flows[EdgeId("B", "D", 0)] = 2000.0

    objective = beckmann_objective(
        graph,
        flows,
    )

    assert objective > 0.0


def test_relative_gap_is_positive_away_from_equilibrium() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)

    flows[EdgeId("O", "A", 0)] = 4000.0
    flows[EdgeId("A", "D", 0)] = 4000.0

    update_travel_times(graph, flows)

    gap = relative_gap(
        graph,
        flows,
        [ODPair("O", "D", 4000.0)],
    )

    assert gap > 0.0