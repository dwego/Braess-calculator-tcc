from collections import defaultdict
import networkx as nx

def describe_graph_schema(G: nx.MultiDiGraph) -> None:
    print("\n=== ATRIBUTOS DO GRAFO ===")
    for key, value in G.graph.items():
        print(f"{key}: {type(value).__name__}")

    node_keys = set()
    node_types = defaultdict(set)

    for _, data in G.nodes(data=True):
        for key, value in data.items():
            node_keys.add(key)
            node_types[key].add(type(value).__name__)

    print("\n=== ATRIBUTOS DOS NÓS ===")
    for key in sorted(node_keys):
        print(f"{key}: tipos={sorted(node_types[key])}")

    edge_keys = set()
    edge_types = defaultdict(set)

    for _, _, _, data in G.edges(keys=True, data=True):
        for key, value in data.items():
            edge_keys.add(key)
            edge_types[key].add(type(value).__name__)

    print("\n=== ATRIBUTOS DAS ARESTAS ===")
    for key in sorted(edge_keys):
        print(f"{key}: tipos={sorted(edge_types[key])}")