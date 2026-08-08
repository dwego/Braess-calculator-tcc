from __future__ import annotations

import csv
import time
from pathlib import Path

import networkx as nx

from braess.frank_wolfe import (
    FrankWolfeIteration,
    FrankWolfeResult,
    frank_wolfe,
)
from braess.models import ODPair
from braess.removal import (
    RemovalCandidate,
    RemovalResult,
    run_removal_experiments,
    select_removal_candidates,
    sort_removal_results,
)
from braess.urban import prepare_urban_graph
from braess.visualization import (
    plot_convergence,
    plot_flow_comparison,
    plot_urban_flows,
)
from braess.maps.graph_builder import build_graph


CENTER_POINT = (
    -23.1791,
    -45.8869,
)

DISTANCE_METERS = 1800
DEMAND_VEHICLES_PER_HOUR = 4000.0

RELATIVE_GAP_TOLERANCE = 5e-4
MAX_ITERATIONS = 1000

CANDIDATE_LIMIT = 10
MINIMUM_BASELINE_FLOW = 40.0

BASELINE_LOG_INTERVAL = 20
REMOVAL_LOG_INTERVAL = 100

OUTPUT_DIRECTORY = Path(
    "outputs/removal-experiment"
)


CAPACITY_PER_LANE = {
    "motorway": 2000.0,
    "motorway_link": 1400.0,
    "trunk": 1800.0,
    "trunk_link": 1300.0,
    "primary": 1600.0,
    "primary_link": 1200.0,
    "secondary": 1400.0,
    "secondary_link": 1100.0,
    "tertiary": 1200.0,
    "tertiary_link": 1000.0,
    "residential": 900.0,
    "living_street": 600.0,
    "service": 600.0,
    "unclassified": 900.0,
}

DEFAULT_CAPACITY_PER_LANE = 800.0


def select_strongly_connected_network(
    graph: nx.MultiDiGraph,
) -> nx.MultiDiGraph:
    """
    Mantém a maior componente fortemente conectada.
    """
    components = list(
        nx.strongly_connected_components(
            graph
        )
    )

    if not components:
        raise ValueError(
            "O grafo não possui componentes "
            "fortemente conectadas."
        )

    largest_component = max(
        components,
        key=len,
    )

    return graph.subgraph(
        largest_component
    ).copy()


def select_origin_destination(
    graph: nx.MultiDiGraph,
) -> tuple[int, int]:
    """
    Seleciona provisoriamente os extremos oeste e leste.
    """
    nodes_with_longitude: list[
        tuple[int, float]
    ] = []

    for node, data in graph.nodes(
        data=True
    ):
        longitude = data.get("x")

        if not isinstance(
            longitude,
            int | float,
        ):
            continue

        nodes_with_longitude.append(
            (
                node,
                float(longitude),
            )
        )

    if len(nodes_with_longitude) < 2:
        raise ValueError(
            "Não existem nós suficientes com longitude."
        )

    origin = min(
        nodes_with_longitude,
        key=lambda item: item[1],
    )[0]

    destination = max(
        nodes_with_longitude,
        key=lambda item: item[1],
    )[0]

    if not nx.has_path(
        graph,
        origin,
        destination,
    ):
        raise nx.NetworkXNoPath(
            "Não existe caminho entre os nós selecionados."
        )

    return origin, destination


def create_solver_logger(
    *,
    prefix: str,
    interval: int,
):
    """
    Cria um logger para acompanhar o Frank-Wolfe.
    """
    started_at = time.perf_counter()

    def log_progress(
        item: FrankWolfeIteration,
    ) -> None:
        should_log = (
            item.iteration == 0
            or item.iteration % interval == 0
            or item.step_size == 0.0
        )

        if not should_log:
            return

        elapsed = (
            time.perf_counter()
            - started_at
        )

        print(
            f"[{prefix}] "
            f"iteração={item.iteration:4d} | "
            f"gap={item.relative_gap:.6e} | "
            f"passo={item.step_size:.6e} | "
            f"tempo={elapsed:.1f}s",
            flush=True,
        )

    return log_progress


