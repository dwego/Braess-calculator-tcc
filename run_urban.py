from __future__ import annotations

import time
from pathlib import Path

import networkx as nx

from braess.frank_wolfe import (
    FrankWolfeIteration,
    frank_wolfe,
)
from braess.models import ODPair
from braess.outputs import (
    save_edge_results,
    save_iteration_history,
    save_summary,
)
from braess.urban import prepare_urban_graph
from braess.visualization import (
    plot_convergence,
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
LOG_INTERVAL = 10

OUTPUT_DIRECTORY = Path(
    "outputs/urban-baseline"
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
    Seleciona provisoriamente o nó mais a oeste e
    o nó mais a leste.

    Essa escolha é determinística, mas ainda deverá ser
    substituída pela seleção metodológica final.
    """
    if graph.number_of_nodes() < 2:
        raise ValueError(
            "A rede precisa possuir ao menos dois nós."
        )

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

    if origin == destination:
        raise ValueError(
            "A origem e o destino selecionados são iguais."
        )

    if not nx.has_path(
        graph,
        origin,
        destination,
    ):
        raise nx.NetworkXNoPath(
            "Não existe caminho entre a origem "
            "e o destino selecionados."
        )

    return origin, destination


def create_progress_logger(
    *,
    interval: int,
):
    """
    Cria o callback de acompanhamento do solver.
    """
    if interval <= 0:
        raise ValueError(
            "O intervalo de log deve ser positivo."
        )

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
            "[Frank-Wolfe] "
            f"iteração={item.iteration:4d} | "
            f"gap={item.relative_gap:.6e} | "
            f"passo={item.step_size:.6e} | "
            f"objetivo="
            f"{item.beckmann_objective:.3f} | "
            f"TSTT="
            f"{item.total_system_travel_time:.3f} | "
            f"tempo={elapsed:.1f}s",
            flush=True,
        )

    return log_progress


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    execution_started_at = (
        time.perf_counter()
    )

    print(
        "Baixando e preparando a rede viária...",
        flush=True,
    )

    raw_graph = build_graph(
        CENTER_POINT,
        DISTANCE_METERS,
    )

    print(
        "Rede bruta: "
        f"{raw_graph.number_of_nodes()} nós e "
        f"{raw_graph.number_of_edges()} arestas.",
        flush=True,
    )

    connected_graph = (
        select_strongly_connected_network(
            raw_graph
        )
    )

    print(
        "Maior componente fortemente conectada: "
        f"{connected_graph.number_of_nodes()} nós e "
        f"{connected_graph.number_of_edges()} arestas.",
        flush=True,
    )

    print(
        "Preparando capacidades e funções BPR...",
        flush=True,
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

    print(
        f"Origem selecionada: {origin}",
        flush=True,
    )

    print(
        f"Destino selecionado: {destination}",
        flush=True,
    )

    print(
        "Demanda: "
        f"{DEMAND_VEHICLES_PER_HOUR:.0f} "
        "veículos por hora.",
        flush=True,
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
        "Executando o algoritmo de Frank-Wolfe...",
        flush=True,
    )

    result = frank_wolfe(
        urban_graph,
        od_pairs,
        relative_gap_tolerance=(
            RELATIVE_GAP_TOLERANCE
        ),
        max_iterations=MAX_ITERATIONS,
        progress_callback=(
            create_progress_logger(
                interval=LOG_INTERVAL,
            )
        ),
    )

    average_minutes = (
        result.average_travel_time
        / 60.0
    )

    print(
        "\nResultado do equilíbrio:",
        flush=True,
    )

    print(
        f"  Convergiu: {result.converged}",
        flush=True,
    )

    print(
        f"  Iterações: {result.iterations}",
        flush=True,
    )

    print(
        "  Lacuna relativa: "
        f"{result.relative_gap:.6e}",
        flush=True,
    )

    print(
        "  Tempo médio: "
        f"{result.average_travel_time:.2f} s "
        f"({average_minutes:.2f} min)",
        flush=True,
    )

    print(
        "  TSTT: "
        f"{result.total_system_travel_time:.3f}",
        flush=True,
    )

    print(
        "Gerando mapa, gráfico e arquivos...",
        flush=True,
    )

    plot_urban_flows(
        urban_graph,
        result.flows,
        OUTPUT_DIRECTORY
        / "urban-flows.png",
        title=(
            "Fluxos no equilíbrio — "
            f"{average_minutes:.2f} min"
        ),
    )

    plot_convergence(
        result,
        OUTPUT_DIRECTORY
        / "convergence.png",
        title=(
            "Convergência do Frank-Wolfe "
            "— rede urbana"
        ),
        tolerance=RELATIVE_GAP_TOLERANCE,
    )

    save_edge_results(
        urban_graph,
        result,
        OUTPUT_DIRECTORY
        / "edge-results.csv",
    )

    save_iteration_history(
        result,
        OUTPUT_DIRECTORY
        / "iterations.csv",
    )

    total_execution_seconds = (
        time.perf_counter()
        - execution_started_at
    )

    save_summary(
        result,
        OUTPUT_DIRECTORY
        / "summary.json",
        extra={
            "origin": origin,
            "destination": destination,
            "demand_vehicles_per_hour": (
                DEMAND_VEHICLES_PER_HOUR
            ),
            "center_point": list(
                CENTER_POINT
            ),
            "distance_meters": (
                DISTANCE_METERS
            ),
            "average_travel_time_minutes": (
                average_minutes
            ),
            "relative_gap_tolerance": (
                RELATIVE_GAP_TOLERANCE
            ),
            "max_iterations": (
                MAX_ITERATIONS
            ),
            "nodes": (
                urban_graph.number_of_nodes()
            ),
            "edges": (
                urban_graph.number_of_edges()
            ),
            "execution_time_seconds": (
                total_execution_seconds
            ),
        },
    )

    print(
        "Resultados salvos em: "
        f"{OUTPUT_DIRECTORY}",
        flush=True,
    )

    print(
        "Tempo total da execução: "
        f"{total_execution_seconds:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()