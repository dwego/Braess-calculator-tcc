from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import networkx as nx
from scipy.optimize import minimize_scalar

from braess.assignment import all_or_nothing_assignment
from braess.metrics import (
    average_travel_time,
    beckmann_objective,
    relative_gap,
    total_system_travel_time,
)
from braess.models import EdgeFlowMap, ODPair
from braess.synthetic import (
    COST_FUNCTION_ATTRIBUTE,
    create_zero_flows,
    update_travel_times,
)


@dataclass(frozen=True, slots=True)
class FrankWolfeIteration:
    """
    Métricas registradas em uma iteração do Frank-Wolfe.
    """

    iteration: int
    relative_gap: float
    step_size: float
    beckmann_objective: float
    total_system_travel_time: float


@dataclass(frozen=True, slots=True)
class FrankWolfeResult:
    """
    Resultado final do algoritmo de Frank-Wolfe.
    """

    flows: EdgeFlowMap
    converged: bool
    iterations: int
    relative_gap: float
    total_system_travel_time: float
    average_travel_time: float
    beckmann_objective: float
    history: list[FrankWolfeIteration]


ProgressCallback = Callable[[FrankWolfeIteration], None]


def frank_wolfe(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    *,
    relative_gap_tolerance: float = 1e-6,
    max_iterations: int = 100,
    line_search_tolerance: float = 1e-10,
    progress_callback: ProgressCallback | None = None,
) -> FrankWolfeResult:
    """
    Calcula uma aproximação do equilíbrio do usuário.

    O método minimiza a formulação de Beckmann utilizando
    o algoritmo de Frank-Wolfe.

    Em cada iteração:

    1. atualiza os tempos das arestas;
    2. calcula as métricas do estado atual;
    3. verifica a convergência;
    4. executa uma atribuição All-or-Nothing;
    5. calcula a direção de busca;
    6. encontra o tamanho do passo;
    7. atualiza os fluxos.

    Parameters
    ----------
    graph:
        Rede direcionada contendo uma função de custo em cada aresta.
    od_pairs:
        Demandas origem-destino.
    relative_gap_tolerance:
        Tolerância máxima da lacuna relativa.
    max_iterations:
        Número máximo de atualizações do vetor de fluxo.
    line_search_tolerance:
        Tolerância numérica da busca do tamanho do passo.
    progress_callback:
        Função opcional chamada após o registro de cada iteração.

    Returns
    -------
    FrankWolfeResult
        Resultado final, fluxos e histórico do algoritmo.
    """
    _validate_parameters(
        od_pairs=od_pairs,
        relative_gap_tolerance=relative_gap_tolerance,
        max_iterations=max_iterations,
        line_search_tolerance=line_search_tolerance,
    )

    zero_flows = create_zero_flows(graph)

    update_travel_times(
        graph,
        zero_flows,
    )

    current_flows = all_or_nothing_assignment(
        graph,
        od_pairs,
    )

    history: list[FrankWolfeIteration] = []

    for iteration in range(max_iterations):
        update_travel_times(
            graph,
            current_flows,
        )

        current_metrics = _calculate_iteration_metrics(
            graph=graph,
            od_pairs=od_pairs,
            flows=current_flows,
        )

        if (
            current_metrics.relative_gap
            <= relative_gap_tolerance
        ):
            final_iteration = FrankWolfeIteration(
                iteration=iteration,
                relative_gap=current_metrics.relative_gap,
                step_size=0.0,
                beckmann_objective=(
                    current_metrics.beckmann_objective
                ),
                total_system_travel_time=(
                    current_metrics.total_system_travel_time
                ),
            )

            _record_iteration(
                history=history,
                item=final_iteration,
                progress_callback=progress_callback,
            )

            return _build_result(
                graph=graph,
                od_pairs=od_pairs,
                flows=current_flows,
                converged=True,
                iterations=iteration,
                history=history,
            )

        auxiliary_flows = all_or_nothing_assignment(
            graph,
            od_pairs,
        )

        direction = _calculate_direction(
            current_flows=current_flows,
            auxiliary_flows=auxiliary_flows,
        )

        step_size = _find_step_size(
            graph=graph,
            current_flows=current_flows,
            direction=direction,
            tolerance=line_search_tolerance,
        )

        iteration_result = FrankWolfeIteration(
            iteration=iteration,
            relative_gap=current_metrics.relative_gap,
            step_size=step_size,
            beckmann_objective=(
                current_metrics.beckmann_objective
            ),
            total_system_travel_time=(
                current_metrics.total_system_travel_time
            ),
        )

        _record_iteration(
            history=history,
            item=iteration_result,
            progress_callback=progress_callback,
        )

        current_flows = _update_flows(
            current_flows=current_flows,
            direction=direction,
            step_size=step_size,
        )

    # O laço terminou após max_iterations atualizações.
    # Agora registramos o estado realmente final.
    update_travel_times(
        graph,
        current_flows,
    )

    final_metrics = _calculate_iteration_metrics(
        graph=graph,
        od_pairs=od_pairs,
        flows=current_flows,
    )

    final_iteration = FrankWolfeIteration(
        iteration=max_iterations,
        relative_gap=final_metrics.relative_gap,
        step_size=0.0,
        beckmann_objective=(
            final_metrics.beckmann_objective
        ),
        total_system_travel_time=(
            final_metrics.total_system_travel_time
        ),
    )

    _record_iteration(
        history=history,
        item=final_iteration,
        progress_callback=progress_callback,
    )

    converged = (
        final_metrics.relative_gap
        <= relative_gap_tolerance
    )

    return _build_result(
        graph=graph,
        od_pairs=od_pairs,
        flows=current_flows,
        converged=converged,
        iterations=max_iterations,
        history=history,
    )