def log_scenario_start(
    current: int,
    total: int,
    candidate: RemovalCandidate,
) -> None:
    """
    Exibe a candidata que está sendo testada.
    """
    print(
        "\n"
        f"[Remoção {current}/{total}] "
        f"aresta={candidate.edge} | "
        f"fluxo-base={candidate.baseline_flow:.2f} | "
        f"via={candidate.name or 'sem nome'} | "
        f"tipo={candidate.highway or 'desconhecido'}",
        flush=True,
    )


def create_removal_solver_logger(
    candidate: RemovalCandidate,
):
    """
    Cria um logger específico para cada remoção.
    """
    edge = candidate.edge

    return create_solver_logger(
        prefix=(
            f"FW {edge.u}->{edge.v}:{edge.key}"
        ),
        interval=REMOVAL_LOG_INTERVAL,
    )


def save_removal_results(
    results: list[RemovalResult],
    baseline_result: FrankWolfeResult,
    output_path: str | Path,
) -> None:
    """
    Salva os resultados das remoções em CSV.
    """
    output_path = Path(output_path)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "rank",
        "u",
        "v",
        "key",
        "name",
        "highway",
        "baseline_flow",
        "connected",
        "converged",
        "error",
        "baseline_tstt",
        "modified_tstt",
        "absolute_improvement",
        "relative_improvement",
        "relative_improvement_percent",
        "baseline_average_time_seconds",
        "modified_average_time_seconds",
        "possible_braess",
    ]

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for rank, result in enumerate(
            results,
            start=1,
        ):
            modified = result.solver_result

            relative_percent = ""

            if result.relative_improvement is not None:
                relative_percent = (
                    result.relative_improvement
                    * 100.0
                )

            writer.writerow(
                {
                    "rank": rank,
                    "u": result.candidate.edge.u,
                    "v": result.candidate.edge.v,
                    "key": result.candidate.edge.key,
                    "name": result.candidate.name,
                    "highway": (
                        result.candidate.highway
                    ),
                    "baseline_flow": (
                        result.candidate.baseline_flow
                    ),
                    "connected": result.connected,
                    "converged": (
                        modified.converged
                        if modified is not None
                        else False
                    ),
                    "error": result.error or "",
                    "baseline_tstt": (
                        result.baseline_tstt
                    ),
                    "modified_tstt": (
                        result.modified_tstt
                        if result.modified_tstt
                        is not None
                        else ""
                    ),
                    "absolute_improvement": (
                        result.absolute_improvement
                        if result.absolute_improvement
                        is not None
                        else ""
                    ),
                    "relative_improvement": (
                        result.relative_improvement
                        if result.relative_improvement
                        is not None
                        else ""
                    ),
                    "relative_improvement_percent": (
                        relative_percent
                    ),
                    "baseline_average_time_seconds": (
                        baseline_result
                        .average_travel_time
                    ),
                    "modified_average_time_seconds": (
                        modified.average_travel_time
                        if modified is not None
                        else ""
                    ),
                    "possible_braess": (
                        result.possible_braess
                    ),
                }
            )


