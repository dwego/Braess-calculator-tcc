"""Resolução geométrica de interseções na malha OSM, sem atribuição de tráfego."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree


ABBREVIATIONS = {
    "av": "avenida", "avda": "avenida", "r": "rua", "rod": "rodovia",
    "pres": "presidente", "mal": "marechal", "dr": "doutor",
    "dra": "doutora", "prof": "professor", "eng": "engenheiro", "gen": "general",
}


def normalize_street_name(value: str) -> str:
    text = "".join(char for char in unicodedata.normalize("NFKD", value.lower())
                   if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\b(sp|br)\s*0*(\d+)\b", r"\1 \2", text)
    return " ".join(ABBREVIATIONS.get(word, word) for word in text.split())


def _values(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(";") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [name for item in value for name in _values(item)]
    return []


def street_queries(point: dict) -> tuple[set[str], set[str]]:
    streets = re.split(r"\s+[x×]\s+", point["intersection"], flags=re.IGNORECASE)
    if len(streets) != 2:
        raise ValueError("intersection deve conter duas vias separadas por ' x '.")
    queries = []
    for index, street in enumerate(streets, 1):
        queries.append({normalize_street_name(value) for value in
                        [street, *point.get(f"street_{index}_aliases", [])]})
    return queries[0], queries[1]


@dataclass(frozen=True)
class IntersectionCandidate:
    node_id: int
    latitude: float
    longitude: float
    distance_error_m: float
    method: str


@dataclass(frozen=True)
class IntersectionResolution:
    status: str
    selected: IntersectionCandidate | None
    candidates: list[IntersectionCandidate]
    matched_streets: list[list[str]]
    message: str = ""


class StreetIndex:
    """Indexa name/ref/aliases e mantém distâncias e geometrias em metros."""

    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph
        self.projected = ox.projection.project_graph(graph)
        self.undirected = self.projected.to_undirected()
        self.names = defaultdict(set)
        self.primary_names = defaultdict(set)
        self.original_names = defaultdict(set)
        self.geometries = {}
        for u, v, key, data in self.projected.edges(keys=True, data=True):
            edge = (u, v, key)
            self.geometries[edge] = data.get("geometry") or LineString([
                (self.projected.nodes[node]["x"], self.projected.nodes[node]["y"])
                for node in (u, v)
            ])
            for attribute in ("name", "ref", "alt_name", "official_name", "short_name"):
                for value in _values(data.get(attribute)):
                    normalized = normalize_street_name(value)
                    self.names[normalized].add(edge)
                    if attribute in {"name", "ref"}:
                        self.primary_names[normalized].add(edge)
                    self.original_names[normalized].add(value)

    def _point(self, node: int) -> Point:
        return Point(self.projected.nodes[node]["x"], self.projected.nodes[node]["y"])

    def _candidate(self, node: int, error: float, method: str) -> IntersectionCandidate:
        data = self.graph.nodes[node]
        return IntersectionCandidate(int(node), float(data["y"]), float(data["x"]), float(error), method)

    def _choose(self, candidates, matched, cluster_distance_m, preferred_node_id=None):
        candidates = sorted(candidates, key=lambda item: (item.distance_error_m, item.node_id))
        if not candidates:
            return IntersectionResolution("NOT_FOUND", None, [], matched,
                                          "Sem interseção topologicamente plausível dentro do limite.")
        if preferred_node_id is not None:
            selected = next((item for item in candidates if item.node_id == preferred_node_id), None)
            if selected is not None:
                return IntersectionResolution("RESOLVED", selected, candidates, matched,
                                              "Candidato configurado e confirmado na malha.")
            return IntersectionResolution("AMBIGUOUS", None, candidates, matched,
                                          "preferred_node_id não está entre os candidatos válidos.")
        # Aproximações com erro claramente maior não tornam o melhor encontro ambíguo.
        best_error = candidates[0].distance_error_m
        plausible = [item for item in candidates
                     if item.distance_error_m <= best_error + min(10, cluster_distance_m / 10)]
        # Não agrupa por encadeamento: extremos distantes não viram um único cruzamento.
        diameter = max(self._point(a.node_id).distance(self._point(b.node_id))
                       for a in plausible for b in plausible)
        if diameter > cluster_distance_m:
            return IntersectionResolution("AMBIGUOUS", None, candidates, matched,
                                          f"Candidatos separados por até {diameter:.1f} m; escolha explícita necessária.")
        # Medoide do pequeno conjunto de pistas/alças; desempate determinístico.
        selected = min(plausible, key=lambda candidate: (
            candidate.distance_error_m,
            sum(self._point(candidate.node_id).distance(self._point(other.node_id)) for other in plausible),
            -self.graph.degree(candidate.node_id), candidate.node_id,
        ))
        return IntersectionResolution("RESOLVED", selected, candidates, matched,
                                      "Nó central do conjunto local de candidatos.")

    def resolve(self, point: dict, *, maximum_error_m: float = 100,
                cluster_distance_m: float = 100) -> IntersectionResolution:
        queries = street_queries(point)
        edges = [set().union(*(self.primary_names.get(name) or self.names.get(name, set())
                               for name in group)) for group in queries]
        matched = [sorted(set().union(*(self.original_names.get(name, set()) for name in group)))
                   for group in queries]
        if not all(edges):
            return IntersectionResolution("NOT_FOUND", None, [], matched,
                                          "Uma ou ambas as vias não foram encontradas por name/ref/aliases.")
        # Um name=[rua1, rua2] numa única aresta simplificada não prova interseção.
        shared_edges = edges[0] & edges[1]
        distinct_edges = [group - shared_edges for group in edges]
        nodes = [{node for u, v, _ in group for node in (u, v)} for group in distinct_edges]
        direct_nodes = nodes[0] & nodes[1]
        if direct_nodes:
            candidates = [self._candidate(node, 0, "osm_street_intersection") for node in direct_nodes]
            return self._choose(candidates, matched, cluster_distance_m, point.get("preferred_node_id"))
        if shared_edges:
            return IntersectionResolution("AMBIGUOUS", None, [], matched,
                                          "Nomes agregados na mesma aresta; não há nó comum comprovado.")

        street_geometries = [unary_union([self.geometries[edge] for edge in group]) for group in edges]
        second_edges = sorted(edges[1])
        tree = STRtree([self.geometries[edge] for edge in second_edges])
        plausible_nodes = set()
        for first_edge in sorted(edges[0]):
            geometry = self.geometries[first_edge]
            for index in tree.query(geometry.buffer(maximum_error_m)):
                second_edge = second_edges[int(index)]
                if geometry.distance(self.geometries[second_edge]) > maximum_error_m:
                    continue
                plausible_nodes.update(first_edge[:2])
                plausible_nodes.update(second_edge[:2])
        candidates = []
        for node in sorted(plausible_nodes):
            error = max(self._point(node).distance(geometry) for geometry in street_geometries)
            if error > maximum_error_m:
                continue
            # Cruzamento de geometrias de viaduto/túnel sem ligação local não é interseção.
            other_nodes = nodes[1] if node in nodes[0] else nodes[0]
            reachable = nx.single_source_dijkstra_path_length(
                self.undirected, node, cutoff=maximum_error_m * 3, weight="length",
            )
            if not any(other in reachable for other in other_nodes):
                continue
            candidates.append(self._candidate(node, error, "osm_nearby_connected_streets"))
        return self._choose(candidates, matched, cluster_distance_m, point.get("preferred_node_id"))


def apply_resolution(point: dict, result: IntersectionResolution) -> dict:
    """Mantém nomes originais e remove coordenadas antigas quando não confirmadas."""
    resolved = dict(point)
    for key in ("node_id", "snap_distance_m", "node_latitude", "node_longitude",
                "coordinate_source", "resolution_error"):
        resolved.pop(key, None)
    resolved.update(latitude=None, longitude=None)
    resolved["resolution"] = {
        "status": result.status, "candidate_count": len(result.candidates),
        "matched_streets": result.matched_streets, "message": result.message,
    }
    if point.get("type") == "junction_group":
        requested = [item.get("node_id") for item in point.get("nodes", [])]
        candidates = {item.node_id: item for item in result.candidates}
        members = requested or list(candidates)
        if len(members) >= 2 and all(node in candidates for node in members):
            resolved.pop("latitude", None)
            resolved.pop("longitude", None)
            resolved["nodes"] = [
                dict(label=f"{point['label']}{index}", **{
                    key: value for key, value in asdict(candidates[node]).items()
                    if key in {"latitude", "longitude", "node_id"}
                }) for index, node in enumerate(members, 1)
            ]
            resolved["resolution"].update(
                status="RESOLVED", method="osm_junction_group",
                distance_error_m=max(candidates[node].distance_error_m for node in members),
                message="Grupo de junções solicitado, com todos os membros confirmados na malha.",
            )
        else:
            resolved["nodes"] = []
            resolved["resolution"].update(status="AMBIGUOUS", message="Membros do grupo não confirmados na malha.")
        resolved["resolution"]["candidates"] = [asdict(candidate) for candidate in result.candidates[:20]]
        return resolved
    if result.selected is not None:
        selected = result.selected
        resolved.update(latitude=selected.latitude, longitude=selected.longitude, node_id=selected.node_id)
        resolved["resolution"].update(method=selected.method, distance_error_m=selected.distance_error_m,
                                      intersection_node_id=selected.node_id)
    if len(result.candidates) > 1 or result.status != "RESOLVED":
        resolved["resolution"]["candidates"] = [asdict(candidate) for candidate in result.candidates[:20]]
    return resolved
