from __future__ import annotations

from collections.abc import Hashable

import networkx as nx

from braess.models import EdgeId


def shortest_edge_path(
    graph: nx.MultiDiGraph,
    *,
    source: Hashable,
    target: Hashable,
    weight: str = "travel_time",
) -> list[EdgeId]:
    """
    Calcula o menor caminho e preserva a chave das arestas.

    O NetworkX normalmente retorna uma sequência de nós:

        ["O", "A", "D"]

    Em um MultiDiGraph, isso não é suficiente porque podem existir várias
    arestas entre O e A. Por isso, esta função converte a sequência de nós
    em uma sequência de EdgeId:

        [
            EdgeId("O", "A", 0),
            EdgeId("A", "D", 0),
        ]

    Parameters
    ----------
    graph:
        Multidígrafo no qual o caminho será calculado.
    source:
        Nó de origem.
    target:
        Nó de destino.
    weight:
        Nome do atributo utilizado como custo.

    Returns
    -------
    list[EdgeId]
        Arestas que formam o menor caminho.

    Raises
    ------
    nx.NodeNotFound
        Caso a origem ou o destino não exista.
    nx.NetworkXNoPath
        Caso não exista caminho entre os nós.
    ValueError
        Caso uma aresta não possua peso válido.
    """
    node_path = nx.shortest_path(
        graph,
        source=source,
        target=target,
        weight=weight,
        method="dijkstra",
    )

    edge_path: list[EdgeId] = []

    for u, v in zip(node_path, node_path[1:]):
        key = _select_lowest_cost_edge_key(
            graph,
            u=u,
            v=v,
            weight=weight,
        )

        edge_path.append(
            EdgeId(
                u=u,
                v=v,
                key=key,
            )
        )

    return edge_path


def path_cost(
    graph: nx.MultiDiGraph,
    path: list[EdgeId],
    *,
    weight: str = "travel_time",
) -> float:
    """
    Soma o custo das arestas de um caminho.
    """
    total = 0.0

    for edge in path:
        data = graph.get_edge_data(
            edge.u,
            edge.v,
            edge.key,
        )

        if data is None:
            raise KeyError(
                f"A aresta {edge} não existe no grafo."
            )

        edge_weight = data.get(weight)

        if not isinstance(edge_weight, int | float):
            raise ValueError(
                f"A aresta {edge} não possui peso numérico "
                f"no atributo {weight!r}."
            )

        total += float(edge_weight)

    return total


def _select_lowest_cost_edge_key(
    graph: nx.MultiDiGraph,
    *,
    u: Hashable,
    v: Hashable,
    weight: str,
) -> Hashable:
    """
    Seleciona a chave da aresta paralela de menor custo entre u e v.

    Em caso de empate, escolhe a menor chave segundo sua representação
    textual. Isso mantém o resultado determinístico.
    """
    parallel_edges = graph.get_edge_data(u, v)

    if not parallel_edges:
        raise KeyError(
            f"Não existem arestas entre {u!r} e {v!r}."
        )

    candidates: list[tuple[float, str, Hashable]] = []

    for key, data in parallel_edges.items():
        edge_weight = data.get(weight)

        if not isinstance(edge_weight, int | float):
            raise ValueError(
                f"A aresta ({u!r}, {v!r}, {key!r}) "
                f"não possui peso numérico."
            )

        candidates.append(
            (
                float(edge_weight),
                repr(key),
                key,
            )
        )

    _, _, selected_key = min(candidates)

    return selected_key