def print_summary(
    results: list[RemovalResult],
) -> None:
    """
    Exibe o resumo das remoções.
    """
    valid_results = [
        result
        for result in results
        if result.solver_result is not None
    ]

    braess_candidates = [
        result
        for result in valid_results
        if result.possible_braess
    ]

    print(
        "\nResumo do experimento:",
        flush=True,
    )

    print(
        f"  Cenários avaliados: {len(results)}",
        flush=True,
    )

    print(
        f"  Cenários válidos: {len(valid_results)}",
        flush=True,
    )

    print(
        "  Possíveis ocorrências de Braess: "
        f"{len(braess_candidates)}",
        flush=True,
    )

    for result in braess_candidates[:5]:
        improvement_percent = (
            result.relative_improvement * 100.0
            if result.relative_improvement is not None
            else 0.0
        )

        print(
            "  - "
            f"{result.candidate.edge} | "
            f"{result.candidate.name or 'sem nome'} | "
            f"melhoria={improvement_percent:.6f}%",
            flush=True,
        )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    started_at = time.perf_counter()

    print(
        "Construindo a rede urbana...",
        flush=True,
    )

    raw_graph = build_graph(
        CENTER_POINT,
        DISTANCE_METERS,
    )

    connected_graph = (
        select_strongly_connected_network(
            raw_graph
        )
    )

    urban_graph = prepare_urban_graph(
        connected_graph,
        capacity_per_lane=CAPACITY_PER_LANE,
        default_capacity_per_lane=(
            DEFAULT_CAPACITY_PER_LANE
        ),
        default_lanes=1,
    )

    origin, destination = (
        select_origin_destination(
            urban_graph
        )
    )

    od_pairs = [
        ODPair(
            origin=origin,
            destination=destination,
            demand=(
                DEMAND_VEHICLES_PER_HOUR
            ),
        )
    ]

    print(
        f"Origem: {origin}",
        flush=True,
    )

    print(
        f"Destino: {destination}",
        flush=True,
    )

    print(
        "Executando o cenário-base...",
        flush=True,
    )

    baseline_result = frank_wolfe(
        urban_graph,
        od_pairs,
        relative_gap_tolerance=(
            RELATIVE_GAP_TOLERANCE
        ),
        max_iterations=MAX_ITERATIONS,
        progress_callback=create_solver_logger(
            prefix="Base",
            interval=BASELINE_LOG_INTERVAL,
        ),
    )

    if not baseline_result.converged:
        raise RuntimeError(
            "O cenário-base não convergiu."
        )

    candidates = select_removal_candidates(
        urban_graph,
        baseline_result,
        limit=CANDIDATE_LIMIT,
        minimum_flow=MINIMUM_BASELINE_FLOW,
        excluded_highway_types={
            "service",
        },
    )

    print(
        f"{len(candidates)} candidatas selecionadas.",
        flush=True,
    )

    results = run_removal_experiments(
        urban_graph,
        od_pairs,
        baseline_result,
        candidates,
        relative_gap_tolerance=(
            RELATIVE_GAP_TOLERANCE
        ),
        max_iterations=MAX_ITERATIONS,
        numerical_tolerance=1e-6,
        scenario_progress_callback=(
            log_scenario_start
        ),
        solver_progress_factory=(
            create_removal_solver_logger
        ),
    )

    ordered_results = sort_removal_results(
        results
    )

    save_removal_results(
        ordered_results,
        baseline_result,
        OUTPUT_DIRECTORY
        / "removal-results.csv",
    )

    plot_urban_flows(
        urban_graph,
        baseline_result.flows,
        OUTPUT_DIRECTORY
        / "baseline-flows.png",
        title=(
            "Fluxos do cenário-base — "
            f"{baseline_result.average_travel_time / 60:.2f} min"
        ),
        minimum_active_flow=40.0,
    )

    plot_convergence(
        baseline_result,
        OUTPUT_DIRECTORY
        / "baseline-convergence.png",
        title="Convergência do cenário-base",
        tolerance=RELATIVE_GAP_TOLERANCE,
    )

    valid_results = [
        result
        for result in ordered_results
        if result.solver_result is not None
    ]

    if valid_results:
        best_result = valid_results[0]
        best_solver = best_result.solver_result

        modified_graph = urban_graph.copy()

        edge = best_result.candidate.edge

        modified_graph.remove_edge(
            edge.u,
            edge.v,
            edge.key,
        )

        plot_urban_flows(
            modified_graph,
            best_solver.flows,
            OUTPUT_DIRECTORY
            / "best-removal-flows.png",
            title=(
                "Fluxos após melhor remoção — "
                f"{best_solver.average_travel_time / 60:.2f} min"
            ),
            minimum_active_flow=40.0,
        )

        plot_flow_comparison(
            baseline_result,
            best_solver,
            OUTPUT_DIRECTORY
            / "best-removal-comparison.png",
            baseline_label="Rede original",
            modified_label="Rede modificada",
        )

    print_summary(
        ordered_results
    )

    elapsed = (
        time.perf_counter()
        - started_at
    )

    print(
        "\nResultados salvos em: "
        f"{OUTPUT_DIRECTORY}",
        flush=True,
    )

    print(
        f"Tempo total: {elapsed:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()