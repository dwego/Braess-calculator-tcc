"""Preparação geográfica e relatórios, sem chamar o solver nem testar remoções."""
from __future__ import annotations

import hashlib
import json
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox

from braess.experiment_config import DEFAULT_POINT_RESOLUTION, map_extent, point_members, remap_route_nodes, validate_config
from braess.experiment_maps import file_sha256, nearest_point_nodes
from braess.maps.graph_builder import build_graph
from braess.outputs import save_json, save_records
from braess.point_resolution import StreetIndex, apply_resolution


POINT_FIELDS = ["map_id", "point_label", "member_label", "intersection", "latitude", "longitude", "node_id",
                "snap_distance_m", "resolution_method", "resolution_error_m", "status"]


def select_route_nodes(graph, points: dict, route: dict) -> dict:
    """Propõe membros por caminho dirigido mais curto em metros, sem custos de tráfego."""
    candidates, paths = [], {}
    origins = [member["node_id"] for member in point_members(points[route["origin"]])]
    destinations = [member["node_id"] for member in point_members(points[route["destination"]])]
    for endpoint, ids in [("origin", origins), ("destination", destinations)]:
        explicit = route.get(f"{endpoint}_node")
        if explicit is not None and explicit not in ids:
            raise ValueError(f"{route['id']}: {endpoint}_node={explicit} não pertence ao ponto.")
    for origin in origins:
        for destination in destinations:
            eligible = (route.get("origin_node", origin) == origin and
                        route.get("destination_node", destination) == destination)
            record = {"origin_node": origin, "destination_node": destination,
                      "connected": False, "distance_m": None, "eligible": eligible}
            if origin != destination and nx.has_path(graph, origin, destination):
                path = nx.shortest_path(graph, origin, destination, weight="length")
                length = sum(min(data["length"] for data in graph[u][v].values()) for u, v in zip(path, path[1:]))
                record.update(connected=True, distance_m=float(length))
                paths[(origin, destination)] = path
            candidates.append(record)
    ranked = sorted((item for item in candidates if item["connected"] and item["eligible"]),
                    key=lambda item: item["distance_m"])
    result = deepcopy(route)
    selection = {"method": "shortest_directed_distance", "candidates": candidates, "status": "DISCONNECTED"}
    result["node_selection"] = selection
    if not ranked:
        return result
    if len(ranked) > 1 and ranked[1]["distance_m"] - ranked[0]["distance_m"] <= 5:
        selection["status"] = "AMBIGUOUS"
        return result
    chosen = ranked[0]
    result.update(origin_node=chosen["origin_node"], destination_node=chosen["destination_node"])
    selection.update(status="RESOLVED", distance_m=chosen["distance_m"])
    path = paths[(chosen["origin_node"], chosen["destination_node"])]
    edges = []
    for u, v in zip(path, path[1:]):
        key, data = min(graph[u][v].items(), key=lambda item: (item[1]["length"], str(item[0])))
        edges.append({"u": int(u), "v": int(v), "key": int(key), "name": data.get("name", ""),
                      "highway": data.get("highway", ""), "length": float(data["length"])})
    for endpoint, local_edges in [("origin", edges[:3]), ("destination", edges[-3:])]:
        if points[route[endpoint]].get("type") == "junction_group":
            selection[f"{endpoint}_edges"] = local_edges
    return result


