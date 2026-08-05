from __future__ import annotations

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
from braess.models import EdgeFlowMap, EdgeId, ODPair
from braess.synthetic import (
    COST_FUNCTION_ATTRIBUTE,
    create_zero_flows,
    update_travel_times,
)


@dataclass(frozen=True, slots=True)
class FrankWolfeIteration:
    """
    Registra as métricas de uma iteração do Frank-Wolfe.

    Attributes
    ----------
    iteration:
        Número da iteração, começando em zero.
    relative_gap:
        Lacuna relativa calculada para o fluxo atual.
    step_size:
        Tamanho do passo usado para atualizar o fluxo.
    beckmann_objective:
        Valor da função objetivo de Beckmann.
    total_system_travel_time:
        Tempo total de viagem do sistema.
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

    Attributes
    ----------
    flows:
        Fluxo final de cada aresta.
    converged:
        Indica se a tolerância foi atingida.
    iterations:
        Quantidade de iterações executadas.
    relative_gap:
        Lacuna relativa final.
    total_system_travel_time:
        Tempo total de viagem da rede.
    average_travel_time:
        Tempo médio por veículo.
    beckmann_objective:
        Valor final da função objetivo de Beckmann.
    history:
        Histórico das iterações.
    """

    flows: EdgeFlowMap
    converged: bool
    iterations: int
    relative_gap: float
    total_system_travel_time: float
    average_travel_time: float
    beckmann_objective: float
    history: list[FrankWolfeIteration]


def frank_wolfe(
    graph: nx.MultiDiGraph,
    od_pairs: list[ODPair],
    *,
    relative_gap_tolerance: float = 1e-6,
    max_iterations: int = 100,
    line_search_tolerance: float = 1e-10,
) -> FrankWolfeResult:
    """
    Calcula uma aproximação do equilíbrio do usuário.

    O método resolve a formulação de Beckmann por meio do algoritmo
    de Frank-Wolfe.

    Em cada iteração:

    1. os tempos das arestas são atualizados;
    2. calcula-se a lacuna relativa;
    3. executa-se uma atribuição All-or-Nothing;
    4. calcula-se a direção entre o fluxo atual e o fluxo auxiliar;
    5. realiza-se uma busca pelo melhor tamanho de passo;
    6. os fluxos são atualizados.

    Parameters
    ----------
    graph:
        Rede direcionada com funções de custo em todas as arestas.
    od_pairs:
        Demandas origem-destino.
    relative_gap_tolerance:
        Tolerância usada como critério de convergência.
    max_iterations:
        Número máximo de iterações.
    line_search_tolerance:
        Tolerância da busca numérica do tamanho de passo.

    Returns
    -------
    FrankWolfeResult
        Fluxos finais, métricas e histórico de convergência.

    Raises
    ------
    ValueError
        Caso os parâmetros sejam inválidos ou não existam pares OD.
    """
    _validate_parameters(
        od_pairs=od_pairs,
        relative_gap_tolerance=relative_gap_tolerance,
        max_iterations=max_iterations,
        line_search_tolerance=line_search_tolerance,
    )

    # O Frank-Wolfe precisa começar com uma solução viável.
    #
    # Inicialmente, todos os fluxos são zerados e os tempos são
    # calculados em fluxo livre. Em seguida, uma atribuição
    # All-or-Nothing produz o primeiro vetor de fluxos viável.
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

    for iteration in range(max_iterations + 1):
        update_travel_times(
            graph,
            current_flows,
        )

        current_gap = relative_gap(
            graph,
            current_flows,
            od_pairs,
        )

        current_tstt = total_system_travel_time(
            graph,
            current_flows,
        )

        current_objective = beckmann_objective(
            graph,
            current_flows,
        )

        # Se a lacuna já estiver dentro da tolerância, não é
        # necessário realizar uma nova atualização.
        if current_gap <= relative_gap_tolerance:
            history.append(
                FrankWolfeIteration(
                    iteration=iteration,
                    relative_gap=current_gap,
                    step_size=0.0,
                    beckmann_objective=current_objective,
                    total_system_travel_time=current_tstt,
                )
            )

            return _build_result(
                graph=graph,
                od_pairs=od_pairs,
                flows=current_flows,
                converged=True,
                iterations=iteration,
                history=history,
            )

        # O vetor auxiliar representa o fluxo que seria obtido
        # caso toda demanda escolhesse agora o menor caminho.
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

        history.append(
            FrankWolfeIteration(
                iteration=iteration,
                relative_gap=current_gap,
                step_size=step_size,
                beckmann_objective=current_objective,
                total_system_travel_time=current_tstt,
            )
        )

        current_flows = _update_flows(
            current_flows=current_flows,
            direction=direction,
            step_size=step_size,
        )

    update_travel_times(
        graph,
        current_flows,
    )

    return _build_result(
        graph=graph,
        od_pairs=od_pairs,
        flows=current_flows,
        converged=False,
        iterations=max_iterations,
        history=history,
    )


