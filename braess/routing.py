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
    Calcula o menor caminho entre uma origem e um destino.

    A busca usa Dijkstra e o caminho de nós retornado pelo NetworkX é
    convertido em uma sequência de EdgeId para preservar a chave das
    arestas paralelas do MultiDiGraph.
    """
    node_path = nx.shortest_path(
        graph,
        source=source,
        target=target,
        weight=weight,
        method="dijkstra",
    )

    return _node_path_to_edge_path(
        graph,
        node_path,
        weight=weight,
    )


def shortest_edge_paths_to_target(
    graph: nx.MultiDiGraph,
    *,
    target: Hashable,
    weight: str = "travel_time",
) -> dict[Hashable, list[EdgeId]]:
    """
    Calcula, com um único Dijkstra, os menores caminhos até um destino.

    O grafo é visto com as arestas invertidas e o Dijkstra parte do
    destino. Assim, uma única árvore de menores caminhos fornece a rota
    de cada origem alcançável até ``target`` no grafo original.

    Essa abordagem é útil quando vários pares OD compartilham o mesmo
    destino, pois evita executar um Dijkstra independente para cada origem.
    """
    if target not in graph:
        raise nx.NodeNotFound(
            f"O destino {target!r} não existe no grafo."
        )

    reversed_graph = graph.reverse(copy=False)

    reversed_node_paths = nx.single_source_dijkstra_path(
        reversed_graph,
        source=target,
        weight=weight,
    )

    paths_to_target: dict[
        Hashable,
        list[EdgeId],
    ] = {}

    for source, reversed_node_path in reversed_node_paths.items():
        node_path = list(reversed(reversed_node_path))

        paths_to_target[source] = _node_path_to_edge_path(
            graph,
            node_path,
            weight=weight,
        )

    return paths_to_target


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


def _node_path_to_edge_path(
    graph: nx.MultiDiGraph,
    node_path: list[Hashable],
    *,
    weight: str,
) -> list[EdgeId]:
    """
    Converte uma sequência de nós em arestas do MultiDiGraph.
    """
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
