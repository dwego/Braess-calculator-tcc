from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
from matplotlib import colormaps
from matplotlib.colors import Normalize

from braess.frank_wolfe import FrankWolfeResult
from braess.models import EdgeFlowMap, EdgeId


def plot_convergence(
    result: FrankWolfeResult,
    output_path: str | Path,
    *,
    title: str = "Convergência do algoritmo de Frank-Wolfe",
    tolerance: float | None = None,
) -> None:
    """
    Gera o gráfico da lacuna relativa por iteração.

    O eixo vertical utiliza escala logarítmica.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    iterations = [
        item.iteration
        for item in result.history
    ]

    gaps = [
        max(item.relative_gap, 1e-16)
        for item in result.history
    ]

    figure, axis = plt.subplots(
        figsize=(10, 5.5)
    )

    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")

    axis.plot(
        iterations,
        gaps,
        linewidth=1.2,
    )

    if tolerance is not None:
        axis.axhline(
            y=tolerance,
            linestyle="--",
            linewidth=1.0,
            label=f"Tolerância: {tolerance:.0e}",
        )

        axis.legend()

    axis.set_yscale("log")
    axis.set_xlabel("Iteração")
    axis.set_ylabel("Lacuna relativa")
    axis.set_title(title)
    axis.grid(
        True,
        alpha=0.25,
    )

    figure.tight_layout()

    figure.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(figure)


def plot_synthetic_flows(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
    output_path: str | Path,
    *,
    title: str,
) -> None:
    """
    Desenha a rede sintética com fluxo e tempo por aresta.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    positions = {
        "O": (0.0, 0.5),
        "A": (1.0, 1.0),
        "B": (1.0, 0.0),
        "D": (2.0, 0.5),
    }

    maximum_flow = max(
        flows.values(),
        default=0.0,
    )

    edge_widths: list[float] = []
    edge_labels: dict[
        tuple[Any, Any, Any],
        str,
    ] = {}

    for u, v, key, data in graph.edges(
        keys=True,
        data=True,
    ):
        edge = EdgeId(u, v, key)
        flow = flows.get(edge, 0.0)

        edge_widths.append(
            _scale_width(
                value=flow,
                maximum=maximum_flow,
                minimum_width=1.0,
                maximum_width=8.0,
            )
        )

        travel_time = float(
            data.get("travel_time", 0.0)
        )

        edge_labels[(u, v, key)] = (
            f"x={flow:.0f}\n"
            f"t={travel_time:.2f}"
        )

    figure, axis = plt.subplots(
        figsize=(10, 6)
    )

    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")

    nx.draw_networkx_nodes(
        graph,
        positions,
        node_size=1800,
        ax=axis,
    )

    nx.draw_networkx_labels(
        graph,
        positions,
        font_size=12,
        ax=axis,
    )

    nx.draw_networkx_edges(
        graph,
        positions,
        width=edge_widths,
        arrows=True,
        arrowsize=22,
        connectionstyle="arc3,rad=0.04",
        ax=axis,
    )

    nx.draw_networkx_edge_labels(
        graph,
        positions,
        edge_labels=edge_labels,
        font_size=9,
        rotate=False,
        label_pos=0.5,
        ax=axis,
    )

    axis.set_title(title)
    axis.set_axis_off()

    figure.tight_layout()

    figure.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(figure)