@dataclass(frozen=True, slots=True)
class _IterationMetrics:
    relative_gap: float
    beckmann_objective: float
    total_system_travel_time: float


def _calculate_iteration_metrics(
    *,
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    flows: EdgeFlowMap,
) -> _IterationMetrics:
    """
    Calcula as métricas usadas durante uma iteração.
    """
    return _IterationMetrics(
        relative_gap=relative_gap(
            graph,
            flows,
            od_pairs,
        ),
        beckmann_objective=beckmann_objective(
            graph,
            flows,
        ),
        total_system_travel_time=(
            total_system_travel_time(
                graph,
                flows,
            )
        ),
    )


def _record_iteration(
    *,
    history: list[FrankWolfeIteration],
    item: FrankWolfeIteration,
    progress_callback: ProgressCallback | None,
) -> None:
    """
    Registra uma iteração e chama o callback de progresso.
    """
    history.append(item)

    if progress_callback is not None:
        progress_callback(item)


def _calculate_direction(
    *,
    current_flows: EdgeFlowMap,
    auxiliary_flows: EdgeFlowMap,
) -> EdgeFlowMap:
    """
    Calcula a direção de busca:

        d = y - x
    """
    if current_flows.keys() != auxiliary_flows.keys():
        raise ValueError(
            "Os mapas de fluxo atual e auxiliar possuem "
            "conjuntos diferentes de arestas."
        )

    return {
        edge: (
            auxiliary_flows[edge]
            - current_flows[edge]
        )
        for edge in current_flows
    }


def _find_step_size(
    *,
    graph: nx.MultiDiGraph,
    current_flows: EdgeFlowMap,
    direction: EdgeFlowMap,
    tolerance: float,
) -> float:
    """
    Encontra o passo que minimiza o objetivo de Beckmann.

    São testados fluxos da forma:

        x(lambda) = x + lambda * d

    com:

        0 <= lambda <= 1
    """

    def objective_at_step(
        step_size: float,
    ) -> float:
        objective = 0.0

        for edge, current_flow in current_flows.items():
            candidate_flow = (
                current_flow
                + step_size * direction[edge]
            )

            if (
                candidate_flow < 0.0
                and abs(candidate_flow) < 1e-10
            ):
                candidate_flow = 0.0

            if candidate_flow < 0.0:
                raise ValueError(
                    "A busca de passo gerou fluxo negativo "
                    f"na aresta {edge}."
                )

            edge_data = graph.get_edge_data(
                edge.u,
                edge.v,
                edge.key,
            )

            if edge_data is None:
                raise KeyError(
                    f"A aresta {edge} não existe no grafo."
                )

            cost_function = edge_data[
                COST_FUNCTION_ATTRIBUTE
            ]

            objective += cost_function.integral(
                candidate_flow
            )

        return objective

    result = minimize_scalar(
        objective_at_step,
        bounds=(0.0, 1.0),
        method="bounded",
        options={
            "xatol": tolerance,
            "maxiter": 200,
        },
    )

    if not result.success:
        raise RuntimeError(
            "A busca pelo tamanho do passo não convergiu: "
            f"{result.message}"
        )

    return min(
        1.0,
        max(0.0, float(result.x)),
    )


def _update_flows(
    *,
    current_flows: EdgeFlowMap,
    direction: EdgeFlowMap,
    step_size: float,
) -> EdgeFlowMap:
    """
    Atualiza os fluxos:

        x_novo = x_atual + lambda * direção
    """
    updated_flows: EdgeFlowMap = {}

    for edge, current_flow in current_flows.items():
        updated_flow = (
            current_flow
            + step_size * direction[edge]
        )

        if (
            updated_flow < 0.0
            and abs(updated_flow) < 1e-10
        ):
            updated_flow = 0.0

        if updated_flow < 0.0:
            raise ValueError(
                "A atualização gerou fluxo negativo "
                f"na aresta {edge}."
            )

        updated_flows[edge] = updated_flow

    return updated_flows


def _build_result(
    *,
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    flows: EdgeFlowMap,
    converged: bool,
    iterations: int,
    history: list[FrankWolfeIteration],
) -> FrankWolfeResult:
    """
    Reúne os fluxos e as métricas finais.
    """
    update_travel_times(
        graph,
        flows,
    )

    return FrankWolfeResult(
        flows=flows.copy(),
        converged=converged,
        iterations=iterations,
        relative_gap=relative_gap(
            graph,
            flows,
            od_pairs,
        ),
        total_system_travel_time=(
            total_system_travel_time(
                graph,
                flows,
            )
        ),
        average_travel_time=average_travel_time(
            graph,
            flows,
            od_pairs,
        ),
        beckmann_objective=beckmann_objective(
            graph,
            flows,
        ),
        history=history.copy(),
    )


def _validate_parameters(
    *,
    od_pairs: list[ODPair],
    relative_gap_tolerance: float,
    max_iterations: int,
    line_search_tolerance: float,
) -> None:
    """
    Valida os parâmetros do solver.
    """
    if not od_pairs:
        raise ValueError(
            "Ao menos um par origem-destino deve ser informado."
        )

    if relative_gap_tolerance <= 0.0:
        raise ValueError(
            "A tolerância da lacuna relativa deve ser positiva."
        )

    if max_iterations <= 0:
        raise ValueError(
            "O número máximo de iterações deve ser positivo."
        )

    if line_search_tolerance <= 0.0:
        raise ValueError(
            "A tolerância da busca de passo deve ser positiva."
        )