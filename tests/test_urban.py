import networkx as nx
import pytest

from braess.costs import BPRCost
from braess.models import EdgeId
from braess.synthetic import (
    COST_FUNCTION_ATTRIBUTE,
    TRAVEL_TIME_ATTRIBUTE,
)
from braess.urban import (
    CAPACITY_ATTRIBUTE,
    CAPACITY_SOURCE_ATTRIBUTE,
    FREE_FLOW_TIME_ATTRIBUTE,
    HIGHWAY_NORMALIZED_ATTRIBUTE,
    LANES_NORMALIZED_ATTRIBUTE,
    create_urban_zero_flows,
    normalize_highway,
    normalize_lanes,
    prepare_urban_graph,
)


CAPACITY_RULES = {
    "primary": 1600.0,
    "secondary": 1400.0,
    "residential": 900.0,
}


def build_test_graph() -> nx.MultiDiGraph:
    """
    Cria uma rede urbana mínima para os testes.

    Os valores de capacidade utilizados aqui são apenas dados de teste.
    Eles não representam ainda os parâmetros finais da pesquisa.
    """
    graph = nx.MultiDiGraph()

    graph.add_edge(
        1,
        2,
        key=0,
        highway="primary",
        lanes="2",
        length=500.0,
        speed_kph=50.0,
        travel_time=36.0,
    )

    graph.add_edge(
        2,
        3,
        key=0,
        highway="residential",
        lanes=None,
        length=250.0,
        speed_kph=30.0,
        travel_time=30.0,
    )

    return graph


def test_normalize_highway_from_string() -> None:
    assert normalize_highway(
        "Primary"
    ) == "primary"


def test_normalize_highway_from_list() -> None:
    assert normalize_highway(
        ["secondary", "residential"]
    ) == "secondary"


def test_normalize_highway_rejects_missing_value() -> None:
    with pytest.raises(ValueError):
        normalize_highway(None)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (2, 2),
        (2.0, 2),
        ("2", 2),
        ("2;3", 3),
        (["1", "2"], 2),
        (None, 1),
        ("invalid", 1),
    ],
)
def test_normalize_lanes(
    raw_value: object,
    expected: int,
) -> None:
    assert normalize_lanes(
        raw_value,
        default=1,
    ) == expected


def test_prepare_urban_graph_preserves_multidigraph() -> None:
    original = build_test_graph()

    prepared = prepare_urban_graph(
        original,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=800.0,
    )

    assert isinstance(prepared, nx.MultiDiGraph)
    assert prepared.number_of_edges() == 2


def test_prepare_urban_graph_does_not_modify_original_by_default() -> None:
    original = build_test_graph()

    prepared = prepare_urban_graph(
        original,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=800.0,
    )

    assert COST_FUNCTION_ATTRIBUTE not in (
        original[1][2][0]
    )

    assert COST_FUNCTION_ATTRIBUTE in (
        prepared[1][2][0]
    )


def test_prepare_urban_graph_copies_free_flow_time() -> None:
    graph = build_test_graph()

    prepared = prepare_urban_graph(
        graph,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=800.0,
    )

    data = prepared[1][2][0]

    assert data[
        FREE_FLOW_TIME_ATTRIBUTE
    ] == pytest.approx(36.0)

    assert data[
        TRAVEL_TIME_ATTRIBUTE
    ] == pytest.approx(36.0)


def test_prepare_urban_graph_estimates_capacity() -> None:
    graph = build_test_graph()

    prepared = prepare_urban_graph(
        graph,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=800.0,
    )

    primary_data = prepared[1][2][0]

    # 1600 veículos/hora/faixa × 2 faixas.
    assert primary_data[
        CAPACITY_ATTRIBUTE
    ] == pytest.approx(3200.0)

    assert primary_data[
        CAPACITY_SOURCE_ATTRIBUTE
    ] == "highway:primary"

    residential_data = prepared[2][3][0]

    # Como lanes está ausente, usa uma faixa.
    assert residential_data[
        CAPACITY_ATTRIBUTE
    ] == pytest.approx(900.0)


def test_prepare_urban_graph_normalizes_attributes() -> None:
    graph = build_test_graph()

    prepared = prepare_urban_graph(
        graph,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=800.0,
    )

    data = prepared[1][2][0]

    assert data[
        HIGHWAY_NORMALIZED_ATTRIBUTE
    ] == "primary"

    assert data[
        LANES_NORMALIZED_ATTRIBUTE
    ] == 2


def test_prepare_urban_graph_adds_bpr_cost() -> None:
    graph = build_test_graph()

    prepared = prepare_urban_graph(
        graph,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=800.0,
    )

    cost = prepared[1][2][0][
        COST_FUNCTION_ATTRIBUTE
    ]

    assert isinstance(cost, BPRCost)

    assert cost.free_flow_time == pytest.approx(
        36.0
    )

    assert cost.capacity == pytest.approx(
        3200.0
    )

    assert cost.travel_time(0.0) == pytest.approx(
        36.0
    )

    assert cost.travel_time(3200.0) > 36.0


def test_create_urban_zero_flows_includes_edge_keys() -> None:
    graph = build_test_graph()

    flows = create_urban_zero_flows(graph)

    assert flows == {
        EdgeId(1, 2, 0): 0.0,
        EdgeId(2, 3, 0): 0.0,
    }


def test_prepare_urban_graph_uses_default_capacity_rule() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        1,
        2,
        key=0,
        highway="unclassified",
        lanes=2,
        travel_time=15.0,
    )

    prepared = prepare_urban_graph(
        graph,
        capacity_per_lane=CAPACITY_RULES,
        default_capacity_per_lane=700.0,
    )

    data = prepared[1][2][0]

    assert data[
        CAPACITY_ATTRIBUTE
    ] == pytest.approx(1400.0)

    assert data[
        CAPACITY_SOURCE_ATTRIBUTE
    ] == "default"


def test_prepare_urban_graph_rejects_digraph() -> None:
    graph = nx.DiGraph()

    with pytest.raises(TypeError):
        prepare_urban_graph(
            graph,  # type: ignore[arg-type]
            capacity_per_lane=CAPACITY_RULES,
            default_capacity_per_lane=800.0,
        )


def test_prepare_urban_graph_rejects_missing_travel_time() -> None:
    graph = nx.MultiDiGraph()

    graph.add_edge(
        1,
        2,
        key=0,
        highway="primary",
        lanes=1,
    )

    with pytest.raises(ValueError):
        prepare_urban_graph(
            graph,
            capacity_per_lane=CAPACITY_RULES,
            default_capacity_per_lane=800.0,
        )