def plot_urban_flows(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
    output_path: str | Path,
    *,
    title: str = "Fluxos no equilíbrio da rede urbana",
    minimum_active_flow: float = 1e-8,
) -> None:
    """
    Gera o mapa de fluxos da rede urbana.

    Representação:

    - rede completa: linhas finas e discretas;
    - arestas com fluxo: linhas destacadas;
    - espessura: fluxo absoluto;
    - cor: relação fluxo/capacidade.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    active_edges: list[
        tuple[Any, Any, Any, dict[str, Any]]
    ] = []

    active_flows: list[float] = []
    active_ratios: list[float] = []

    for u, v, key, data in graph.edges(
        keys=True,
        data=True,
    ):
        edge = EdgeId(u, v, key)
        flow = flows.get(edge, 0.0)

        if flow <= minimum_active_flow:
            continue

        capacity = _numeric_value(
            data.get("capacity")
        )

        ratio = (
            flow / capacity
            if capacity > 0.0
            else 0.0
        )

        active_edges.append(
            (u, v, key, data)
        )
        active_flows.append(flow)
        active_ratios.append(ratio)

    maximum_flow = max(
        active_flows,
        default=1.0,
    )

    maximum_ratio = max(
        active_ratios,
        default=1.0,
    )

    normalization = Normalize(
        vmin=0.0,
        vmax=max(1.0, maximum_ratio),
    )

    colormap = colormaps["viridis"]

    active_widths = [
        _scale_width(
            value=flow,
            maximum=maximum_flow,
            minimum_width=1.0,
            maximum_width=6.0,
        )
        for flow in active_flows
    ]

    active_colors = [
        colormap(
            normalization(ratio)
        )
        for ratio in active_ratios
    ]

    figure, axis = ox.plot_graph(
        graph,
        node_size=0,
        edge_color="#d0d0d0",
        edge_linewidth=0.35,
        bgcolor="white",
        show=False,
        close=False,
    )

    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")

    if active_edges:
        active_graph = _build_active_subgraph(
            graph=graph,
            active_edges=active_edges,
        )

        ox.plot_graph(
            active_graph,
            ax=axis,
            node_size=0,
            edge_color=active_colors,
            edge_linewidth=active_widths,
            bgcolor="white",
            show=False,
            close=False,
        )

    axis.set_title(title)

    scalar_map = plt.cm.ScalarMappable(
        norm=normalization,
        cmap=colormap,
    )

    scalar_map.set_array([])

    figure.colorbar(
        scalar_map,
        ax=axis,
        fraction=0.03,
        pad=0.02,
        label="Relação fluxo/capacidade",
    )

    figure.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(figure)


def plot_flow_comparison(
    baseline_result: FrankWolfeResult,
    modified_result: FrankWolfeResult,
    output_path: str | Path,
    *,
    baseline_label: str = "Rede original",
    modified_label: str = "Rede modificada",
) -> None:
    """
    Compara o tempo médio de dois cenários.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    labels = [
        baseline_label,
        modified_label,
    ]

    values = [
        baseline_result.average_travel_time,
        modified_result.average_travel_time,
    ]

    figure, axis = plt.subplots(
        figsize=(8, 5)
    )

    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")

    bars = axis.bar(
        labels,
        values,
    )

    axis.set_ylabel("Tempo médio de viagem")
    axis.set_title("Comparação entre cenários")

    for bar, value in zip(
        bars,
        values,
    ):
        axis.text(
            bar.get_x()
            + bar.get_width() / 2,
            bar.get_height(),
            f"{value:.2f}",
            ha="center",
            va="bottom",
        )

    figure.tight_layout()

    figure.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(figure)


def _build_active_subgraph(
    *,
    graph: nx.MultiDiGraph,
    active_edges: list[
        tuple[Any, Any, Any, dict[str, Any]]
    ],
) -> nx.MultiDiGraph:
    """
    Cria um subgrafo contendo apenas arestas com fluxo.
    """
    active_graph = nx.MultiDiGraph()

    active_graph.graph.update(
        graph.graph
    )

    active_nodes: set[Any] = set()

    for u, v, _, _ in active_edges:
        active_nodes.add(u)
        active_nodes.add(v)

    for node in active_nodes:
        active_graph.add_node(
            node,
            **graph.nodes[node],
        )

    for u, v, key, data in active_edges:
        active_graph.add_edge(
            u,
            v,
            key=key,
            **data,
        )

    return active_graph


def _scale_width(
    *,
    value: float,
    maximum: float,
    minimum_width: float,
    maximum_width: float,
) -> float:
    """
    Converte fluxo em espessura visual.
    """
    if value < 0.0:
        raise ValueError(
            "Não é possível representar fluxo negativo."
        )

    if maximum <= 0.0:
        return minimum_width

    normalized = math.sqrt(
        value / maximum
    )

    return (
        minimum_width
        + normalized
        * (
            maximum_width
            - minimum_width
        )
    )


def _numeric_value(
    value: object,
) -> float:
    """
    Converte um valor numérico válido para float.
    """
    if isinstance(value, bool):
        return 0.0

    if isinstance(value, int | float):
        return float(value)

    return 0.0