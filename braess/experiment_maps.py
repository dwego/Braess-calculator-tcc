"""Preparação explícita de entradas OSM congeladas para a bateria experimental."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox
from pyproj import CRS, Transformer

from braess.experiment_config import map_extent, validate_config
from braess.maps.graph_builder import build_graph
from braess.outputs import save_json


def file_sha256(path: str | Path) -> str:
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def resolve_points(config: dict, output_path: str | Path) -> list[str]:
    """Auxiliar opt-in. Nunca é chamado pelo experimento ou pela preparação."""
    resolved = validate_config(config, require_coordinates=False)
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"A saída já existe: {output_path}")
    failures = []
    for map_config in resolved["maps"]:
        for label, point in map_config["points"].items():
            if point.get("latitude") is not None:
                continue
            query = ", ".join(filter(None, [point["intersection"], map_config.get("locality")]))
            try:
                lat, lon = ox.geocoder.geocode(query)
                point.update(latitude=float(lat), longitude=float(lon))
                point["coordinate_source"] = {
                    "provider": "Nominatim", "query": query,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
                point.pop("resolution_error", None)
            except Exception as error:
                point["resolution_error"] = f"{type(error).__name__}: {error}"
                failures.append(f"{map_config['id']}/{label}")
            # Cada resposta é persistida, inclusive quando o próximo ponto falhar.
            save_json(resolved, output_path)
    save_json(resolved, output_path)
    return failures


def snap_points(graph: nx.MultiDiGraph, map_config: dict) -> dict:
    """Nearest nodes em CRS métrico (SciPy já é dependência), com limite de distância."""
    if CRS.from_user_input(graph.graph["crs"]) != CRS.from_epsg(4326):
        raise ValueError("O GraphML de entrada deve usar coordenadas EPSG:4326.")
    projected = ox.projection.project_graph(graph)
    transformer = Transformer.from_crs(graph.graph["crs"], projected.graph["crs"], always_xy=True)
    points = deepcopy(map_config["points"])
    for label, point in points.items():
        x, y = transformer.transform(point["longitude"], point["latitude"])
        node, distance = ox.distance.nearest_nodes(projected, X=x, Y=y, return_dist=True)
        node, distance = int(node), float(distance)
        if distance > map_config["max_snap_distance_m"]:
            raise ValueError(f"{map_config['id']}/{label}: nó mais próximo a {distance:.1f} m; revise coordenadas/recorte.")
        if point.get("node_id") is not None and point["node_id"] != node:
            raise ValueError(f"{map_config['id']}/{label}: node_id diverge de nearest_nodes; prepare novamente.")
        point.update(node_id=node, snap_distance_m=distance,
                     node_latitude=float(graph.nodes[node]["y"]),
                     node_longitude=float(graph.nodes[node]["x"]))
    for route in map_config["routes"]:
        if points[route["origin"]]["node_id"] == points[route["destination"]]["node_id"]:
            raise ValueError(f"{map_config['id']}/{route['id']}: origem e destino resolvem para o mesmo nó.")
    return points


def load_map_snapshot(map_config: dict) -> nx.MultiDiGraph:
    path = Path(map_config["graphml"])
    expected = map_config.get("graph_sha256")
    if expected and file_sha256(path) != expected:
        raise ValueError(f"{map_config['id']}: SHA-256 do GraphML diverge da configuração.")
    graph = ox.io.load_graphml(path)
    if not graph.graph.get("simplified"):
        raise ValueError("Use um GraphML OSMnx com simplify=True.")
    if graph.graph.get("network_type", "drive") != "drive":
        raise ValueError("Use um GraphML de uma rede network_type='drive'.")
    if any("cost_function" in data for *_, data in graph.edges(data=True)):
        raise ValueError("Use o GraphML bruto, anterior à atribuição de fluxos/BPR.")
    return graph


def prepare_inputs(config: dict, output_directory: str | Path) -> Path:
    """Baixa/carrega cada mapa uma vez e salva rede bruta, coordenadas e IDs fixos."""
    resolved = validate_config(config)
    extents = [map_extent(item) for item in resolved["maps"]]
    output_directory = Path(output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    for map_config, (center, radius) in zip(resolved["maps"], extents):
        print(f"Preparando {map_config['id']}...", flush=True)
        graph = (load_map_snapshot(map_config) if map_config.get("graphml")
                 else build_graph(center, radius))
        graph.graph["network_type"] = "drive"
        map_config["points"] = snap_points(graph, map_config)
        map_config["center"] = {"latitude": center[0], "longitude": center[1]}
        map_config["radius_m"] = radius
        directory = output_directory / "maps" / map_config["id"]
        directory.mkdir(parents=True)
        snapshot = directory / "network.graphml"
        ox.io.save_graphml(graph, snapshot)
        map_config["graphml"] = str(snapshot.relative_to(output_directory))
        map_config["graph_sha256"] = file_sha256(snapshot)
        metadata = {
            "map_id": map_config["id"], "center": map_config["center"], "radius_m": radius,
            "node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges(),
            "network_type": "drive", "simplify": True,
            "points": map_config["points"], "graph_sha256": map_config["graph_sha256"],
            "nearest_nodes_crs": str(ox.projection.project_graph(graph).graph["crs"]),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "routes": [dict(route, origin_node=map_config["points"][route["origin"]]["node_id"],
                            destination_node=map_config["points"][route["destination"]]["node_id"])
                       for route in map_config["routes"]],
        }
        save_json(metadata, directory / "metadata.json")
    config_path = output_directory / "scenarios.json"
    save_json(resolved, config_path)
    return config_path
