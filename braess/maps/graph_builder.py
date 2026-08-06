import osmnx as ox
import networkx as nx

ox.settings.use_cache = True

def build_graph(center_point: tuple[float, float], dist_m: int) -> nx.MultiDiGraph:
    G = ox.graph_from_point(
        center_point,
        dist=dist_m,
        network_type="drive",
        simplify=True
    )
    G = ox.routing.add_edge_speeds(G)
    G = ox.routing.add_edge_travel_times(G)
    return G

def to_digraph_by_travel_time(G: nx.MultiDiGraph) -> nx.DiGraph:
    return ox.convert.to_digraph(G, weight="travel_time")