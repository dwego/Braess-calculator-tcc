"""Configuração declarativa de mapas, pontos e direções, sem acesso à rede."""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_SOLVER = {
    "relative_gap_tolerance": 5e-4,
    "max_iterations": 1000,
    "line_search_tolerance": 1e-10,
}
DEFAULT_REMOVALS = {
    "limit": 10,
    "minimum_flow": 40.0,
    "excluded_highway_types": ["service"],
    "numerical_tolerance": 1e-6,
}
DEFAULT_POINT_RESOLUTION = {
    "maximum_intersection_error_m": 100.0,
    "candidate_cluster_m": 100.0,
    "radius_step_m": 500,
    "max_radius_m": 15000,
    "search_radius_m": 15000,
    "zoom_radius_m": 300.0,
}


def _number(value: Any, name: str, *, minimum: float = 0, strict: bool = True) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (value <= minimum if strict else value < minimum)
    ):
        raise ValueError(f"{name}: número finito {'>' if strict else '>='} {minimum} esperado.")


def _identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError(f"{name}: use apenas letras ASCII, números, '_' e '-'.")


def _coordinates(point: dict, name: str, *, required: bool) -> None:
    if not isinstance(point, dict):
        raise ValueError(f"{name}: objeto com latitude e longitude esperado.")
    lat, lon = point.get("latitude"), point.get("longitude")
    if lat is None and lon is None and not required:
        return
    for value, bound, field in [(lat, 90, "latitude"), (lon, 180, "longitude")]:
        _number(value, f"{name}.{field}", minimum=-bound, strict=False)
        if value > bound:
            raise ValueError(f"{name}.{field}: fora do intervalo permitido.")


def point_members(point: dict) -> list[dict]:
    """Um ponto simples possui um membro; um complexo mantém todos os seus nós."""
    return point.get("nodes", []) if point.get("type") == "junction_group" else [point]


def route_node(points: dict, route: dict, endpoint: str) -> int:
    point = points[route[endpoint]]
    members = point_members(point)
    selected = route.get(f"{endpoint}_node")
    if selected is None:
        if point.get("type") == "junction_group":
            raise ValueError(f"{route['id']}: selecione {endpoint}_node após validar os sentidos do grupo.")
        selected = point["node_id"]
    if selected not in {member["node_id"] for member in members}:
        raise ValueError(f"{route['id']}: {endpoint}_node não pertence ao ponto {route[endpoint]}.")
    return selected


def remap_route_nodes(routes: list[dict], old_points: dict, new_points: dict) -> list[dict]:
    """Preserva o membro escolhido ao reconstruir uma rede cujos IDs mudaram."""
    remapped = deepcopy(routes)
    for route in remapped:
        for endpoint in ("origin", "destination"):
            label = route[endpoint]
            ids = {old.get("node_id"): new.get("node_id")
                   for old, new in zip(point_members(old_points[label]), point_members(new_points[label]))}
            field = f"{endpoint}_node"
            if field in route and route[field] in ids:
                route[field] = ids[route[field]]
    return remapped


