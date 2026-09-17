"""Bateria de cenários independentes: um baseline por direção e demanda."""
from __future__ import annotations

import platform
import subprocess
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from braess.experiment_config import load_config, scenario_count, validate_config
from braess.experiment_maps import load_map_snapshot, prepare_inputs
from braess.frank_wolfe import FrankWolfeResult, frank_wolfe
from braess.models import EdgeId, ODPair
from braess.outputs import save_edge_results, save_iteration_history, save_json, save_records, save_summary
from braess.removal import RemovalCandidate, RemovalResult, all_od_pairs_are_connected, run_single_removal, select_removal_candidates
from braess.synthetic import update_travel_times
from braess.urban import BPR_PARAMETERS, prepare_urban_graph


REMOVAL_FIELDS = [
    "map_id", "od_pair_id", "direction", "origin_label", "destination_label",
    "origin_node", "destination_node", "demand", "u", "v", "key", "osmid",
    "name", "highway", "length", "lanes", "free_flow_time", "capacity",
    "capacity_source", "bpr_alpha", "bpr_beta", "bpr_link_type", "baseline_flow",
    "baseline_travel_time", "baseline_vc_ratio", "baseline_volume_capacity_ratio",
    "status", "connected", "converged", "error",
    "baseline_tstt", "modified_tstt", "absolute_improvement", "relative_improvement",
    "relative_improvement_percent", "baseline_average_travel_time", "modified_average_travel_time",
    "baseline_beckmann_objective", "modified_beckmann_objective", "baseline_iterations",
    "modified_iterations", "baseline_relative_gap", "modified_relative_gap",
    "baseline_converged", "modified_converged", "possible_braess",
    "baseline_runtime_seconds", "removal_runtime_seconds", "solver_runtime_seconds", "artifact_errors",
]


def _metrics(result: FrankWolfeResult | None, prefix: str) -> dict:
    names = {"tstt": "total_system_travel_time", "average_travel_time": "average_travel_time",
             "beckmann_objective": "beckmann_objective", "iterations": "iterations",
             "relative_gap": "relative_gap", "converged": "converged"}
    return {f"{prefix}_{key}": getattr(result, value) if result else None for key, value in names.items()}


def _export_solution(graph, result, directory: Path, config: dict, title: str) -> list[str]:
    """Uma falha de figura não descarta métricas nem impede outras remoções."""
    errors = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        update_travel_times(graph, result.flows)
    except Exception as error:
        return [f"{type(error).__name__}: {error}"]
    exports = [
        lambda: save_edge_results(graph, result, directory / "edges.csv"),
        lambda: save_iteration_history(result, directory / "convergence.csv"),
        lambda: save_summary(result, directory / "solver.json", extra={"final_relative_gap": result.relative_gap}),
    ]
    if config["images"]["enabled"]:
        exports.extend([
            lambda: _export_images(graph, result, directory, config, title),
        ])
    for export in exports:
        try:
            export()
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
    return errors


