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
) -> None:
    """
    Gera um gráfico da lacuna relativa ao longo das iterações.

    O eixo vertical utiliza escala logarítmica para facilitar a
    visualização da aproximação da lacuna relativa a zero.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    iterations = [
        item.iteration
        for item in result.history
    ]

    gaps = [
        max(item.relative_gap, 1e-16)
        for item in result.history
    ]

    figure, axis = plt.subplots(figsize=(9, 5))

    axis.plot(
        iterations,
        gaps,
        marker="o",
        markersize=3,
    )

    axis.set_yscale("log")
    axis.set_xlabel("Iteração")
    axis.set_ylabel("Lacuna relativa")
    axis.set_title(title)
    axis.grid(True, alpha=0.3)

    figure.tight_layout()
    figure.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight",
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
    Desenha a rede sintética e exibe o fluxo e o tempo das arestas.

    A espessura das arestas cresce conforme o fluxo atribuído.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    positions = {
        "O": (0.0, 0.5),
        "A": (1.0, 1.0),
        "B": (1.0, 0.0),
        "D": (2.0, 0.5),
    }

    max_flow = max(
        flows.values(),
        default=0.0,
    )

    edge_widths: list[float] = []
    edge_labels: dict[tuple[Any, Any, Any], str] = {}

    for u, v, key, data in graph.edges(
        keys=True,
        data=True,
    ):
        edge = EdgeId(u, v, key)
        flow = flows.get(edge, 0.0)

        width = _scale_width(
            value=flow,
            maximum=max_flow,
            minimum_width=1.0,
            maximum_width=8.0,
        )

        edge_widths.append(width)

        travel_time = float(
            data.get("travel_time", 0.0)
        )

        edge_labels[(u, v, key)] = (
            f"x={flow:.0f}\n"
            f"t={travel_time:.2f}"
        )

    figure, axis = plt.subplots(figsize=(10, 6))

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
    )

    plt.close(figure)


def plot_urban_flows(
    graph: nx.MultiDiGraph,
    flows: EdgeFlowMap,
    output_path: str | Path,
    *,
    title: str = "Fluxos no equilíbrio da rede urbana",
) -> None:
    """
    Gera um mapa da rede urbana após a atribuição de tráfego.

    Representação visual:

    - espessura: fluxo absoluto da aresta;
    - cor: relação fluxo/capacidade;
    - arestas sem fluxo: linhas finas.

    Espera-se que o grafo possua coordenadas geográficas nos nós,
    como ocorre nos grafos obtidos pelo OSMnx.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ordered_edges = list(
        graph.edges(keys=True, data=True)
    )

    edge_flows: list[float] = []
    volume_capacity_ratios: list[float] = []

    for u, v, key, data in ordered_edges:
        edge = EdgeId(u, v, key)
        flow = flows.get(edge, 0.0)

        capacity = float(
            data.get("capacity", 0.0)
        )

        edge_flows.append(flow)

        if capacity > 0.0:
            ratio = flow / capacity
        else:
            ratio = 0.0

        volume_capacity_ratios.append(ratio)

    max_flow = max(
        edge_flows,
        default=0.0,
    )

    edge_widths = [
        _scale_width(
            value=flow,
            maximum=max_flow,
            minimum_width=0.3,
            maximum_width=5.0,
        )
        for flow in edge_flows
    ]

    maximum_ratio = max(
        volume_capacity_ratios,
        default=1.0,
    )

    normalization = Normalize(
        vmin=0.0,
        vmax=max(1.0, maximum_ratio),
    )

    colormap = colormaps["viridis"]

    edge_colors = [
        colormap(normalization(ratio))
        for ratio in volume_capacity_ratios
    ]

    figure, axis = ox.plot_graph(
        graph,
        node_size=0,
        edge_color=edge_colors,
        edge_linewidth=edge_widths,
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
    Compara visualmente os tempos médios de dois cenários.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    labels = [
        baseline_label,
        modified_label,
    ]

    values = [
        baseline_result.average_travel_time,
        modified_result.average_travel_time,
    ]

    figure, axis = plt.subplots(figsize=(8, 5))

    bars = axis.bar(
        labels,
        values,
    )

    axis.set_ylabel("Tempo médio de viagem")
    axis.set_title("Comparação entre cenários")

    for bar, value in zip(bars, values):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
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
    )

    plt.close(figure)


def _scale_width(
    *,
    value: float,
    maximum: float,
    minimum_width: float,
    maximum_width: float,
) -> float:
    """
    Converte um valor de fluxo em uma espessura visual.

    Utiliza raiz quadrada para evitar que poucas arestas com fluxo
    muito alto escondam todas as demais.
    """
    if value < 0.0:
        raise ValueError(
            "Não é possível representar fluxo negativo."
        )

    if maximum <= 0.0:
        return minimum_width

    normalized = math.sqrt(value / maximum)

    return (
        minimum_width
        + normalized
        * (maximum_width - minimum_width)
    )