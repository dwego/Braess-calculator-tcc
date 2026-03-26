import osmnx as ox
import networkx as nx

def compute_betweenness(
    D: nx.DiGraph,
    k: int | None = None
) -> dict[int, float]:
    if k is None:
        return nx.betweenness_centrality(
            D,
            weight="travel_time",
            normalized=True
        )
    return nx.betweenness_centrality(
        D,
        k=k,
        weight="travel_time",
        normalized=True,
        seed=42
    )

def save_outputs(
    G: nx.MultiDiGraph,
    gpkg_path: str,
    graphml_path: str,
    png_path: str
) -> None:
    nc = ox.plot.get_node_colors_by_attr(G, "bc", cmap="plasma")
    ox.plot.plot_graph(
        G,
        bgcolor="k",
        node_color=nc,
        node_size=35,
        edge_linewidth=1.5,
        edge_color="#333333",
        save=True,
        filepath=png_path,
        show=False,
        close=True
    )
    ox.io.save_graph_geopackage(G, filepath=gpkg_path)
    ox.io.save_graphml(G, filepath=graphml_path)