def _export_images(graph, result, directory: Path, config: dict, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    from braess.visualization import plot_convergence, plot_urban_flows
    plot_convergence(result, directory / "convergence.png", title=title,
                     tolerance=config["solver"]["relative_gap_tolerance"])
    plot_urban_flows(graph, result.flows, directory / "flows.png", title=title,
                     minimum_active_flow=config["images"]["minimum_active_flow"])


def _candidates(graph, baseline, map_config: dict, config: dict) -> list[RemovalCandidate]:
    if "removal_edges" in map_config:
        candidates = []
        for item in map_config["removal_edges"]:
            edge = EdgeId(**item)
            data = graph.get_edge_data(edge.u, edge.v, edge.key) or {}
            candidates.append(RemovalCandidate(edge, baseline.flows.get(edge, 0.0),
                                               str(data.get("name", "")), str(data.get("highway", ""))))
        return candidates
    options = config["removals"]
    return select_removal_candidates(
        graph, baseline,
        limit=options["limit"] or max(1, graph.number_of_edges()),
        minimum_flow=options["minimum_flow"],
        excluded_highway_types=set(options["excluded_highway_types"]),
    )


def _edge_details(graph, candidate: RemovalCandidate) -> dict:
    edge = candidate.edge
    data = graph.get_edge_data(edge.u, edge.v, edge.key) or {}
    fields = ("osmid", "name", "highway", "length", "lanes", "free_flow_time", "capacity",
              "capacity_source", "bpr_alpha", "bpr_beta", "bpr_link_type")
    details = {key: data.get(key) for key in fields}
    details.update(u=edge.u, v=edge.v, key=edge.key,
                   highway=data.get("highway_normalized", data.get("highway")),
                   lanes=data.get("lanes_normalized", data.get("lanes")),
                   baseline_flow=candidate.baseline_flow,
                   baseline_travel_time=data.get("travel_time"),
                   baseline_vc_ratio=(candidate.baseline_flow / data["capacity"] if data.get("capacity") else None))
    details["baseline_volume_capacity_ratio"] = details["baseline_vc_ratio"]
    return details


def _run_scenario(graph, map_config: dict, route: dict, demand: float, config: dict,
                  directory: Path) -> tuple[dict, list[dict]]:
    started_at = perf_counter()
    points = map_config["points"]
    identity = {
        "map_id": map_config["id"], "od_pair_id": route["id"],
        "direction": f"{route['origin']} -> {route['destination']}",
        "origin_label": route["origin"], "destination_label": route["destination"],
        "origin_node": points[route["origin"]]["node_id"],
        "destination_node": points[route["destination"]]["node_id"], "demand": demand,
    }
    baseline = None
    baseline_runtime = 0.0
    removals = []
    artifact_errors = []
    connected = False
    status, error = "ERROR", None
    try:
        od_pairs = [ODPair(identity["origin_node"], identity["destination_node"], demand)]
        connected = all_od_pairs_are_connected(graph, od_pairs)
        if not connected:
            status = "DISCONNECTED"
            error = "Par O-D desconectado na rede original."
        else:
            baseline_started = perf_counter()
            try:
                baseline = frank_wolfe(graph, od_pairs, **config["solver"])
            finally:
                baseline_runtime = perf_counter() - baseline_started
            status = "OK" if baseline.converged else "NO_CONVERGENCE"
            artifact_errors.extend(_export_solution(graph, baseline, directory / "baseline", config,
                                                    f"{map_config['id']} | {identity['direction']} | {demand} veíc/h"))
            for index, candidate in enumerate(_candidates(graph, baseline, map_config, config), 1):
                print(f"  remoção {index}: {candidate.edge}", flush=True)
                removal_started = perf_counter()
                try:
                    result = run_single_removal(
                        graph, od_pairs, baseline, candidate, **config["solver"],
                        numerical_tolerance=config["removals"]["numerical_tolerance"],
                    )
                except Exception as exception:
                    # Falhas inesperadas também não interrompem as próximas candidatas.
                    result = RemovalResult(
                        candidate=candidate, connected=False, solver_result=None,
                        error=f"{type(exception).__name__}: {exception}",
                        baseline_tstt=baseline.total_system_travel_time, modified_tstt=None,
                        absolute_improvement=None, relative_improvement=None, possible_braess=False,
                        status="ERROR", total_runtime_seconds=perf_counter() - removal_started,
                    )
                row = identity | _edge_details(graph, candidate) | {
                    "status": result.status, "connected": result.connected,
                    "converged": bool(result.solver_result and result.solver_result.converged),
                    "error": result.error,
                    **_metrics(baseline, "baseline"), **_metrics(result.solver_result, "modified"),
                    "absolute_improvement": result.absolute_improvement,
                    "relative_improvement": result.relative_improvement,
                    "relative_improvement_percent": (100 * result.relative_improvement
                                                       if result.relative_improvement is not None else None),
                    "possible_braess": result.possible_braess,
                    "baseline_runtime_seconds": baseline_runtime,
                    "removal_runtime_seconds": result.total_runtime_seconds,
                    "solver_runtime_seconds": result.solver_runtime_seconds,
                }
                removal_directory = directory / "removals" / f"{candidate.edge.u}_{candidate.edge.v}_{candidate.edge.key}"
                row["artifact_errors"] = []
                if result.solver_result is not None:
                    try:
                        # A cópia para exportação fica fora do tempo do experimento.
                        modified_graph = graph.copy()
                        modified_graph.remove_edge(candidate.edge.u, candidate.edge.v, candidate.edge.key)
                        row["artifact_errors"] = _export_solution(
                            modified_graph, result.solver_result, removal_directory, config,
                            f"{identity['direction']} | remoção ({candidate.edge.u}, {candidate.edge.v}, {candidate.edge.key})",
                        )
                    except Exception as exception:
                        row["artifact_errors"].append(f"{type(exception).__name__}: {exception}")
                removals.append(row)
                try:
                    save_json(row, removal_directory / "result.json")
                    save_records(removals, directory / "removals.csv", fieldnames=REMOVAL_FIELDS)
                except Exception as exception:
                    row["artifact_errors"].append(f"{type(exception).__name__}: {exception}")
                artifact_errors.extend(row["artifact_errors"])
    except Exception as exception:
        status, error = "ERROR", f"{type(exception).__name__}: {exception}"
    summary = identity | _metrics(baseline, "baseline") | {
        "status": status, "connected": connected, "error": error,
        "converged": bool(baseline and baseline.converged),
        "iterations": baseline.iterations if baseline else None,
        "final_relative_gap": baseline.relative_gap if baseline else None,
        "total_system_travel_time": baseline.total_system_travel_time if baseline else None,
        "average_travel_time": baseline.average_travel_time if baseline else None,
        "beckmann_objective": baseline.beckmann_objective if baseline else None,
        "total_demand": demand, "baseline_runtime_seconds": baseline_runtime,
        "scenario_runtime_seconds": perf_counter() - started_at,
        "removal_count": len(removals), "possible_braess_count": sum(r["possible_braess"] for r in removals),
        "artifact_errors": artifact_errors,
    }
    save_records(removals, directory / "removals.csv", fieldnames=REMOVAL_FIELDS)
    save_json(summary, directory / "summary.json")
    return summary, removals


def _revision() -> dict:
    repository = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repository, text=True).strip())
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def run_experiments(config: dict, output_directory: str | Path) -> dict:
    """Executa somente entradas congeladas; nunca faz geocoding ou baixa OSM."""
    config = validate_config(config)
    for map_config in config["maps"]:
        if not map_config.get("graphml") or not map_config.get("graph_sha256") or any(
            point.get("node_id") is None for point in map_config["points"].values()
        ):
            raise ValueError("Execute 'prepare' primeiro e use o scenarios.json produzido.")
    started_at = perf_counter()
    output_directory = Path(output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    # Inclui cópias portáveis das redes brutas, coordenadas e parâmetros usados.
    frozen_path = prepare_inputs(config, output_directory / "inputs")
    frozen = load_config(frozen_path)
    metadata = {
        "started_at": datetime.now(timezone.utc).isoformat(), "code": _revision(),
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("networkx", "osmnx", "numpy", "scipy", "matplotlib", "pyproj")},
        "bpr_parameters": BPR_PARAMETERS, "scenario_count": scenario_count(frozen),
        "units": {"flow": "vehicles/hour", "travel_time": "seconds", "tstt": "vehicles*seconds/hour", "runtime": "seconds"},
    }
    save_json(metadata | {"status": "RUNNING"}, output_directory / "experiment.json")
    scenarios, removals = [], []
    for map_config in frozen["maps"]:
        graph = prepare_urban_graph(load_map_snapshot(map_config), **frozen["urban"])
        for route in map_config["routes"]:
            for demand in route.get("demands", frozen["demands"]):
                print(f"[{len(scenarios) + 1}/{metadata['scenario_count']}] {map_config['id']}/{route['id']} | {demand} veíc/h", flush=True)
                directory = output_directory / "scenarios" / map_config["id"] / route["id"] / f"demand-{demand}"
                summary, results = _run_scenario(graph, map_config, route, demand, frozen, directory)
                scenarios.append(summary)
                removals.extend(results)
                save_records(scenarios, output_directory / "baselines.csv")
                save_records(removals, output_directory / "removals.csv", fieldnames=REMOVAL_FIELDS)
    groups = []
    for map_config in frozen["maps"]:
        rows = [row for row in removals if row["map_id"] == map_config["id"]]
        groups.append({"map_id": map_config["id"], "removals": len(rows),
                       **{status: sum(row["status"] == status for row in rows)
                          for status in ("OK", "DISCONNECTED", "NO_CONVERGENCE", "ERROR")},
                       "possible_braess": sum(row["possible_braess"] for row in rows)})
    save_records(groups, output_directory / "aggregated.csv")
    has_errors = any(row["status"] == "ERROR" or row["artifact_errors"] for row in [*scenarios, *removals])
    metadata.update(
        status="COMPLETED_WITH_ERRORS" if has_errors else "COMPLETED",
        completed_at=datetime.now(timezone.utc).isoformat(),
        completed_scenarios=len(scenarios), removal_count=len(removals),
        baseline_status_counts=dict(Counter(row["status"] for row in scenarios)),
        removal_status_counts=dict(Counter(row["status"] for row in removals)),
        possible_braess_count=sum(row["possible_braess"] for row in removals),
        total_experiment_runtime_seconds=perf_counter() - started_at,
    )
    save_json(metadata, output_directory / "experiment.json")
    return metadata