def validate_config(config: dict, *, require_coordinates: bool = True) -> dict:
    """Valida antes de baixar mapas ou criar saídas; retorna cópia com defaults."""
    if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
            or config["schema_version"] != 1):
        raise ValueError("schema_version deve ser 1.")
    if config.keys() - {"schema_version", "solver", "removals", "urban", "images", "demands", "maps", "point_resolution"}:
        raise ValueError("Campos desconhecidos na configuração.")
    result = deepcopy(config)
    if "point_resolution" in result:
        settings = result["point_resolution"]
        if not isinstance(settings, dict) or settings.keys() - DEFAULT_POINT_RESOLUTION.keys():
            raise ValueError("Campos inválidos em point_resolution.")
        result["point_resolution"] = DEFAULT_POINT_RESOLUTION | settings
        for key, value in result["point_resolution"].items():
            _number(value, f"point_resolution.{key}")
    for key, defaults in [("solver", DEFAULT_SOLVER), ("removals", DEFAULT_REMOVALS)]:
        supplied = result.get(key, {})
        if not isinstance(supplied, dict) or supplied.keys() - defaults.keys():
            raise ValueError(f"Campos inválidos em {key}.")
        result[key] = defaults | supplied
    for key, value in result["solver"].items():
        _number(value, f"solver.{key}")
    if type(result["solver"]["max_iterations"]) is not int:
        raise ValueError("solver.max_iterations deve ser inteiro.")

    removals = result["removals"]
    if removals["limit"] is not None and (type(removals["limit"]) is not int or removals["limit"] <= 0):
        raise ValueError("removals.limit deve ser inteiro positivo ou null (todas).")
    for key in ("minimum_flow", "numerical_tolerance"):
        _number(removals[key], f"removals.{key}", strict=False)
    excluded = removals["excluded_highway_types"]
    if not isinstance(excluded, list) or not all(isinstance(item, str) for item in excluded):
        raise ValueError("excluded_highway_types deve ser uma lista de strings.")

    urban = result.get("urban")
    if not isinstance(urban, dict) or not isinstance(urban.get("capacity_per_lane"), dict):
        raise ValueError("Informe urban.capacity_per_lane e default_capacity_per_lane.")
    if urban.keys() - {"capacity_per_lane", "default_capacity_per_lane", "default_lanes"}:
        raise ValueError("Campos inválidos em urban.")
    _number(urban.get("default_capacity_per_lane"), "urban.default_capacity_per_lane")
    for key, value in urban["capacity_per_lane"].items():
        _number(value, f"capacity_per_lane.{key}")
    urban.setdefault("default_lanes", 1)
    if type(urban["default_lanes"]) is not int or urban["default_lanes"] <= 0:
        raise ValueError("urban.default_lanes deve ser inteiro positivo.")

    images = result.setdefault("images", {"enabled": True})
    if not isinstance(images, dict) or images.keys() - {"enabled", "minimum_active_flow"}:
        raise ValueError("Campos inválidos em images.")
    images.setdefault("enabled", True)
    images.setdefault("minimum_active_flow", 40.0)
    if type(images["enabled"]) is not bool:
        raise ValueError("images.enabled deve ser booleano.")
    _number(images["minimum_active_flow"], "images.minimum_active_flow", strict=False)

    def validate_demands(demands: Any) -> None:
        if not isinstance(demands, list) or not demands:
            raise ValueError("demands deve ser uma lista não vazia.")
        for demand in demands:
            _number(demand, "demand")
        if len(demands) != len(set(demands)):
            raise ValueError("Demandas duplicadas.")

    validate_demands(result.get("demands"))
    maps = result.get("maps")
    if not isinstance(maps, list) or not maps:
        raise ValueError("maps deve ser uma lista não vazia.")
    map_ids = set()
    for map_config in maps:
        if not isinstance(map_config, dict):
            raise ValueError("Cada mapa deve ser um objeto JSON.")
        if map_config.keys() - {"id", "locality", "points", "routes", "margin_m", "max_snap_distance_m",
                                "center", "radius_m", "graphml", "graph_sha256", "removal_edges", "geographic_validation"}:
            raise ValueError("Campos desconhecidos no mapa.")
        map_id = map_config.get("id")
        _identifier(map_id, "map.id")
        if map_id in map_ids:
            raise ValueError(f"Mapa duplicado: {map_id}.")
        map_ids.add(map_id)
        if require_coordinates and map_config.get("geographic_validation", {}).get("status", "RESOLVED") != "RESOLVED":
            raise ValueError(f"{map_id}: validação geográfica incompleta; execute resolve_tcc_points.py.")
        points = map_config.get("points")
        if not isinstance(points, dict) or len(points) < 2:
            raise ValueError(f"{map_id}: informe ao menos dois pontos.")
        for label, point in points.items():
            _identifier(label, "point.label")
            if not isinstance(point, dict) or not isinstance(point.get("intersection"), str):
                raise ValueError(f"{map_id}/{label}: informe intersection.")
            point.setdefault("label", label)
            if point["label"] != label:
                raise ValueError(f"{map_id}/{label}: label deve corresponder à chave do ponto.")
            if point.get("type", "intersection") not in {"intersection", "junction_group"}:
                raise ValueError(f"{map_id}/{label}: type desconhecido.")
            if point.get("type") == "junction_group":
                members = point.get("nodes", [])
                if not isinstance(members, list) or (require_coordinates and len(members) < 2):
                    raise ValueError(f"{map_id}/{label}: junction_group requer ao menos dois membros resolvidos.")
                for index, member in enumerate(members, 1):
                    _coordinates(member, f"{map_id}/{label}{index}", required=require_coordinates)
                    if member.get("node_id") is not None and type(member["node_id"]) is not int:
                        raise ValueError(f"{map_id}/{label}: node_id do membro deve ser inteiro.")
                ids = [member["node_id"] for member in members if member.get("node_id") is not None]
                if len(ids) != len(set(ids)):
                    raise ValueError(f"{map_id}/{label}: membros duplicados.")
            else:
                _coordinates(point, f"{map_id}/{label}", required=require_coordinates)
            if point.get("node_id") is not None and type(point["node_id"]) is not int:
                raise ValueError(f"{map_id}/{label}: node_id deve ser inteiro.")
            if point.get("preferred_node_id") is not None and type(point["preferred_node_id"]) is not int:
                raise ValueError(f"{map_id}/{label}: preferred_node_id deve ser inteiro.")
            for field in ("street_1_aliases", "street_2_aliases"):
                aliases = point.get(field, [])
                if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias.strip() for alias in aliases):
                    raise ValueError(f"{map_id}/{label}: {field} deve ser lista de nomes não vazios.")
        routes = map_config.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ValueError(f"{map_id}: routes deve ser uma lista não vazia.")
        route_ids, directions = set(), set()
        for route in routes:
            if not isinstance(route, dict) or route.keys() - {"id", "origin", "destination", "demands", "origin_node", "destination_node", "node_selection"}:
                raise ValueError("Cada rota deve definir id, origin, destination e, opcionalmente, demands.")
            _identifier(route.get("id"), "route.id")
            origin, destination = route.get("origin"), route.get("destination")
            if origin not in points or destination not in points or origin == destination:
                raise ValueError(f"{map_id}: direção inválida {origin} -> {destination}.")
            if route["id"] in route_ids or (origin, destination) in directions:
                raise ValueError(f"{map_id}: rota duplicada.")
            route_ids.add(route["id"])
            directions.add((origin, destination))
            if "demands" in route:
                validate_demands(route["demands"])
            for endpoint in ("origin", "destination"):
                field = f"{endpoint}_node"
                if field in route and type(route[field]) is not int:
                    raise ValueError(f"{route['id']}: {field} deve ser inteiro.")
                if require_coordinates and points[route[endpoint]].get("type") == "junction_group":
                    route_node(points, route, endpoint)
        map_config.setdefault("margin_m", 1000.0)
        map_config.setdefault("max_snap_distance_m", 300.0)
        _number(map_config["margin_m"], "margin_m")
        _number(map_config["max_snap_distance_m"], "max_snap_distance_m")
        if map_config.get("center") is not None:
            _coordinates(map_config["center"], f"{map_id}.center", required=True)
        if map_config.get("radius_m") is not None:
            _number(map_config["radius_m"], "radius_m")
        if "removal_edges" in map_config:
            if not isinstance(map_config["removal_edges"], list):
                raise ValueError("removal_edges deve ser uma lista de {u, v, key}.")
            edge_ids = set()
            for edge in map_config["removal_edges"]:
                if not isinstance(edge, dict) or set(edge) != {"u", "v", "key"}:
                    raise ValueError("Aresta deve conter exatamente u, v e key.")
                if any(type(value) is not int for value in edge.values()):
                    raise ValueError("u, v e key devem ser inteiros OSM.")
                identity = (edge["u"], edge["v"], edge["key"])
                if identity in edge_ids:
                    raise ValueError("Aresta de remoção duplicada.")
                edge_ids.add(identity)
    return result