def load_search_graph(locality: str, *, cache_directory: Path, fallback_radius_m: float):
    """Prefere o município inteiro; o fallback usa só o geocoding da localidade."""
    ox.settings.use_cache = True
    ox.settings.useful_tags_way = list(dict.fromkeys([
        *ox.settings.useful_tags_way, "alt_name", "official_name", "short_name", "layer",
    ]))
    spec = {"locality": locality, "network_type": "drive", "simplify": True,
            "retain_all": True, "fallback_radius_m": fallback_radius_m,
            "tags": ox.settings.useful_tags_way}
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:20]
    cache_directory.mkdir(parents=True, exist_ok=True)
    snapshot = cache_directory / f"search-{digest}.graphml"
    provenance_file = snapshot.with_suffix(".json")
    if snapshot.exists() and provenance_file.exists():
        provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
        if provenance["sha256"] != file_sha256(snapshot):
            raise ValueError(f"Cache de busca alterado: {snapshot}")
        print(f"Rede temporária em cache: {snapshot}", flush=True)
        return ox.io.load_graphml(snapshot), provenance
    print(f"Obtendo rede temporária de {locality}...", flush=True)
    provenance = {"locality": locality, "method": "graph_from_place",
                  "downloaded_at": datetime.now(timezone.utc).isoformat()}
    try:
        graph = ox.graph.graph_from_place(locality, network_type="drive", simplify=True, retain_all=True)
    except Exception as error:
        print(f"Consulta por município falhou ({error}); tentando raio de {fallback_radius_m:.0f} m.", flush=True)
        center = ox.geocoder.geocode(locality)
        graph = ox.graph.graph_from_point(center, dist=fallback_radius_m, network_type="drive",
                                          simplify=True, retain_all=True)
        provenance.update(method="graph_from_point", center=list(center), radius_m=fallback_radius_m,
                          place_error=f"{type(error).__name__}: {error}")
    graph.graph["network_type"] = "drive"
    ox.io.save_graphml(graph, snapshot)
    provenance.update(sha256=file_sha256(snapshot), node_count=len(graph), edge_count=graph.number_of_edges())
    save_json(provenance, provenance_file)
    print(f"Rede temporária: {len(graph)} nós, {graph.number_of_edges()} arestas.", flush=True)
    return graph, provenance


