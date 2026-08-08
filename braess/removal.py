from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

import networkx as nx

from braess.frank_wolfe import (
    FrankWolfeIteration,
    FrankWolfeResult,
    frank_wolfe,
)
from braess.models import EdgeId, ODPair


@dataclass(frozen=True, slots=True)
class RemovalCandidate:
    """
    Representa uma aresta candidata à remoção.

    Attributes
    ----------
    edge:
        Identificador completo da aresta no MultiDiGraph.
    baseline_flow:
        Fluxo da aresta no equilíbrio do cenário-base.
    name:
        Nome da via, quando disponível.
    highway:
        Classificação da via no OpenStreetMap.
    """

    edge: EdgeId
    baseline_flow: float
    name: str
    highway: str


@dataclass(frozen=True, slots=True)
class RemovalResult:
    """
    Resultado do experimento de remoção de uma aresta.

    Attributes
    ----------
    candidate:
        Aresta removida.
    connected:
        Indica se todos os pares OD permaneceram conectados.
    solver_result:
        Resultado do Frank-Wolfe após a remoção.
    error:
        Descrição do erro, caso o cenário não possa ser concluído.
    baseline_tstt:
        Tempo total de viagem do cenário-base.
    modified_tstt:
        Tempo total após a remoção.
    absolute_improvement:
        Diferença absoluta entre os dois TSTTs.
    relative_improvement:
        Melhoria relativa em relação ao cenário-base.
    possible_braess:
        Indica uma possível manifestação do paradoxo no modelo.
    """

    candidate: RemovalCandidate
    connected: bool
    solver_result: FrankWolfeResult | None
    error: str | None

    baseline_tstt: float
    modified_tstt: float | None

    absolute_improvement: float | None
    relative_improvement: float | None

    possible_braess: bool


ScenarioProgressCallback = Callable[
    [int, int, RemovalCandidate],
    None,
]

SolverProgressFactory = Callable[
    [RemovalCandidate],
    Callable[[FrankWolfeIteration], None] | None,
]


def select_removal_candidates(
    graph: nx.MultiDiGraph,
    baseline_result: FrankWolfeResult,
    *,
    limit: int = 10,
    minimum_flow: float = 1e-8,
    excluded_highway_types: set[str] | None = None,
) -> list[RemovalCandidate]:
    """
    Seleciona as arestas de maior fluxo no cenário-base.

    Somente arestas com fluxo acima de ``minimum_flow`` são consideradas.
    As candidatas são ordenadas do maior para o menor fluxo.

    Parameters
    ----------
    graph:
        Rede utilizada no cenário-base.
    baseline_result:
        Resultado do equilíbrio da rede original.
    limit:
        Quantidade máxima de candidatas.
    minimum_flow:
        Fluxo mínimo para uma aresta ser considerada.
    excluded_highway_types:
        Classificações viárias que não devem ser testadas.

    Returns
    -------
    list[RemovalCandidate]
        Lista ordenada de candidatas.
    """
    if limit <= 0:
        raise ValueError(
            "O limite de candidatas deve ser maior que zero."
        )

    if minimum_flow < 0.0:
        raise ValueError(
            "O fluxo mínimo não pode ser negativo."
        )

    excluded = excluded_highway_types or set()

    candidates: list[RemovalCandidate] = []

    for edge, flow in baseline_result.flows.items():
        if flow <= minimum_flow:
            continue

        edge_data = graph.get_edge_data(
            edge.u,
            edge.v,
            edge.key,
        )

        if edge_data is None:
            raise KeyError(
                f"A aresta {edge} não existe no grafo."
            )

        highway = _normalize_text_attribute(
            edge_data.get(
                "highway_normalized",
                edge_data.get("highway"),
            )
        )

        if highway in excluded:
            continue

        name = _normalize_text_attribute(
            edge_data.get("name")
        )

        candidates.append(
            RemovalCandidate(
                edge=edge,
                baseline_flow=float(flow),
                name=name,
                highway=highway,
            )
        )

    candidates.sort(
        key=lambda candidate: candidate.baseline_flow,
        reverse=True,
    )

    return candidates[:limit]