def load_config(path: str | Path, *, require_coordinates: bool = True) -> dict:
    config_path = Path(path).resolve()
    with config_path.open(encoding="utf-8") as file:
        config = validate_config(json.load(file), require_coordinates=require_coordinates)
    for map_config in config["maps"]:
        if map_config.get("graphml"):
            map_config["graphml"] = str((config_path.parent / map_config["graphml"]).resolve())
    return config


def scenario_count(config: dict) -> int:
    return sum(
        len(route.get("demands", config["demands"]))
        for map_config in config["maps"] for route in map_config["routes"]
    )


def map_extent(map_config: dict) -> tuple[tuple[float, float], int]:
    """Centro médio e raio geodésico com margem; valida recortes explícitos."""
    coordinates = [(p["latitude"], p["longitude"]) for point in map_config["points"].values()
                   for p in point_members(point)]
    center = map_config.get("center")
    center_lat, center_lon = (
        (center["latitude"], center["longitude"]) if center
        else tuple(sum(p[i] for p in coordinates) / len(coordinates) for i in (0, 1))
    )
    distances = []
    for lat, lon in coordinates:
        phi1, phi2 = math.radians(center_lat), math.radians(lat)
        a = (math.sin((phi2 - phi1) / 2) ** 2
             + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon - center_lon) / 2) ** 2)
        distances.append(6371009 * 2 * math.asin(math.sqrt(min(1, a))))
    farthest = max(distances)
    radius = math.ceil(map_config.get("radius_m") or (farthest + map_config["margin_m"]))
    if radius <= farthest:
        raise ValueError(f"{map_config['id']}: radius_m não contém todos os pontos.")
    return (center_lat, center_lon), radius
