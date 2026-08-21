from __future__ import annotations

from collections import defaultdict

import networkx as nx

from braess.models import EdgeFlowMap, EdgeId, ODPair
from braess.routing import shortest_edge_paths_to_target
from braess.synthetic import create_zero_flows


def all_or_nothing_assignment(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    *,
    weight: str = "travel_time",
) -> EdgeFlowMap:
    """
    Executa a atribuição All-or-Nothing.

    Os pares OD são agrupados por destino. Para cada destino distinto,
    executa-se um único Dijkstra no grafo invertido, produzindo os menores
    caminhos de todas as origens alcançáveis até esse destino no grafo
    original.

    Em seguida, toda a demanda de cada par OD é atribuída ao respectivo
    caminho mínimo e os fluxos são acumulados nas arestas utilizadas.
    """
    auxiliary_flows = create_zero_flows(graph)

    pairs_by_destination: dict[
        object,
        list[ODPair],
    ] = defaultdict(list)

    for od_pair in od_pairs:
        pairs_by_destination[
            od_pair.destination
        ].append(od_pair)

    for destination, destination_pairs in pairs_by_destination.items():
        paths_to_destination = shortest_edge_paths_to_target(
            graph,
            target=destination,
            weight=weight,
        )

        for od_pair in destination_pairs:
            path = paths_to_destination.get(
                od_pair.origin
            )

            if path is None:
                raise nx.NetworkXNoPath(
                    "Não existe caminho entre a origem "
                    f"{od_pair.origin!r} e o destino "
                    f"{od_pair.destination!r}."
                )

            for edge in path:
                auxiliary_flows[edge] += od_pair.demand

    return auxiliary_flows


def total_assigned_flow_from_origin(
    flows: EdgeFlowMap,
    origin: object,
) -> float:
    """
    Soma o fluxo das arestas que saem de uma origem.

    Essa função é útil para testes simples de conservação da demanda.
    """
    return sum(
        flow
        for edge, flow in flows.items()
        if edge.u == origin
    )
