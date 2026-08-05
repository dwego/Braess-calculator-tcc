import networkx as nx
import pytest

from braess.models import EdgeId
from braess.routing import path_cost, shortest_edge_path
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
    assert set(graph.nodes) == {"O", "A", "B", "D"}
    assert graph.number_of_edges() == 4
    assert not graph.has_edge("A", "B")


def test_builds_braess_network_with_connector() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    assert graph.number_of_edges() == 5
    assert graph.has_edge("A", "B", 0)


def test_creates_zero_flow_for_every_edge() -> None:
    graph = build_braess_network(
        include_connector=True,
    )

    flows = create_zero_flows(graph)

    assert len(flows) == graph.number_of_edges()
    assert all(flow == 0.0 for flow in flows.values())


def test_updates_travel_times_from_flows() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)
    flows[EdgeId("O", "B", 0)] = 2000.0

    update_travel_times(graph, flows)

    assert graph["O"]["B"][0]["travel_time"] == pytest.approx(
        20.0
    )


def test_shortest_path_at_zero_flow() -> None:
    graph = build_braess_network(
        include_connector=False,
    )

    flows = create_zero_flows(graph)
    update_travel_times(graph, flows)

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
    assert path_cost(graph, path) == pytest.approx(45.0)


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

    assert path_cost(graph, path) == pytest.approx(15.0)


def test_shortest_path_raises_when_no_path_exists() -> None:
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(["O", "D"])

    with pytest.raises(nx.NetworkXNoPath):
        shortest_edge_path(
            graph,
            source="O",
            target="D",
        )