def run_single_removal(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    baseline_result: FrankWolfeResult,
    candidate: RemovalCandidate,
    *,
    relative_gap_tolerance: float,
    max_iterations: int,
    numerical_tolerance: float = 1e-9,
    progress_callback: (
        Callable[[FrankWolfeIteration], None] | None
    ) = None,
) -> RemovalResult:
    """
    Remove uma aresta e recalcula o equilíbrio da rede.

    A rede original não é modificada. Uma cópia independente é criada
    antes da remoção.

    Uma possível manifestação do paradoxo é identificada quando:

    - os dois cenários convergem;
    - a demanda permanece conectada;
    - o TSTT da rede modificada é menor;
    - a diferença supera a tolerância numérica.
    """
    if numerical_tolerance < 0.0:
        raise ValueError(
            "A tolerância numérica não pode ser negativa."
        )

    modified_graph = deepcopy(graph)

    edge = candidate.edge

    if not modified_graph.has_edge(
        edge.u,
        edge.v,
        edge.key,
    ):
        return _failed_result(
            candidate=candidate,
            baseline_result=baseline_result,
            connected=False,
            error=(
                f"A aresta {edge} não existe no grafo."
            ),
        )

    modified_graph.remove_edge(
        edge.u,
        edge.v,
        edge.key,
    )

    if not all_od_pairs_are_connected(
        modified_graph,
        od_pairs,
    ):
        return _failed_result(
            candidate=candidate,
            baseline_result=baseline_result,
            connected=False,
            error=(
                "A remoção desconectou ao menos "
                "um par origem-destino."
            ),
        )

    try:
        modified_result = frank_wolfe(
            modified_graph,
            od_pairs,
            relative_gap_tolerance=(
                relative_gap_tolerance
            ),
            max_iterations=max_iterations,
            progress_callback=progress_callback,
        )
    except Exception as exception:
        return _failed_result(
            candidate=candidate,
            baseline_result=baseline_result,
            connected=True,
            error=(
                f"{type(exception).__name__}: "
                f"{exception}"
            ),
        )

    baseline_tstt = (
        baseline_result.total_system_travel_time
    )

    modified_tstt = (
        modified_result.total_system_travel_time
    )

    absolute_improvement = (
        baseline_tstt - modified_tstt
    )

    relative_improvement = (
        absolute_improvement / baseline_tstt
    )

    possible_braess = (
        baseline_result.converged
        and modified_result.converged
        and absolute_improvement
        > numerical_tolerance
    )

    return RemovalResult(
        candidate=candidate,
        connected=True,
        solver_result=modified_result,
        error=None,
        baseline_tstt=baseline_tstt,
        modified_tstt=modified_tstt,
        absolute_improvement=absolute_improvement,
        relative_improvement=relative_improvement,
        possible_braess=possible_braess,
    )


def run_removal_experiments(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    baseline_result: FrankWolfeResult,
    candidates: list[RemovalCandidate],
    *,
    relative_gap_tolerance: float,
    max_iterations: int,
    numerical_tolerance: float = 1e-9,
    scenario_progress_callback: (
        ScenarioProgressCallback | None
    ) = None,
    solver_progress_factory: (
        SolverProgressFactory | None
    ) = None,
) -> list[RemovalResult]:
    """
    Executa o experimento para todas as candidatas.

    Cada remoção utiliza uma cópia nova do grafo original.
    """
    results: list[RemovalResult] = []

    total_candidates = len(candidates)

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        if scenario_progress_callback is not None:
            scenario_progress_callback(
                index,
                total_candidates,
                candidate,
            )

        progress_callback = None

        if solver_progress_factory is not None:
            progress_callback = (
                solver_progress_factory(candidate)
            )

        result = run_single_removal(
            graph,
            od_pairs,
            baseline_result,
            candidate,
            relative_gap_tolerance=(
                relative_gap_tolerance
            ),
            max_iterations=max_iterations,
            numerical_tolerance=(
                numerical_tolerance
            ),
            progress_callback=progress_callback,
        )

        results.append(result)

    return results


def all_od_pairs_are_connected(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
) -> bool:
    """
    Verifica se todos os pares OD continuam conectados.
    """
    for od_pair in od_pairs:
        if od_pair.origin not in graph:
            return False

        if od_pair.destination not in graph:
            return False

        if not nx.has_path(
            graph,
            od_pair.origin,
            od_pair.destination,
        ):
            return False

    return True


def sort_removal_results(
    results: list[RemovalResult],
) -> list[RemovalResult]:
    """
    Ordena os resultados pela maior melhoria relativa.

    Cenários inválidos ficam no final.
    """

    def sorting_key(
        result: RemovalResult,
    ) -> tuple[int, float]:
        if result.relative_improvement is None:
            return (1, 0.0)

        return (
            0,
            -result.relative_improvement,
        )

    return sorted(
        results,
        key=sorting_key,
    )


def _failed_result(
    *,
    candidate: RemovalCandidate,
    baseline_result: FrankWolfeResult,
    connected: bool,
    error: str,
) -> RemovalResult:
    """
    Cria um resultado padronizado para cenário inválido.
    """
    return RemovalResult(
        candidate=candidate,
        connected=connected,
        solver_result=None,
        error=error,
        baseline_tstt=(
            baseline_result.total_system_travel_time
        ),
        modified_tstt=None,
        absolute_improvement=None,
        relative_improvement=None,
        possible_braess=False,
    )


def _normalize_text_attribute(
    value: object,
) -> str:
    """
    Normaliza atributos textuais do OpenStreetMap.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, list | tuple):
        return ";".join(
            str(item)
            for item in value
        )

    return str(value)