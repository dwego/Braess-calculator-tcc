from __future__ import annotations

from collections.abc import Hashable

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

    A rede possui quatro nós:

        O: origem;
        A: nó intermediário superior;
        B: nó intermediário inferior;
        D: destino.

    As funções de custo são:

        O -> A: 0,01x
        O -> B: 45
        A -> D: 45
        B -> D: 0,01x
        A -> B: 0

    O parâmetro ``include_connector`` determina se a ligação A -> B
    será incluída.

    Sem a ligação A -> B, existem duas rotas principais:

        O -> A -> D
        O -> B -> D

    Com demanda total de 4000 veículos, o equilíbrio ocorre com
    aproximadamente 2000 veículos em cada rota, produzindo tempo
    médio de 65 minutos.

    Com a ligação A -> B, a rota:

        O -> A -> B -> D

    torna-se individualmente atrativa e produz tempo de 80 minutos
    quando recebe os 4000 veículos.

    Parameters
    ----------
    include_connector:
        Define se a ligação intermediária A -> B será adicionada.

    Returns
    -------
    nx.MultiDiGraph
        Rede sintética direcionada, preservando chaves de arestas.
    """
    graph = nx.MultiDiGraph()

    graph.add_nodes_from(
        [
            "O",
            "A",
            "B",
            "D",
        ]
    )

    add_cost_edge(
        graph,
        u="O",
        v="A",
        key=0,
        cost_function=LinearCost(
            alpha=0.0,
            beta=0.01,
        ),
    )

    add_cost_edge(
        graph,
        u="O",
        v="B",
        key=0,
        cost_function=LinearCost(
            alpha=45.0,
            beta=0.0,
        ),
    )

    add_cost_edge(
        graph,
        u="A",
        v="D",
        key=0,
        cost_function=LinearCost(
            alpha=45.0,
            beta=0.0,
        ),
    )

    add_cost_edge(
        graph,
        u="B",
        v="D",
        key=0,
        cost_function=LinearCost(
            alpha=0.0,
            beta=0.01,
        ),
    )

    if include_connector:
        add_cost_edge(
            graph,
            u="A",
            v="B",
            key=0,
            cost_function=LinearCost(
                alpha=0.0,
                beta=0.0,
            ),
        )

    return graph


def add_cost_edge(
    graph: nx.MultiDiGraph,
    *,
    u: Hashable,
    v: Hashable,
    key: Hashable,
    cost_function: CostFunction,
) -> None:
    """
    Adiciona uma aresta com uma função de custo associada.

    O atributo ``travel_time`` é inicializado usando fluxo zero.

    Parameters
    ----------
    graph:
        Multidígrafo que receberá a aresta.
    u:
        Nó de origem.
    v:
        Nó de destino.
    key:
        Chave da aresta no MultiDiGraph.
    cost_function:
        Função responsável pelo cálculo do tempo da aresta.
    """
    initial_travel_time = cost_function.travel_time(0.0)

    graph.add_edge(
        u,
        v,
        key=key,
        cost_function=cost_function,
        travel_time=initial_travel_time,
    )


def create_zero_flows(
    graph: nx.MultiDiGraph,
) -> EdgeFlowMap:
    """
    Cria um mapa de fluxo contendo valor zero para todas as arestas.

    Parameters
    ----------
    graph:
        Grafo cujas arestas serão incluídas no mapa.

    Returns
    -------
    EdgeFlowMap
        Dicionário que relaciona cada ``EdgeId`` ao fluxo zero.
    """
    return {
        EdgeId(
            u=u,
            v=v,
            key=key,
        ): 0.0
        for u, v, key in graph.edges(keys=True)
    }


def update_travel_times(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
) -> None:
    """
    Atualiza o tempo de viagem de todas as arestas.

    Para cada aresta ``e``, o tempo é calculado por:

        t_e = cost_function_e.travel_time(x_e)

    em que ``x_e`` é o fluxo atual da aresta.

    A função modifica o próprio grafo, atualizando o atributo
    ``travel_time``.

    Parameters
    ----------
    graph:
        Multidígrafo contendo as funções de custo.
    flows:
        Fluxos atuais, indexados pela identidade completa da aresta.

    Raises
    ------
    KeyError
        Caso o mapa de fluxos não contenha alguma aresta do grafo.
    TypeError
        Caso o atributo ``cost_function`` não implemente a interface
        esperada.
    """
    for u, v, key, data in graph.edges(
        keys=True,
        data=True,
    ):
        edge_id = EdgeId(
            u=u,
            v=v,
            key=key,
        )

        if edge_id not in flows:
            raise KeyError(
                f"O mapa de fluxos não contém a aresta {edge_id}."
            )

        cost_function = data.get(
            COST_FUNCTION_ATTRIBUTE
        )

        if cost_function is None:
            raise KeyError(
                f"A aresta {edge_id} não possui função de custo."
            )

        flow = flows[edge_id]

        data[TRAVEL_TIME_ATTRIBUTE] = (
            cost_function.travel_time(flow)
        )  