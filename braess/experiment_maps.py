"""Preparação explícita de entradas OSM congeladas para a bateria experimental."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox
from pyproj import CRS, Transformer

from braess.experiment_config import map_extent, point_members, remap_route_nodes, route_node, validate_config
from braess.maps.graph_builder import build_graph
from braess.outputs import save_json


def file_sha256(path: str | Path) -> str:
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def resolve_points(config: dict, output_path: str | Path) -> list[str]:
    """Geocoding legado, sem validação; prefira resolve_tcc_points.py.

    Mantido para compatibilidade com chamadas antigas. Nenhum CLI, experimento
    ou etapa de preparação usa este auxiliar.
    """
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


def nearest_point_nodes(graph: nx.MultiDiGraph, points: dict) -> dict:
    """Associa coordenadas a nós em CRS métrico, registrando todas as distâncias."""
    if CRS.from_user_input(graph.graph["crs"]) != CRS.from_epsg(4326):
        raise ValueError("O GraphML de entrada deve usar coordenadas EPSG:4326.")
    projected = ox.projection.project_graph(graph)
    transformer = Transformer.from_crs(graph.graph["crs"], projected.graph["crs"], always_xy=True)
    points = deepcopy(points)
    for label, point in points.items():
        for member in point_members(point):
            x, y = transformer.transform(member["longitude"], member["latitude"])
            node, distance = ox.distance.nearest_nodes(projected, X=x, Y=y, return_dist=True)
            node, distance = int(node), float(distance)
            member.update(node_id=node, snap_distance_m=distance,
                          node_latitude=float(graph.nodes[node]["y"]),
                          node_longitude=float(graph.nodes[node]["x"]))
    return points


def snap_points(graph: nx.MultiDiGraph, map_config: dict, *, require_same_node: bool = True) -> dict:
    """Valida distância; IDs são fixos em snapshots, mas podem mudar numa nova rede."""
    points = nearest_point_nodes(graph, map_config["points"])
    for label, point in points.items():
        for old, member in zip(point_members(map_config["points"][label]), point_members(point)):
            if member["snap_distance_m"] > map_config["max_snap_distance_m"]:
                raise ValueError(f"{map_config['id']}/{label}: nó mais próximo a {member['snap_distance_m']:.1f} m; revise coordenadas/recorte.")
            if require_same_node and old.get("node_id") is not None and old["node_id"] != member["node_id"]:
                raise ValueError(f"{map_config['id']}/{label}: node_id diverge de nearest_nodes; prepare novamente.")
        ids = [member["node_id"] for member in point_members(point)]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{map_config['id']}/{label}: membros do grupo resolvem para o mesmo nó.")
    for route in remap_route_nodes(map_config["routes"], map_config["points"], points):
        if route_node(points, route, "origin") == route_node(points, route, "destination"):
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
        points = snap_points(graph, map_config, require_same_node=bool(map_config.get("graph_sha256")))
        map_config["routes"] = remap_route_nodes(map_config["routes"], map_config["points"], points)
        map_config["points"] = points
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
            "routes": [dict(route, origin_node=route_node(map_config["points"], route, "origin"),
                            destination_node=route_node(map_config["points"], route, "destination"))
                       for route in map_config["routes"]],
        }
        save_json(metadata, directory / "metadata.json")
    config_path = output_directory / "scenarios.json"
    save_json(resolved, config_path)
    return config_path
