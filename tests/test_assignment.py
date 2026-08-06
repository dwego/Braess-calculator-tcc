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

    # O par O -> D usa:
    #
    # O -> A -> B -> D
    #
    # Portanto, 3000 veículos passam por O -> A.
    assert auxiliary_flows[
        EdgeId("O", "A", 0)
    ] == pytest.approx(3000.0)

    # A aresta A -> B recebe:
    #
    # 3000 veículos do par O -> D
    #  500 veículos do par A -> D
    #
    # Total: 3500 veículos.
    assert auxiliary_flows[
        EdgeId("A", "B", 0)
    ] == pytest.approx(3500.0)

    # Os dois pares terminam usando B -> D.
    assert auxiliary_flows[
        EdgeId("B", "D", 0)
    ] == pytest.approx(3500.0)

    # A ligação direta A -> D custa 45, enquanto A -> B -> D
    # custa zero no estado inicial. Portanto, ela não recebe fluxo.
    assert auxiliary_flows[
        EdgeId("A", "D", 0)
    ] == pytest.approx(0.0)