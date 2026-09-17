"""Renderização de fluxos urbanos; nenhum grafo ou fluxo de entrada é alterado."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
from matplotlib import colormaps
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm
from matplotlib.lines import Line2D
from shapely.affinity import translate
from shapely.geometry import LineString, Point

from braess.models import EdgeFlowMap, EdgeId


MAXIMUM_LINEWIDTH = 2.1  # points; the previous urban rendering used 6 points
MINIMUM_LINEWIDTH = .35
PARALLEL_SPACING = 2.4  # points on the figure, not a change to road geometry
REMOVED_COLOR = "#e6007e"
REMOVED_LINEWIDTH = 2.9
FLOW_CMAP = colormaps["plasma"]
DELTA_CMAP = LinearSegmentedColormap.from_list(
    "flow_change", ["#0956b8", "#579cda", "#bfc1c4", "#ef806b", "#c91e28"], N=257,
)


@dataclass(frozen=True)
class UrbanFlowScale:
    maximum_flow: float
    maximum_ratio: float
    maximum_delta: float

    @classmethod
    def from_flows(cls, graph, flow_maps, *, baseline_flows=None):
        """Um domínio comum, incluindo todas as soluções do mesmo experimento."""
        maximum_flow, maximum_ratio, maximum_delta = 1.0, 1.0, 0.0
        for flows in flow_maps:
            for u, v, key, data in graph.edges(keys=True, data=True):
                edge = EdgeId(u, v, key)
                flow = flows.get(edge, 0.0)
                maximum_flow = max(maximum_flow, flow)
                capacity = float(data.get("capacity", 0) or 0)
                if capacity > 0:
                    maximum_ratio = max(maximum_ratio, flow / capacity)
                if baseline_flows is not None:
                    maximum_delta = max(maximum_delta, abs(flow - baseline_flows.get(edge, 0.0)))
        return cls(maximum_flow, maximum_ratio, maximum_delta or 1.0)


def flow_linewidth(value: float, maximum: float, *, length_points: float = math.inf) -> float:
    """Escala suave e limitada; trechos curtos não viram retângulos grossos."""
    fraction = min(1.0, max(0.0, value) / max(maximum, 1e-12))
    width = MINIMUM_LINEWIDTH + (MAXIMUM_LINEWIDTH - MINIMUM_LINEWIDTH) * math.log1p(4 * fraction) / math.log(5)
    return min(width, max(.2, .45 * length_points))


def flow_deltas(graph, baseline_flows: EdgeFlowMap, modified_flows: EdgeFlowMap) -> EdgeFlowMap:
    # O grafo de referência inclui a removida: seu fluxo modificado é zero.
    return {edge: modified_flows.get(edge, 0.0) - baseline_flows.get(edge, 0.0)
            for edge in (EdgeId(u, v, key) for u, v, key in graph.edges(keys=True))}


class UrbanFlowGeometry:
    """Geometria projetada da rede original, reutilizada em todas as figuras."""

    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = ox.projection.project_graph(graph)
        self.geometries = {}
        self.parallel_groups = []
        groups = defaultdict(list)
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            edge = EdgeId(u, v, key)
            geometry = data.get("geometry") or LineString([
                (self.graph.nodes[node]["x"], self.graph.nodes[node]["y"]) for node in (u, v)
            ])
            self.geometries[edge] = geometry
            groups[geometry.normalize().wkb].append(edge)
        for members in groups.values():
            if len(members) > 1:
                self.parallel_groups.append(sorted(members, key=lambda edge: (str(edge.u), str(edge.v), str(edge.key))))
        bounds = [geometry.bounds for geometry in self.geometries.values()]
        west, south = min(b[0] for b in bounds), min(b[1] for b in bounds)
        east, north = max(b[2] for b in bounds), max(b[3] for b in bounds)
        padding = max(20, max(east - west, north - south) * .035)
        self.bounds = (west - padding, south - padding, east + padding, north + padding)
        self.detail_bounds = None
        self._display_cache = {}

    def focus_on(self, edges):
        bounds = [self.geometries[edge].bounds for edge in edges if edge is not None]
        if bounds:
            west, south = min(b[0] for b in bounds), min(b[1] for b in bounds)
            east, north = max(b[2] for b in bounds), max(b[3] for b in bounds)
            padding = max(120, max(east - west, north - south) * .35)
            self.detail_bounds = (west - padding, south - padding, east + padding, north + padding)

    def node_position(self, node):
        data = self.graph.nodes[node]
        return data["x"], data["y"]

    def display_geometries(self, points_per_metre):
        """Separa somente geometrias coincidentes, de forma estável entre cenários."""
        cache_key = round(points_per_metre, 10)
        if cache_key in self._display_cache:
            return self._display_cache[cache_key]
        display = dict(self.geometries)
        for members in self.parallel_groups:
            canonical = self.geometries[members[0]].normalize()
            directions = defaultdict(list)
            for edge in members:
                source = Point(self.node_position(edge.u))
                forward = source.distance(Point(canonical.coords[0])) <= source.distance(Point(canonical.coords[-1]))
                directions[forward].append(edge)
            for edge in members:
                forward = edge in directions.get(True, [])
                lane = directions[forward].index(edge)
                if len(directions) == 2:
                    # Mantém o lado direito do sentido, sem alternar pela ordem dos IDs OSM.
                    offset = -(lane + .5) if forward else lane + .5
                else:
                    offset = lane - (len(members) - 1) / 2
                distance = offset * PARALLEL_SPACING / points_per_metre
                shifted = canonical.offset_curve(distance, join_style="round") if distance else canonical
                if shifted.is_empty or shifted.geom_type != "LineString":
                    start, end = canonical.coords[0], canonical.coords[-1]
                    dx, dy = end[0] - start[0], end[1] - start[1]
                    norm = math.hypot(dx, dy) or 1.0
                    shifted = translate(canonical, xoff=-dy * distance / norm, yoff=dx * distance / norm)
                display[edge] = shifted
        # OSM pode armazenar a mesma ordem de coordenadas nos dois sentidos.
        for edge, geometry in display.items():
            source = Point(self.node_position(edge.u))
            if source.distance(Point(geometry.coords[0])) > source.distance(Point(geometry.coords[-1])):
                display[edge] = LineString(list(geometry.coords)[::-1])
        self._display_cache[cache_key] = display
        return display


def _draw_network(axis, graph, flows, geometry, scale, norm, cmap, bounds, *, threshold,
                  removed_edge, delta, endpoints, detail=False):
    background = LineCollection([list(line.coords) for line in geometry.geometries.values()],
                                colors="#b8c2cb", linewidths=.30, zorder=1)
    background.set_gid("full-road-network")
    axis.add_collection(background)
    west, south, east, north = bounds
    axis.set_xlim(west, east)
    axis.set_ylim(south, north)
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])
    if not detail:
        axis.set_axis_off()
    else:
        for spine in axis.spines.values():
            spine.set_color("#aab6bf")
            spine.set_linewidth(.6)
    axis.figure.canvas.draw()
    p0, p1 = axis.transData.transform([(west, south), (west + 1, south)])
    points_per_metre = math.hypot(*(p1 - p0)) * 72 / axis.figure.dpi
    display = geometry.display_geometries(points_per_metre)
    segments, widths, colors, active = [], [], [], []
    for edge, line in display.items():
        if not delta and (edge == removed_edge or not graph.has_edge(edge.u, edge.v, edge.key)):
            continue
        value = flows.get(edge, 0.0)
        if abs(value) <= threshold:
            continue
        capacity = float(geometry.graph[edge.u][edge.v][edge.key].get("capacity", 0) or 0)
        color_value = value if delta else value / capacity if capacity > 0 else 0.0
        width = flow_linewidth(abs(value), scale.maximum_delta if delta else scale.maximum_flow,
                               length_points=line.length * points_per_metre)
        segments.append(list(line.coords))
        widths.append(width)
        colors.append(cmap(norm(color_value)))
        active.append(edge)
    overlay = LineCollection(segments, linewidths=widths, colors=colors, capstyle="round", joinstyle="round", zorder=3)
    overlay.set_gid("delta-flow-overlay" if delta else "active-flow-overlay")
    axis.add_collection(overlay)
    parallel_edges = {edge for group in geometry.parallel_groups for edge in group}
    for edge, color in zip(active, colors):
        line = display[edge]
        if edge in parallel_edges and line.length * points_per_metre >= 18:
            start, end = line.interpolate(.48, normalized=True), line.interpolate(.58, normalized=True)
            if west <= end.x <= east and south <= end.y <= north:
                axis.annotate("", (end.x, end.y), (start.x, start.y), zorder=4,
                              arrowprops={"arrowstyle": "->", "mutation_scale": 5, "lw": .65, "color": color})
    if removed_edge is not None:
        removed = geometry.geometries[removed_edge]
        # Geometria original, mesmo ausente na rede modificada.
        axis.plot(*removed.xy, color="white", linewidth=4.2, zorder=5, solid_capstyle="round")
        artist, = axis.plot(*removed.xy, color=REMOVED_COLOR, linewidth=REMOVED_LINEWIDTH,
                            linestyle=(0, (4, 2.5)), zorder=6, dash_capstyle="round")
        artist.set_gid("removed-edge")
        if not detail:
            middle = removed.interpolate(.5, normalized=True)
            axis.annotate("aresta removida", (middle.x, middle.y), xytext=(25, -28),
                          textcoords="offset points", fontsize=9, color=REMOVED_COLOR, weight="bold",
                          arrowprops={"arrowstyle": "-", "color": REMOVED_COLOR, "lw": .8},
                          bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9}, zorder=9)
    for node, label, role, color, marker in endpoints:
        if node is None:
            continue
        xy = geometry.node_position(node)
        if not (west <= xy[0] <= east and south <= xy[1] <= north):
            continue
        axis.scatter(*xy, s=270 if detail else 360, marker=marker, c=color,
                     edgecolors="white", linewidths=2.2, zorder=10)
        axis.text(*xy, label, ha="center", va="center", color="white", fontsize=11 if detail else 13,
                  weight="bold", zorder=11, clip_on=detail)


def _plot_map(graph, flows, output_path, *, title, minimum_active_flow, scale,
              geometry, origin_node, destination_node, origin_label, destination_label,
              removed_edge, delta=False):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(figsize=(12, 8.5), facecolor="white")
    axis = figure.add_axes((.025, .11, .68, .80))
    color_axis = figure.add_axes((.755, .37, .21, .022))
    endpoints = [(origin_node, origin_label, "origem", "#087f8c", "o"),
                 (destination_node, destination_label, "destino", "#25354a", "s")]
    cmap = DELTA_CMAP if delta else FLOW_CMAP
    norm = (TwoSlopeNorm(vmin=-scale.maximum_delta, vcenter=0, vmax=scale.maximum_delta)
            if delta else Normalize(vmin=0, vmax=scale.maximum_ratio))
    try:
        figure.suptitle(title, fontsize=14, y=.96)
        options = dict(threshold=minimum_active_flow, removed_edge=removed_edge, delta=delta, endpoints=endpoints)
        _draw_network(axis, graph, flows, geometry, scale, norm, cmap, geometry.bounds, **options)
        if geometry.detail_bounds is not None:
            detail_axis = figure.add_axes((.745, .52, .23, .36))
            detail_axis.set_title("Detalhe · mesmo recorte em todos os cenários", fontsize=8, pad=9)
            _draw_network(detail_axis, graph, flows, geometry, scale, norm, cmap, geometry.detail_bounds,
                          detail=True, **options)
        if removed_edge is not None:
            figure.text(.755, .465, f"Removida: {removed_edge.u} → {removed_edge.v}\nchave OSM: {removed_edge.key}",
                        fontsize=8, color=REMOVED_COLOR)
        handles = [Line2D([], [], color=color, marker=marker, linestyle="none", markersize=9,
                          label=f"{label} — {role}") for node, label, role, color, marker in endpoints if node is not None]
        if removed_edge is not None:
            handles.append(Line2D([], [], color=REMOVED_COLOR, linewidth=REMOVED_LINEWIDTH, linestyle="--", label="Aresta removida"))
        if handles:
            figure.legend(handles=handles, loc="lower center", bbox_to_anchor=(.37, .065), ncol=3, frameon=False, fontsize=9)
        colorbar = figure.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=color_axis, orientation="horizontal",
                                   label="Δ fluxo (veíc/h)" if delta else "Fluxo / capacidade")
        if delta:
            colorbar.set_ticks([scale.maximum_delta * fraction for fraction in (-1, -.5, 0, .5, 1)])
        color_axis.tick_params(labelsize=8)
        figure.text(.755, .215, "Δ = modificado − baseline\nvermelho: aumento\nazul: redução · cinza: próximo de zero" if delta
                    else "espessura = fluxo\ncor = fluxo/capacidade", fontsize=9, color="#34434e")
        maximum = scale.maximum_delta if delta else scale.maximum_flow
        samples = [Line2D([], [], color="#536b7d", linewidth=flow_linewidth(maximum * ratio, maximum),
                          label=f"{maximum * ratio:,.0f}".replace(",", ".")) for ratio in (.25, .5, 1)]
        figure.legend(handles=samples, loc="lower right", bbox_to_anchor=(.975, .095), ncol=3, frameon=False,
                      title="|Δ fluxo| (veíc/h)" if delta else "Fluxo (veíc/h)", fontsize=8, title_fontsize=8)
        threshold = "Rede completa ao fundo; delta inclui a aresta removida." if delta else f"Rede completa ao fundo; destaque para fluxo > {minimum_active_flow:g} veíc/h."
        figure.text(.065, .027, threshold, fontsize=7, color="#5a6872")
        figure.text(.065, .012, "OpenStreetMap · paralelas coincidentes separadas apenas no desenho · escalas comuns ao experimento",
                    fontsize=7, color="#5a6872")
        figure.savefig(output_path, dpi=300, facecolor="white")
    finally:
        plt.close(figure)


def plot_urban_flows(graph: nx.MultiDiGraph, flows: EdgeFlowMap, output_path: str | Path, *,
                     title: str = "Fluxos no equilíbrio da rede urbana", minimum_active_flow: float = 1e-8,
                     scale: UrbanFlowScale | None = None, geometry: UrbanFlowGeometry | None = None,
                     baseline_graph: nx.MultiDiGraph | None = None, removed_edge: EdgeId | None = None,
                     origin_node=None, destination_node=None, origin_label="O", destination_label="D") -> None:
    reference = baseline_graph if baseline_graph is not None else graph
    _plot_map(graph, flows, output_path, title=title, minimum_active_flow=minimum_active_flow,
              scale=scale or UrbanFlowScale.from_flows(reference, [flows]), geometry=geometry or UrbanFlowGeometry(reference),
              origin_node=origin_node, destination_node=destination_node, origin_label=origin_label,
              destination_label=destination_label, removed_edge=removed_edge)


def plot_delta_flows(baseline_graph, baseline_flows, modified_flows, output_path, *,
                     title="Redistribuição dos fluxos", scale=None, geometry=None, removed_edge=None,
                     origin_node=None, destination_node=None, origin_label="O", destination_label="D"):
    _plot_map(baseline_graph, flow_deltas(baseline_graph, baseline_flows, modified_flows), output_path,
              title=title, minimum_active_flow=1e-8, delta=True,
              scale=scale or UrbanFlowScale.from_flows(baseline_graph, [modified_flows], baseline_flows=baseline_flows),
              geometry=geometry or UrbanFlowGeometry(baseline_graph), origin_node=origin_node,
              destination_node=destination_node, origin_label=origin_label, destination_label=destination_label,
              removed_edge=removed_edge)
