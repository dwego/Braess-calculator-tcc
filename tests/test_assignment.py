import pytest

from braess.assignment import (
    all_or_nothing_assignment,
    total_assigned_flow_from_origin,
)
from braess.models import EdgeId, ODPair
from braess.synthetic import (
    build_braess_network,
    create_zero_flows,
    update_travel_times,
)


def test_all_or_nothing_assigns_entire_demand() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)
    update_travel_times(graph, flows)

    od_pairs = [
        ODPair(
            origin="O",
            destination="D",
            demand=4000.0,
        )
    ]

    auxiliary_flows = all_or_nothing_assignment(
        graph,
        od_pairs,
    )

    assert total_assigned_flow_from_origin(
        auxiliary_flows,
        "O",
    ) == pytest.approx(4000.0)


def test_all_or_nothing_uses_only_one_shortest_path() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)
    update_travel_times(graph, flows)

    auxiliary_flows = all_or_nothing_assignment(
        graph,
        [
            ODPair(
                origin="O",
                destination="D",
                demand=4000.0,
            )
        ],
    )

    upper_path_flow = auxiliary_flows[
        EdgeId("O", "A", 0)
    ]

    lower_path_flow = auxiliary_flows[
        EdgeId("O", "B", 0)
    ]

    assert sorted(
        [upper_path_flow, lower_path_flow]
    ) == [0.0, 4000.0]


def test_all_or_nothing_accumulates_multiple_od_pairs() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    flows = create_zero_flows(graph)
    update_travel_times(graph, flows)

    auxiliary_flows = all_or_nothing_assignment(
        graph,
        [
            ODPair("O", "D", 3000.0),
            ODPair("A", "D", 500.0),
        ],
    )

    assert sum(auxiliary_flows.values()) > 0.0
    assert auxiliary_flows[
        EdgeId("A", "D", 0)
    ] >= 500.0