def validate_map_routes(map_config: dict, *, radius_step_m: float, max_radius_m: float,
                        graph_builder=None):
    """Expande o recorte até conter pontos/sentidos, sem filtrar componentes."""
    graph_builder = graph_builder or build_graph
    result = deepcopy(map_config)
    for key in ("center", "radius_m", "graphml", "graph_sha256", "geographic_validation"):
        result.pop(key, None)
    center, initial_radius = map_extent(result)
    result["center"] = {"latitude": center[0], "longitude": center[1]}
    print(f"Centro calculado: lat={center[0]:.7f}, lon={center[1]:.7f}", flush=True)
    print(f"Maior distância + margem ({result['margin_m']} m): raio inicial={initial_radius} m", flush=True)
    attempts, final_graph = [], None
    reference_points, requested_routes = deepcopy(result["points"]), deepcopy(result["routes"])
    radius = initial_radius
    if radius > max_radius_m:
        result["geographic_validation"] = {"status": "RADIUS_LIMIT", "initial_radius_m": initial_radius,
                                             "attempts": [], "error": "Raio inicial supera max_radius_m."}
        return result, None
    while radius <= max_radius_m:
        print(f"[{result['id']}] Validando raio={radius} m...", flush=True)
        graph = graph_builder(center, radius)
        final_graph = graph
        points = nearest_point_nodes(graph, result["points"])
        too_far = [label for label, point in points.items()
                   if any(member["snap_distance_m"] > result["max_snap_distance_m"] for member in point_members(point))]
        collapsed = [label for label, point in points.items()
                     if len(point_members(point)) != len({member["node_id"] for member in point_members(point)})]
        for label, point in points.items():
            for member in point_members(point):
                print(f"  {member.get('label', label)}: nó={member['node_id']}, snap={member['snap_distance_m']:.2f} m"
                      + (" — SNAP_TOO_FAR" if label in too_far else ""), flush=True)
        routes, selected_routes = [], []
        for route in remap_route_nodes(requested_routes, reference_points, points):
            selected = select_route_nodes(graph, points, route)
            connected = (route["origin"] not in too_far + collapsed and route["destination"] not in too_far + collapsed
                         and selected["node_selection"]["status"] == "RESOLVED")
            routes.append({"id": route["id"], "origin_node": selected.get("origin_node"),
                           "destination_node": selected.get("destination_node"), "connected": connected,
                           "node_selection": {key: value for key, value in selected["node_selection"].items()
                                              if not key.endswith("_edges")}})
            selected_routes.append(selected)
            print(f"  {route['origin']} -> {route['destination']}: {'OK' if connected else 'NO PATH / SNAP INVÁLIDO / AMBÍGUO'}"
                  f" ({selected.get('origin_node')} -> {selected.get('destination_node')})", flush=True)
            for candidate in selected["node_selection"]["candidates"]:
                print(f"    candidato {candidate['origin_node']} -> {candidate['destination_node']}: "
                      f"{candidate['distance_m']} m, conectado={candidate['connected']}", flush=True)
        attempts.append({"radius_m": radius, "snap_distances_m": {
            member.get("label", label): member["snap_distance_m"]
            for label, point in points.items() for member in point_members(point)},
                         "routes": routes})
        result["points"], result["radius_m"], result["routes"] = points, radius, selected_routes
        complete = not too_far and all(route["connected"] for route in routes)
        ambiguous_routes = (not too_far and not collapsed and
                            all(route["node_selection"]["status"] in {"RESOLVED", "AMBIGUOUS"} for route in routes)
                            and any(route["node_selection"]["status"] == "AMBIGUOUS" for route in routes))
        if complete or ambiguous_routes or radius == max_radius_m:
            for label in too_far:
                result["points"][label].setdefault("resolution", {})["status"] = "SNAP_TOO_FAR"
            for label in collapsed:
                result["points"][label].setdefault("resolution", {})["status"] = "AMBIGUOUS"
            result["geographic_validation"] = {
                "status": ("RESOLVED" if complete else "AMBIGUOUS_ROUTES" if ambiguous_routes
                           else "SNAP_TOO_FAR" if too_far else "ROUTES_DISCONNECTED"),
                "initial_radius_m": initial_radius, "final_radius_m": radius,
                "node_count": len(graph), "edge_count": graph.number_of_edges(),
                "network_type": "drive", "simplify": True, "attempts": attempts,
            }
            print(f"Raio final: {radius} m — {result['geographic_validation']['status']}", flush=True)
            return result, graph
        radius = min(max_radius_m, radius + math.ceil(radius_step_m))
    return result, final_graph


def _records(config: dict) -> list[dict]:
    records = []
    for map_config in config["maps"]:
        for label, point in map_config["points"].items():
            resolution = point.get("resolution", {})
            for member in point_members(point) or [{}]:
                records.append({"map_id": map_config["id"], "point_label": label,
                                "member_label": member.get("label", label),
                                "intersection": point["intersection"], "latitude": member.get("latitude"),
                                "longitude": member.get("longitude"), "node_id": member.get("node_id"),
                                "snap_distance_m": member.get("snap_distance_m"),
                                "resolution_method": resolution.get("method"),
                                "resolution_error_m": resolution.get("distance_error_m"),
                                "status": resolution.get("status", "NOT_FOUND")})
    return records


