from __future__ import annotations

import math

import networkx as nx

from braess.models import EdgeFlowMap, EdgeId, ODPair
from braess.routing import path_cost, shortest_edge_path
from braess.synthetic import COST_FUNCTION_ATTRIBUTE


def total_system_travel_time(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
) -> float:
    """
    Calcula o tempo total de viagem do sistema.

    A métrica é definida por:

        TSTT = soma de x_e * t_e(x_e)

    em que:

    - x_e é o fluxo da aresta;
    - t_e(x_e) é o tempo atual da aresta.

    O resultado representa a soma dos tempos enfrentados por todos
    os veículos da rede.
    """
    total = 0.0

    for edge, flow in flows.items():
        if flow < 0:
            raise ValueError(
                f"A aresta {edge} possui fluxo negativo."
            )

        data = graph.get_edge_data(
            edge.u,
            edge.v,
            edge.key,
        )

        if data is None:
            raise KeyError(
                f"A aresta {edge} não existe no grafo."
            )

        travel_time = data.get("travel_time")

        if not isinstance(travel_time, int | float):
            raise ValueError(
                f"A aresta {edge} não possui tempo numérico."
            )

        total += flow * float(travel_time)

    if not math.isfinite(total):
        raise ValueError(
            "O tempo total do sistema não é finito."
        )

    return total


def average_travel_time(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
    od_pairs: list[ODPair],
) -> float:
    """
    Calcula o tempo médio por veículo.

        tempo médio = TSTT / demanda total
    """
    total_demand = sum(
        od_pair.demand
        for od_pair in od_pairs
    )

    if total_demand <= 0:
        raise ValueError(
            "A demanda total deve ser maior que zero."
        )

    return (
        total_system_travel_time(graph, flows)
        / total_demand
    )


def beckmann_objective(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
) -> float:
    """
    Calcula a função objetivo de Beckmann.

        Z(x) = soma das integrais de 0 até x_e de t_e(w) dw

    Essa é a função minimizada pelo algoritmo de Frank-Wolfe.
    """
    objective = 0.0

    for edge, flow in flows.items():
        data = graph.get_edge_data(
            edge.u,
            edge.v,
            edge.key,
        )

        if data is None:
            raise KeyError(
                f"A aresta {edge} não existe no grafo."
            )

        cost_function = data[COST_FUNCTION_ATTRIBUTE]

        objective += cost_function.integral(flow)

    if not math.isfinite(objective):
        raise ValueError(
            "O objetivo de Beckmann não é finito."
        )

    return objective


def shortest_path_total_travel_time(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
) -> float:
    """
    Calcula o custo total caso cada demanda utilize seu menor caminho
    sob os custos atuais.

        SPTT = soma de q_od * pi_od

    em que pi_od é o custo do menor caminho do par OD.
    """
    total = 0.0

    for od_pair in od_pairs:
        path = shortest_edge_path(
            graph,
            source=od_pair.origin,
            target=od_pair.destination,
        )

        total += (
            od_pair.demand
            * path_cost(graph, path)
        )

    return total


def relative_gap(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
    od_pairs: list[ODPair],
) -> float:
    """
    Calcula a lacuna relativa do equilíbrio.

        RG = (TSTT - SPTT) / TSTT

    Um valor próximo de zero indica que os veículos já não possuem
    uma alternativa coletiva de menor custo significativa sob os
    tempos atuais.
    """
    tstt = total_system_travel_time(
        graph,
        flows,
    )

    if tstt <= 0:
        raise ValueError(
            "O TSTT deve ser positivo para calcular a lacuna."
        )

    shortest_total = shortest_path_total_travel_time(
        graph,
        od_pairs,
    )

    gap = (tstt - shortest_total) / tstt

    # Pequenos valores negativos podem surgir por arredondamento.
    if gap < 0 and abs(gap) < 1e-12:
        return 0.0

    if gap < 0:
        raise ValueError(
            "A lacuna relativa calculada foi negativa."
        )

    return gap