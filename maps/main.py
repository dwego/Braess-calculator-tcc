import networkx as nx

from config import (
    CENTER_POINT,
    DIST_M,
    BETWEENNESS_K,
    GPKG_PATH,
    GRAPHML_PATH,
    PNG_PATH,
)
from utils import run_step, log, eta_after_current
from graph_builder import build_graph, to_digraph_by_travel_time
from analysis import compute_betweenness, save_outputs
from schema_inspector import describe_graph_schema

TOTAL_STEPS = 5
current_step = 0

current_step += 1
G = run_step(
    "Baixar e preparar grafo",
    lambda: build_graph(CENTER_POINT, DIST_M)
)
log(eta_after_current(current_step, TOTAL_STEPS))

current_step += 1
describe_graph_schema(G)
log(eta_after_current(current_step, TOTAL_STEPS))

current_step += 1
D = run_step(
    "Converter para DiGraph",
    lambda: to_digraph_by_travel_time(G)
)
log(eta_after_current(current_step, TOTAL_STEPS))

current_step += 1
bc = run_step(
    "Calcular betweenness centrality",
    lambda: compute_betweenness(D, BETWEENNESS_K)
)
nx.set_node_attributes(G, bc, "bc")
log(eta_after_current(current_step, TOTAL_STEPS))

current_step += 1
run_step(
    "Salvar saídas",
    lambda: save_outputs(G, GPKG_PATH, GRAPHML_PATH, PNG_PATH)
)

log("Tudo pronto.")