def resolve_configuration(config: dict, output_config: Path, output_directory: Path, *,
                          search_graphml: Path | None = None, in_place: bool = False,
                          cache_directory: Path = Path("cache/tcc-point-resolution")) -> dict:
    resolved = validate_config(config, require_coordinates=False)
    settings = DEFAULT_POINT_RESOLUTION | resolved.get("point_resolution", {})
    resolved["point_resolution"] = settings
    output_config, output_directory = output_config.resolve(), output_directory.resolve()
    if output_config.exists() and not in_place:
        raise FileExistsError(f"O JSON de saída já existe: {output_config}")
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError(f"Use um diretório de imagens novo: {output_directory}")
    output_directory.mkdir(parents=True, exist_ok=True)
    if in_place and output_config.exists():
        backup = output_config.with_name(output_config.name + "." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".bak")
        backup.write_bytes(output_config.read_bytes())
    sources = {}
    errors = []
    image_paths = []
    for position, map_config in enumerate(resolved["maps"]):
        print(f"\n[{map_config['id']}]", flush=True)
        # Resultados antigos não devem sobreviver como dados aparentemente confirmados.
        for key in ("center", "radius_m", "graphml", "graph_sha256", "geographic_validation"):
            map_config.pop(key, None)
        locality = map_config.get("locality")
        graph = None
        try:
            source_key = str(search_graphml.resolve()) if search_graphml else locality
            if source_key not in sources:
                if search_graphml:
                    graph = ox.io.load_graphml(search_graphml)
                    provenance = {"method": "local_graphml", "sha256": file_sha256(search_graphml),
                                  "path": str(search_graphml.resolve())}
                else:
                    if not locality:
                        raise ValueError("Informe locality no mapa ou --search-graphml.")
                    graph, provenance = load_search_graph(locality, cache_directory=cache_directory,
                                                          fallback_radius_m=settings["search_radius_m"])
                sources[source_key] = (graph, StreetIndex(graph), provenance)
            graph, index, provenance = sources[source_key]
            for label, point in map_config["points"].items():
                result = index.resolve(point, maximum_error_m=settings["maximum_intersection_error_m"],
                                       cluster_distance_m=settings["candidate_cluster_m"])
                map_config["points"][label] = apply_resolution(point, result)
                confirmed = map_config["points"][label]
                print(f"\n{label} — {point['intersection']}\n{confirmed['resolution']['status']}: {confirmed['resolution']['message']}", flush=True)
                for candidate in result.candidates[:20]:
                    chosen = " *" if candidate.node_id in {member.get("node_id") for member in point_members(confirmed)} else ""
                    print(f"  nó={candidate.node_id}, lat={candidate.latitude:.7f}, lon={candidate.longitude:.7f},"
                          f" erro={candidate.distance_error_m:.2f} m{chosen}", flush=True)
            if all(point["resolution"]["status"] == "RESOLVED" for point in map_config["points"].values()):
                map_config, final_graph = validate_map_routes(
                    map_config, radius_step_m=settings["radius_step_m"], max_radius_m=settings["max_radius_m"],
                )
                if final_graph is not None:
                    graph = final_graph
                    graph.graph["network_type"] = "drive"
                    snapshot = output_directory / f"{map_config['id']}.graphml"
                    ox.io.save_graphml(graph, snapshot)
                    map_config["graphml"] = os.path.relpath(snapshot, output_config.parent)
                    map_config["graph_sha256"] = file_sha256(snapshot)
            else:
                map_config["geographic_validation"] = {"status": "INCOMPLETE", "attempts": []}
            map_config["geographic_validation"].update(source=provenance,
                checked_at=datetime.now(timezone.utc).isoformat())
            resolved["maps"][position] = map_config
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            errors.append({"map_id": map_config["id"], "error": message})
            map_config["geographic_validation"] = {"status": "ERROR", "error": message}
            print(f"ERRO: {message}", flush=True)
        if graph is not None:
            try:
                from braess.point_resolution_plots import plot_validation_maps
                paths = plot_validation_maps(graph, map_config, output_directory,
                                              zoom_radius_m=settings["zoom_radius_m"])
                image_paths.extend(str(path) for path in paths)
            except Exception as error:
                errors.append({"map_id": map_config["id"], "error": f"Falha ao gerar imagens: {error}"})
        save_json(resolved, output_config)
        save_records(_records(resolved), output_directory / "resolved_points.csv", fieldnames=POINT_FIELDS)
    summary = {
        "output_config": str(output_config), "images": image_paths, "errors": errors,
        "points": _records(resolved),
        "maps": {item["id"]: item["geographic_validation"]["status"] for item in resolved["maps"]},
    }
    summary["complete"] = not errors and all(status == "RESOLVED" for status in summary["maps"].values())
    save_json(summary, output_directory / "resolution_summary.json")
    return summary
