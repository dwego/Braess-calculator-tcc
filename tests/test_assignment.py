import braess.assignment as assignment_module
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

    assert auxiliary_flows[
        EdgeId("O", "A", 0)
    ] == pytest.approx(3000.0)

    assert auxiliary_flows[
        EdgeId("A", "B", 0)
    ] == pytest.approx(3500.0)

    assert auxiliary_flows[
        EdgeId("B", "D", 0)
    ] == pytest.approx(3500.0)

    assert auxiliary_flows[
        EdgeId("A", "D", 0)
    ] == pytest.approx(0.0)


def test_all_or_nothing_reuses_one_dijkstra_per_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    flows = create_zero_flows(graph)
    update_travel_times(graph, flows)

    original = assignment_module.shortest_edge_paths_to_target
    called_destinations: list[object] = []

    def counting_shortest_paths(
        graph,
        *,
        target,
        weight="travel_time",
    ):
        called_destinations.append(target)
        return original(
            graph,
            target=target,
            weight=weight,
        )

    monkeypatch.setattr(
        assignment_module,
        "shortest_edge_paths_to_target",
        counting_shortest_paths,
    )

    all_or_nothing_assignment(
        graph,
        [
            ODPair("O", "D", 3000.0),
            ODPair("A", "D", 500.0),
        ],
    )

    assert called_destinations == ["D"]