def _calculate_direction(
    *,
    current_flows: EdgeFlowMap,
    auxiliary_flows: EdgeFlowMap,
) -> EdgeFlowMap:
    """
    Calcula a direção de busca do Frank-Wolfe.

    A direção é dada por:

        d = y - x

    em que:

    - x é o fluxo atual;
    - y é o fluxo auxiliar do All-or-Nothing.
    """
    if current_flows.keys() != auxiliary_flows.keys():
        raise ValueError(
            "Os mapas de fluxo atual e auxiliar possuem "
            "conjuntos diferentes de arestas."
        )

    return {
        edge: auxiliary_flows[edge] - current_flows[edge]
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
    Encontra o tamanho de passo que minimiza o objetivo de Beckmann.

    São avaliados fluxos da forma:

        x(lambda) = x + lambda * d

    com:

        0 <= lambda <= 1
    """

    def objective_at_step(step_size: float) -> float:
        objective = 0.0

        for edge, current_flow in current_flows.items():
            candidate_flow = (
                current_flow
                + step_size * direction[edge]
            )

            # Pequenos valores negativos podem aparecer por causa
            # da precisão de ponto flutuante.
            if candidate_flow < 0.0 and abs(candidate_flow) < 1e-10:
                candidate_flow = 0.0

            if candidate_flow < 0.0:
                raise ValueError(
                    f"O passo gerou fluxo negativo na aresta {edge}."
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

    step_size = float(result.x)

    # Proteção contra pequenos erros numéricos nos limites.
    return min(
        1.0,
        max(0.0, step_size),
    )


def _update_flows(
    *,
    current_flows: EdgeFlowMap,
    direction: EdgeFlowMap,
    step_size: float,
) -> EdgeFlowMap:
    """
    Atualiza os fluxos segundo a regra do Frank-Wolfe.

        x_novo = x_atual + lambda * direção
    """
    updated_flows: EdgeFlowMap = {}

    for edge, current_flow in current_flows.items():
        updated_flow = (
            current_flow
            + step_size * direction[edge]
        )

        if updated_flow < 0.0 and abs(updated_flow) < 1e-10:
            updated_flow = 0.0

        if updated_flow < 0.0:
            raise ValueError(
                f"A atualização gerou fluxo negativo em {edge}."
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
    Calcula e reúne as métricas finais do solver.
    """
    update_travel_times(
        graph,
        flows,
    )

    final_gap = relative_gap(
        graph,
        flows,
        od_pairs,
    )

    final_tstt = total_system_travel_time(
        graph,
        flows,
    )

    final_average = average_travel_time(
        graph,
        flows,
        od_pairs,
    )

    final_objective = beckmann_objective(
        graph,
        flows,
    )

    return FrankWolfeResult(
        flows=flows.copy(),
        converged=converged,
        iterations=iterations,
        relative_gap=final_gap,
        total_system_travel_time=final_tstt,
        average_travel_time=final_average,
        beckmann_objective=final_objective,
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
    Valida os parâmetros principais do solver.
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