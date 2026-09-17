"""Mapas para inspeção humana de nós e candidatos, sem atribuição de fluxos."""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import osmnx as ox
from pyproj import Transformer
from shapely.geometry import LineString, box

from braess.experiment_config import point_members
from braess.point_resolution import normalize_street_name, street_queries


COLORS = ["#1769aa", "#d14900", "#18835f", "#8a388d"]


def plot_validation_maps(graph, map_config: dict, output_directory: str | Path,
                         *, zoom_radius_m: float = 300) -> list[Path]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    projected = ox.projection.project_graph(graph)
    transformer = Transformer.from_crs(graph.graph["crs"], projected.graph["crs"], always_xy=True)
    edges = []
    for u, v, key, data in projected.edges(keys=True, data=True):
        geometry = data.get("geometry") or LineString([
            (projected.nodes[n]["x"], projected.nodes[n]["y"]) for n in (u, v)
        ])
        name = data.get("name", "")
        if isinstance(name, list):
            name = " / ".join(name)
        # Geometrias de arestas bidirecionais podem vir armazenadas na mesma ordem.
        start = projected.nodes[u]
        if ((geometry.coords[0][0] - start["x"]) ** 2 + (geometry.coords[0][1] - start["y"]) ** 2
                > (geometry.coords[-1][0] - start["x"]) ** 2 + (geometry.coords[-1][1] - start["y"]) ** 2):
            geometry = LineString(list(geometry.coords)[::-1])
        edges.append((geometry, name, (u, v, key)))
    locations = {}
    for label, point in map_config["points"].items():
        members = point_members(point)
        if members and all(member.get("latitude") is not None for member in members):
            locations[label] = [
                (transformer.transform(member.get("node_longitude", member["longitude"]),
                                       member.get("node_latitude", member["latitude"])),
                 member.get("label", label), member.get("node_id")) for member in members
            ]
        else:
            locations[label] = [
                (transformer.transform(item["longitude"], item["latitude"]), f"{label}{i}", item["node_id"])
                for i, item in enumerate(point.get("resolution", {}).get("candidates", []), 1)
            ]

    def draw(destination, selected_labels, zoom=False):
        coordinates = [xy for label in selected_labels for xy, _, _ in locations[label]]
        if not coordinates or (not zoom and map_config.get("graphml")):
            coordinates = [(data["x"], data["y"]) for _, data in projected.nodes(data=True)]
        xs, ys = zip(*coordinates)
        padding = zoom_radius_m if zoom else max(150, max(max(xs) - min(xs), max(ys) - min(ys)) * .03)
        bounds = (min(xs) - padding, min(ys) - padding, max(xs) + padding, max(ys) + padding)
        view = box(*bounds)
        visible = [(geometry, name, edge) for geometry, name, edge in edges if geometry.intersects(view)]
        fig, axis = plt.subplots(figsize=(11, 9))
        axis.add_collection(LineCollection([list(geometry.coords) for geometry, _, _ in visible],
                                           colors="#a1abb2", linewidths=.85 if zoom else .45))
        axis.set_xlim(bounds[0], bounds[2])
        axis.set_ylim(bounds[1], bounds[3])
        axis.set_aspect("equal")
        axis.set_axis_off()
        handles = []
        group_zoom = zoom and any(map_config["points"][label].get("type") == "junction_group" for label in selected_labels)
        if group_zoom:
            for geometry, _, _ in visible:
                a, b = geometry.interpolate(.38, normalized=True), geometry.interpolate(.48, normalized=True)
                if view.contains(b):
                    axis.annotate("", (b.x, b.y), (a.x, a.y),
                                  arrowprops={"arrowstyle": "->", "color": "#667580", "lw": .7}, zorder=3)
            for route_index, route in enumerate(map_config["routes"]):
                for endpoint in ("origin", "destination"):
                    if route[endpoint] not in selected_labels:
                        continue
                    chosen = route.get(f"{endpoint}_node")
                    if chosen is None:
                        continue
                    color = ["#00805a", "#c34921"][route_index % 2]
                    selected_edges = {(item["u"], item["v"], item["key"])
                                      for item in route.get("node_selection", {}).get(f"{endpoint}_edges", [])}
                    for geometry, _, edge in visible:
                        if edge in selected_edges:
                            axis.plot(*geometry.xy, color=color, linewidth=2.3, zorder=3)
                            a, b = geometry.interpolate(.38, normalized=True), geometry.interpolate(.48, normalized=True)
                            axis.annotate("", (b.x, b.y), (a.x, a.y),
                                          arrowprops={"arrowstyle": "->", "color": color, "lw": 2}, zorder=4)
                    route_text = f"{route['origin']} → {route['destination']}"
                    member_name = next((name for _, name, node in locations[route[endpoint]] if node == chosen), str(chosen))
                    handles.append(Line2D([], [], color=color, linewidth=2,
                                          label=f"{route_text}: usa {member_name} (OSM {chosen}) — proposta pela topologia dirigida"))
        for position, (label, point) in enumerate(map_config["points"].items()):
            if label not in selected_labels:
                continue
            color = COLORS[position % len(COLORS)]
            status = point.get("resolution", {}).get("status", "RESOLVED")
            ambiguous = status != "RESOLVED"
            for xy, marker_label, node in locations[label]:
                axis.scatter(*xy, s=110, c=color, marker="X" if ambiguous else "o",
                             edgecolors="white", linewidths=1.5, zorder=5)
                axis.annotate(marker_label, xy, xytext=(8, 10), textcoords="offset points",
                              fontsize=17, weight="bold", color=color,
                              bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85}, zorder=6)
                if zoom:
                    axis.annotate(f"OSM {node}", xy, xytext=(8, -17), textcoords="offset points", fontsize=8,
                                  bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85}, zorder=6)
            legend = f"{label} — {point['intersection']} [{status}]"
            handles.append(Line2D([], [], color=color, marker="o", linestyle="none",
                                  label=textwrap.fill(legend, 86)))
        if map_config.get("center") and not zoom:
            center = map_config["center"]
            axis.scatter(*transformer.transform(center["longitude"], center["latitude"]),
                         marker="+", c="#333333", s=100, zorder=4)
        title = f"{map_config['id']} — validação dos pontos"
        if zoom:
            title += f" — {', '.join(selected_labels)}"
        axis.set_title(title, fontsize=16, pad=15)
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .028), fontsize=9, frameon=False)
        bottom = min(.30, .065 + .038 * len(handles))
        fig.subplots_adjust(bottom=bottom, top=.93, left=.04, right=.96)
        if zoom:
            # As duas vias pesquisadas têm prioridade; rótulos vizinhos não as ocultam.
            priority_names = set().union(*(group for label in selected_labels
                                           for group in street_queries(map_config["points"][label])))
            def priority(name):
                return any(normalize_street_name(part) in priority_names for part in name.split(" / "))
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            occupied = [label.get_window_extent(renderer).expanded(1.1, 1.2)
                        for label in axis.texts if label.get_text()]
            frame = axis.get_window_extent(renderer)
            used = set()
            for geometry, name, _ in sorted(visible, key=lambda item: (not priority(item[1]), -item[0].length)):
                if not name or name in used:
                    continue
                clipped = geometry.intersection(view)
                if clipped.length == 0:
                    continue
                for fraction in (.5, .25, .75):
                    position = clipped.interpolate(fraction, normalized=True)
                    label = axis.text(position.x, position.y, textwrap.fill(name, 32), fontsize=7,
                                      weight="bold" if priority(name) else "normal", color="#354650", ha="center",
                                      bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85}, zorder=2)
                    extent = label.get_window_extent(renderer).expanded(1.05, 1.2)
                    inside = frame.contains(extent.x0, extent.y0) and frame.contains(extent.x1, extent.y1)
                    if inside and not any(extent.overlaps(previous) for previous in occupied):
                        occupied.append(extent)
                        used.add(name)
                        break
                    label.remove()
                if len(used) >= 10:
                    break
        fig.text(.02, .008, "Fonte: OpenStreetMap • nós da rede drive • candidatos ambíguos não são pontos confirmados",
                 fontsize=7, color="#52616b")
        fig.savefig(destination, dpi=300, facecolor="white")
        plt.close(fig)

    paths = [output / f"{map_config['id']}_points.png"]
    draw(paths[0], list(map_config["points"]))
    for label in map_config["points"]:
        destination = output / f"{map_config['id']}_{label}.png"
        draw(destination, [label], zoom=True)
        paths.append(destination)
    return paths
