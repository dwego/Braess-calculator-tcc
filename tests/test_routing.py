import networkx as nx
import pytest

from braess.models import EdgeId
from braess.routing import (
    path_cost,
    shortest_edge_path,
)
from braess.synthetic import (
    build_braess_network,
    create_zero_flows,
    update_travel_times,
)


def test_builds_braess_network_without_connector() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    assert isinstance(graph, nx.MultiDiGraph)

    assert set(graph.nodes) == {
        "O",
        "A",
        "B",
        "D",
    }

    assert graph.number_of_edges() == 4

    assert graph.has_edge("O", "A", 0)
    assert graph.has_edge("O", "B", 0)
    assert graph.has_edge("A", "D", 0)
    assert graph.has_edge("B", "D", 0)

    assert not graph.has_edge("A", "B")


def test_builds_braess_network_with_connector() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.number_of_edges() == 5
    assert graph.has_edge("A", "B", 0)


def test_creates_zero_flow_for_every_edge() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    flows = create_zero_flows(graph)

    assert len(flows) == graph.number_of_edges()

    assert set(flows) == {
        EdgeId("O", "A", 0),
        EdgeId("O", "B", 0),
        EdgeId("A", "D", 0),
        EdgeId("A", "B", 0),
        EdgeId("B", "D", 0),
    }

    assert all(
        flow == 0.0
        for flow in flows.values()
    )


def test_updates_travel_times_from_flows() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)

    flows[
        EdgeId("O", "A", 0)
    ] = 2000.0

    flows[
        EdgeId("B", "D", 0)
    ] = 2000.0

    update_travel_times(
        graph,
        flows,
    )

    assert graph["O"]["A"][0][
        "travel_time"
    ] == pytest.approx(20.0)

    assert graph["B"]["D"][0][
        "travel_time"
    ] == pytest.approx(20.0)

    assert graph["O"]["B"][0][
        "travel_time"
    ] == pytest.approx(45.0)

    assert graph["A"]["D"][0][
        "travel_time"
    ] == pytest.approx(45.0)


def test_shortest_path_at_zero_flow() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)

    update_travel_times(
        graph,
        flows,
    )

    path = shortest_edge_path(
        graph,
        source="O",
        target="D",
    )

    valid_paths = [
        [
            EdgeId("O", "A", 0),
            EdgeId("A", "D", 0),
        ],
        [
            EdgeId("O", "B", 0),
            EdgeId("B", "D", 0),
        ],
    ]

    assert path in valid_paths

    assert path_cost(
        graph,
        path,
    ) == pytest.approx(45.0)


def test_shortest_path_with_connector_at_zero_flow() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    flows = create_zero_flows(graph)

    update_travel_times(
        graph,
        flows,
    )

    path = shortest_edge_path(
        graph,
        source="O",
        target="D",
    )

    assert path == [
        EdgeId("O", "A", 0),
        EdgeId("A", "B", 0),
        EdgeId("B", "D", 0),
    ]

    assert path_cost(
        graph,
        path,
    ) == pytest.approx(0.0)


def test_shortest_path_changes_after_flow_update() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)

    flows[
        EdgeId("O", "A", 0)
    ] = 4000.0

    flows[
        EdgeId("A", "D", 0)
    ] = 4000.0

    update_travel_times(
        graph,
        flows,
    )

    path = shortest_edge_path(
        graph,
        source="O",
        target="D",
    )

    assert path == [
        EdgeId("O", "B", 0),
        EdgeId("B", "D", 0),
    ]

    assert path_cost(
        graph,
        path,
    ) == pytest.approx(45.0)


def test_shortest_path_preserves_parallel_edge_key() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        "O",
        "A",
        key=0,
        travel_time=20.0,
    )

    graph.add_edge(
        "O",
        "A",
        key=1,
        travel_time=10.0,
    )

    graph.add_edge(
        "A",
        "D",
        key=0,
        travel_time=5.0,
    )

    path = shortest_edge_path(
        graph,
        source="O",
        target="D",
    )

    assert path == [
        EdgeId("O", "A", 1),
        EdgeId("A", "D", 0),
    ]

    assert path_cost(
        graph,
        path,
    ) == pytest.approx(15.0)


def test_shortest_path_parallel_edge_tie_is_deterministic() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        "O",
        "A",
        key=1,
        travel_time=10.0,
    )

    graph.add_edge(
        "O",
        "A",
        key=0,
        travel_time=10.0,
    )

    graph.add_edge(
        "A",
        "D",
        key=0,
        travel_time=5.0,
    )

    path = shortest_edge_path(
        graph,
        source="O",
        target="D",
    )

    assert path == [
        EdgeId("O", "A", 0),
        EdgeId("A", "D", 0),
    ]


def test_path_cost_rejects_missing_edge() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        "O",
        "A",
        key=0,
        travel_time=10.0,
    )

    path = [
        EdgeId("O", "D", 0),
    ]

    with pytest.raises(KeyError):
        path_cost(
            graph,
            path,
        )


def test_path_cost_rejects_non_numeric_weight() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        "O",
        "D",
        key=0,
        travel_time="invalid",
    )

    path = [
        EdgeId("O", "D", 0),
    ]

    with pytest.raises(ValueError):
        path_cost(
            graph,
            path,
        )


def test_shortest_path_raises_when_no_path_exists() -> None:
    graph = nx.MultiDiGraph()

    graph.add_nodes_from(
        [
            "O",
            "D",
        ]
    )

    with pytest.raises(nx.NetworkXNoPath):
        shortest_edge_path(
            graph,
            source="O",
            target="D",
        )


def test_shortest_path_raises_when_node_does_not_exist() -> None:
    graph = nx.MultiDiGraph()

    graph.add_node("O")

    with pytest.raises(nx.NodeNotFound):
        shortest_edge_path(
            graph,
            source="O",
            target="D",
        )