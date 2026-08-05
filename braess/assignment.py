from __future__ import annotations

import networkx as nx

from braess.models import EdgeFlowMap, EdgeId, ODPair
from braess.routing import shortest_edge_path
from braess.synthetic import create_zero_flows


def all_or_nothing_assignment(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    *,
    weight: str = "travel_time",
) -> EdgeFlowMap:
    """
    Executa a atribuição All-or-Nothing.

    Para cada par origem-destino:

    1. calcula a rota de menor custo;
    2. atribui toda a demanda desse par à rota encontrada;
    3. acumula os fluxos nas arestas utilizadas.

    O resultado é um vetor auxiliar de fluxos, utilizado pelo
    algoritmo de Frank-Wolfe.

    Parameters
    ----------
    graph:
        Rede direcionada com os custos atuais nas arestas.
    od_pairs:
        Demandas origem-destino.
    weight:
        Nome do atributo usado como peso no menor caminho.

    Returns
    -------
    EdgeFlowMap
        Fluxo auxiliar atribuído a cada aresta.

    Raises
    ------
    nx.NodeNotFound
        Caso algum nó de origem ou destino não exista.
    nx.NetworkXNoPath
        Caso não exista caminho para algum par OD.
    """
    auxiliary_flows = create_zero_flows(graph)

    for od_pair in od_pairs:
        path = shortest_edge_path(
            graph,
            source=od_pair.origin,
            target=od_pair.destination,
            weight=weight,
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