from __future__ import annotations

import networkx as nx

from braess.costs import CostFunction, LinearCost
from braess.models import EdgeFlowMap, EdgeId


COST_FUNCTION_ATTRIBUTE = "cost_function"
TRAVEL_TIME_ATTRIBUTE = "travel_time"


def build_braess_network(
    *,
    include_connector: bool,
) -> nx.MultiDiGraph:
    """
    Constrói a rede sintética clássica do paradoxo de Braess.

    A rede contém os nós:

        O: origem
        A: nó intermediário superior
        B: nó intermediário inferior
        D: destino

    Funções de custo:

        O -> A: 45
        O -> B: 0,01x
        A -> D: 0,01x
        B -> D: 45
        A -> B: 0

    A conexão A -> B pode ser incluída ou removida para representar
    os dois cenários do experimento teórico.
    """
    graph = nx.MultiDiGraph()

    graph.add_nodes_from(["O", "A", "B", "D"])

    add_cost_edge(
        graph,
        u="O",
        v="A",
        key=0,
        cost_function=LinearCost(alpha=45.0, beta=0.0),
    )

    add_cost_edge(
        graph,
        u="O",
        v="B",
        key=0,
        cost_function=LinearCost(alpha=0.0, beta=0.01),
    )

    add_cost_edge(
        graph,
        u="A",
        v="D",
        key=0,
        cost_function=LinearCost(alpha=0.0, beta=0.01),
    )

    add_cost_edge(
        graph,
        u="B",
        v="D",
        key=0,
        cost_function=LinearCost(alpha=45.0, beta=0.0),
    )

    if include_connector:
        add_cost_edge(
            graph,
            u="A",
            v="B",
            key=0,
            cost_function=LinearCost(alpha=0.0, beta=0.0),
        )

    return graph


def add_cost_edge(
    graph: nx.MultiDiGraph,
    *,
    u: object,
    v: object,
    key: object,
    cost_function: CostFunction,
) -> None:
    """
    Adiciona uma aresta com uma função de custo associada.

    O tempo inicial é calculado com fluxo igual a zero.
    """
    graph.add_edge(
        u,
        v,
        key=key,
        cost_function=cost_function,
        travel_time=cost_function.travel_time(0.0),
    )


def create_zero_flows(
    graph: nx.MultiDiGraph,
) -> EdgeFlowMap:
    """
    Cria um mapa com fluxo zero para todas as arestas do grafo.
    """
    return {
        EdgeId(u=u, v=v, key=key): 0.0
        for u, v, key in graph.edges(keys=True)
    }


def update_travel_times(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
) -> None:
    """
    Atualiza o tempo de viagem das arestas usando os fluxos atuais.

    Para cada aresta:

        travel_time = cost_function.travel_time(flow)
    """
    for u, v, key, data in graph.edges(
        keys=True,
        data=True,
    ):
        edge_id = EdgeId(u=u, v=v, key=key)

        if edge_id not in flows:
            raise KeyError(
                f"O mapa de fluxos não possui a aresta {edge_id}."
            )

        flow = flows[edge_id]
        cost_function: CostFunction = data[
            COST_FUNCTION_ATTRIBUTE
        ]

        data[TRAVEL_TIME_ATTRIBUTE] = (
            cost_function.travel_time(flow)
        )