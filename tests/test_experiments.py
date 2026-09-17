import csv
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import networkx as nx
import pytest

from braess import experiment_maps, experiments, removal
from braess.experiment_config import load_config, map_extent, scenario_count, validate_config
from braess.experiment_maps import prepare_inputs, resolve_points
from braess.frank_wolfe import frank_wolfe
from braess.models import EdgeId, ODPair
from braess.removal import RemovalCandidate, run_removal_experiments, run_single_removal
from braess.synthetic import build_braess_network
from run_tcc_experiments import main


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    data = load_config(ROOT / "experiments/example_scenarios.json")
    data["images"]["enabled"] = False
    return data


def read_csv(path):
    with path.open(encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_tcc_configuration_has_all_36_scenarios():
    data = load_config(ROOT / "experiments/tcc_scenarios.json", require_coordinates=False)
    assert scenario_count(data) == 36
    assert [len(m["routes"]) for m in data["maps"]] == [8, 2, 2]
    assert data["demands"] == [2000, 4000, 6000]
    assert {(r["origin"], r["destination"]) for r in data["maps"][0]["routes"]} == {
        ("A", "B"), ("B", "A"), ("A", "C"), ("C", "A"),
        ("A", "D"), ("D", "A"), ("C", "B"), ("B", "C"),
    }
    with pytest.raises(ValueError, match="latitude"):
        validate_config(data)


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_rejects_invalid_demand(config, value):
    config["demands"] = [value]
    with pytest.raises(ValueError, match="demand"):
        validate_config(config)


def test_rejects_duplicate_and_unknown_routes(config):
    config["maps"][0]["routes"].append(deepcopy(config["maps"][0]["routes"][0]))
    with pytest.raises(ValueError, match="duplicada"):
        validate_config(config)
    config["maps"][0]["routes"].pop()
    config["maps"][0]["routes"][0]["origin"] = "unknown"
    with pytest.raises(ValueError, match="direção inválida"):
        validate_config(config)


def test_rejects_path_traversal_in_map_id(config):
    config["maps"][0]["id"] = "../escape"
    with pytest.raises(ValueError, match="map.id"):
        validate_config(config)


@pytest.mark.parametrize("field,value", [("maps", [None]), ("schema_version", True), ("unexpected", 1)])
def test_rejects_malformed_config_structure(config, field, value):
    config[field] = value
    with pytest.raises(ValueError):
        validate_config(config)


def test_extent_and_route_specific_demands(config):
    center, radius = map_extent(config["maps"][0])
    assert center == pytest.approx((-23.18, -45.889))
    assert 600 < radius < 610
    config["maps"][0]["routes"][0]["demands"] = [100, 200, 300]
    assert scenario_count(validate_config(config)) == 4
    config["maps"][0]["radius_m"] = 1
    with pytest.raises(ValueError, match="não contém"):
        map_extent(config["maps"][0])


def test_prepare_freezes_raw_graph_and_preserves_parallel_keys(config, tmp_path, monkeypatch):
    monkeypatch.setattr(experiment_maps, "build_graph", Mock(side_effect=AssertionError("network")))
    frozen_path = prepare_inputs(config, tmp_path / "inputs")
    frozen = load_config(frozen_path)
    map_config = frozen["maps"][0]
    assert map_config["points"]["A"]["node_id"] == 1
    assert map_config["points"]["B"]["node_id"] == 4
    graph = experiment_maps.load_map_snapshot(map_config)
    assert graph.has_edge(1, 2, 0) and graph.has_edge(1, 2, 7)
    assert "cost_function" not in graph[1][2][0]
    metadata = json.loads((tmp_path / "inputs/maps/example/metadata.json").read_text())
    assert metadata["network_type"] == "drive" and metadata["simplify"] is True
    assert metadata["node_count"] == 4 and metadata["edge_count"] == 11
    assert metadata["routes"][0]["origin_node"] == 1
    assert not experiment_maps.build_graph.called
    # Congelar novamente em outro local continua válido e independente do cwd.
    monkeypatch.chdir(tmp_path)
    assert load_config(frozen_path)["maps"][0]["graphml"] == map_config["graphml"]


def test_download_once_per_map_uses_configured_extent(config, tmp_path, monkeypatch):
    source = experiment_maps.load_map_snapshot(config["maps"][0])
    del config["maps"][0]["graphml"]
    builder = Mock(return_value=source)
    monkeypatch.setattr(experiment_maps, "build_graph", builder)
    prepare_inputs(config, tmp_path / "prepared")
    builder.assert_called_once_with(*map_extent(config["maps"][0]))


def test_run_is_offline_reuses_baselines_and_continues_after_bad_edge(config, tmp_path, monkeypatch):
    config["maps"][0]["removal_edges"] = [
        {"u": 1, "v": 2, "key": 999}, {"u": 1, "v": 2, "key": 7}, {"u": 1, "v": 2, "key": 0},
    ]
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    monkeypatch.setattr(experiment_maps, "build_graph", Mock(side_effect=AssertionError("network")))
    monkeypatch.setattr(experiment_maps.ox.geocoder, "geocode", Mock(side_effect=AssertionError("geocoding")))
    baseline_solver = Mock(wraps=experiments.frank_wolfe)
    modified_solver = Mock(wraps=removal.frank_wolfe)
    monkeypatch.setattr(experiments, "frank_wolfe", baseline_solver)
    monkeypatch.setattr(removal, "frank_wolfe", modified_solver)
    output = tmp_path / "results"
    summary = experiments.run_experiments(frozen, output)
    assert summary["completed_scenarios"] == 2
    assert summary["removal_count"] == 6
    assert summary["status"] == "COMPLETED_WITH_ERRORS"
    assert baseline_solver.call_count == 2
    assert modified_solver.call_count == 4
    rows = read_csv(output / "removals.csv")
    assert [r["status"] for r in rows] == ["ERROR", "OK", "OK", "ERROR", "OK", "OK"]
    for row in rows:
        assert float(row["removal_runtime_seconds"]) >= float(row["solver_runtime_seconds"]) >= 0
        assert float(row["baseline_runtime_seconds"]) > 0
        assert row["origin_node"] != row["destination_node"]
    assert rows[0]["solver_runtime_seconds"] == "0.0"
    assert rows[1]["osmid"] == "999"
    assert rows[2]["osmid"] == "102"
    assert float(rows[2]["relative_improvement_percent"]) == pytest.approx(100 * float(rows[2]["relative_improvement"]))
    assert float(rows[2]["absolute_improvement"]) == pytest.approx(float(rows[2]["baseline_tstt"]) - float(rows[2]["modified_tstt"]))
    details = read_csv(output / "scenarios/example/A_to_B/demand-2000/removals/1_2_0/edges.csv")
    assert ("1", "2", "0") not in [(r["u"], r["v"], r["key"]) for r in details]
    assert ("1", "2", "7") in [(r["u"], r["v"], r["key"]) for r in details]
    for row in details:
        expected = float(row["free_flow_time"]) * (1 + float(row["bpr_alpha"]) * float(row["volume_capacity_ratio"]) ** float(row["bpr_beta"]))
        assert float(row["travel_time"]) == pytest.approx(expected)
    assert (output / "inputs/scenarios.json").is_file()
    assert summary["total_experiment_runtime_seconds"] >= sum(float(r["scenario_runtime_seconds"]) for r in read_csv(output / "baselines.csv"))


def test_snapshot_tampering_and_unprepared_runs_are_rejected(config, tmp_path):
    with pytest.raises(ValueError, match="prepare"):
        experiments.run_experiments(config, tmp_path / "unprepared")
    assert not (tmp_path / "unprepared").exists()
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    snapshot = Path(frozen["maps"][0]["graphml"])
    snapshot.write_text(snapshot.read_text() + "\n")
    with pytest.raises(ValueError, match="SHA-256"):
        experiments.run_experiments(frozen, tmp_path / "results")


def test_rejects_distant_or_collapsed_od_points(config, tmp_path):
    distant = deepcopy(config)
    distant["maps"][0]["points"]["A"]["longitude"] = -45
    with pytest.raises(ValueError, match="mais próximo"):
        prepare_inputs(distant, tmp_path / "distant")
    config["maps"][0]["points"]["B"]["longitude"] = config["maps"][0]["points"]["A"]["longitude"]
    with pytest.raises(ValueError, match="mesmo nó"):
        prepare_inputs(config, tmp_path / "collapsed")


def test_resolver_saves_partial_results_and_preserves_fixed_points(config, tmp_path, monkeypatch):
    data = deepcopy(config)
    for point in data["maps"][0]["points"].values():
        point.update(latitude=None, longitude=None)
    geocoder = Mock(side_effect=[(-23.18, -45.890), ValueError("not found")])
    monkeypatch.setattr(experiment_maps.ox.geocoder, "geocode", geocoder)
    output = tmp_path / "resolved.json"
    assert resolve_points(data, output) == ["example/B"]
    resolved = load_config(output, require_coordinates=False)
    assert resolved["maps"][0]["points"]["A"]["longitude"] == -45.890
    assert resolved["maps"][0]["points"]["B"]["latitude"] is None
    geocoder.reset_mock(side_effect=True)
    geocoder.return_value = (-23.18, -45.888)
    assert resolve_points(resolved, tmp_path / "resolved-again.json") == []
    geocoder.assert_called_once()


def test_baseline_failure_does_not_stop_other_directions(config, tmp_path, monkeypatch):
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    real_solver = experiments.frank_wolfe
    calls = 0
    def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("baseline failed")
        return real_solver(*args, **kwargs)
    monkeypatch.setattr(experiments, "frank_wolfe", fail_first)
    output = tmp_path / "results"
    summary = experiments.run_experiments(frozen, output)
    assert summary["completed_scenarios"] == 2
    assert [row["status"] for row in read_csv(output / "baselines.csv")] == ["ERROR", "OK"]


def test_nonconverged_baseline_never_flags_braess(config, tmp_path, monkeypatch):
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    real_solver = experiments.frank_wolfe
    monkeypatch.setattr(experiments, "frank_wolfe", lambda *a, **kw: replace(real_solver(*a, **kw), converged=False))
    output = tmp_path / "results"
    experiments.run_experiments(frozen, output)
    assert all(row["status"] == "NO_CONVERGENCE" and row["possible_braess"] == "False" for row in read_csv(output / "removals.csv"))


def test_plot_failure_does_not_stop_removals(config, tmp_path, monkeypatch):
    config["images"]["enabled"] = True
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    monkeypatch.setattr(experiments, "_export_images", Mock(side_effect=RuntimeError("plot failed")))
    output = tmp_path / "results"
    summary = experiments.run_experiments(frozen, output)
    assert summary["removal_count"] == 4
    assert summary["status"] == "COMPLETED_WITH_ERRORS"
    assert all("plot failed" in row["artifact_errors"] for row in read_csv(output / "removals.csv"))


def test_unexpected_removal_failure_does_not_stop_next_candidate(config, tmp_path, monkeypatch):
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    original = experiments.run_single_removal
    calls = 0
    def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("unexpected failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(experiments, "run_single_removal", fail_first)
    output = tmp_path / "results"
    summary = experiments.run_experiments(frozen, output)
    assert summary["removal_count"] == 4
    rows = read_csv(output / "removals.csv")
    assert [row["status"] for row in rows] == ["ERROR", "OK", "OK", "OK"]
    assert float(rows[0]["removal_runtime_seconds"]) > 0


def test_cli_validation_and_no_overwrite(config, tmp_path):
    assert main(["validate", "--config", str(ROOT / "experiments/tcc_scenarios.json")]) == 0
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        prepare_inputs(config, destination)


def test_no_candidates_still_exports_csv_schema(config, tmp_path):
    config["maps"][0]["removal_edges"] = []
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    output = tmp_path / "results"
    summary = experiments.run_experiments(frozen, output)
    assert summary["removal_count"] == 0
    assert read_csv(output / "removals.csv") == []
    assert "baseline_tstt" in (output / "removals.csv").read_text()
    assert "solver_runtime_seconds" in (output / "scenarios/example/A_to_B/demand-2000/removals.csv").read_text()


def test_disconnected_baseline_keeps_od_nodes_without_scc_filter(config, tmp_path, monkeypatch):
    graph = experiment_maps.load_map_snapshot(config["maps"][0])
    graph.remove_edges_from([(u, v, key) for u, v, key in graph.edges(keys=True) if u > v])
    config["maps"][0].pop("graphml")
    monkeypatch.setattr(experiment_maps, "build_graph", Mock(return_value=graph))
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    solver = Mock(wraps=experiments.frank_wolfe)
    monkeypatch.setattr(experiments, "frank_wolfe", solver)
    output = tmp_path / "results"
    experiments.run_experiments(frozen, output)
    rows = read_csv(output / "baselines.csv")
    assert [row["status"] for row in rows] == ["OK", "DISCONNECTED"]
    assert rows[1]["origin_node"] == "4" and rows[1]["destination_node"] == "1"
    assert rows[1]["baseline_runtime_seconds"] == "0.0"
    assert solver.call_count == 1


def test_full_36_scenario_schedule_on_offline_fixture(tmp_path, monkeypatch):
    config = load_config(ROOT / "experiments/tcc_scenarios.json", require_coordinates=False)
    config["images"]["enabled"] = False
    config["removals"]["limit"] = 1
    coordinates = {"A": (-23.180, -45.890), "B": (-23.179, -45.889),
                   "C": (-23.181, -45.889), "D": (-23.180, -45.888)}
    for map_config in config["maps"]:
        map_config["graphml"] = str(ROOT / "experiments/example_network.graphml")
        for label, point in map_config["points"].items():
            # Este teste isola a programação de 36 cenários; grupos têm testes próprios.
            point.pop("type", None)
            point.pop("nodes", None)
            point["latitude"], point["longitude"] = coordinates[label]
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    solver = Mock(wraps=experiments.frank_wolfe)
    monkeypatch.setattr(experiments, "frank_wolfe", solver)
    output = tmp_path / "results"
    summary = experiments.run_experiments(frozen, output)
    assert summary["completed_scenarios"] == summary["removal_count"] == 36
    assert solver.call_count == 36
    rows = read_csv(output / "baselines.csv")
    assert len({(row["map_id"], row["od_pair_id"], row["demand"]) for row in rows}) == 36
    assert {row["demand"] for row in rows} == {"2000", "4000", "6000"}


def test_disconnected_and_failed_removals_have_separate_timings(monkeypatch):
    graph = build_braess_network(include_connector=True)
    od_pairs = [ODPair("O", "D", 4000)]
    baseline = frank_wolfe(graph, od_pairs)
    candidate = RemovalCandidate(EdgeId("A", "B", 0), 4000, "test", "synthetic")
    ticks = iter([10.0, 11.0, 13.0, 15.0])
    monkeypatch.setattr(removal, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(removal, "frank_wolfe", Mock(side_effect=RuntimeError("solver failed")))
    result = run_single_removal(graph, od_pairs, baseline, candidate, relative_gap_tolerance=1e-6, max_iterations=10)
    assert result.status == "ERROR" and result.connected
    assert result.total_runtime_seconds == 5
    assert result.solver_runtime_seconds == 2
    single = nx.MultiDiGraph()
    single.add_edge("O", "D", key=0)
    ticks = iter([20.0, 23.0])
    result = run_single_removal(single, od_pairs, baseline, replace(candidate, edge=EdgeId("O", "D", 0)), relative_gap_tolerance=1e-6, max_iterations=10)
    assert result.status == "DISCONNECTED" and not result.connected
    assert result.total_runtime_seconds == 3 and result.solver_runtime_seconds == 0


def test_copy_failure_is_captured_and_next_removal_runs(monkeypatch):
    graph = build_braess_network(include_connector=True)
    od_pairs = [ODPair("O", "D", 4000)]
    baseline = frank_wolfe(graph, od_pairs)
    candidate = RemovalCandidate(EdgeId("A", "B", 0), 4000, "test", "synthetic")
    copier = Mock(side_effect=[RuntimeError("copy failed"), deepcopy(graph)])
    monkeypatch.setattr(removal, "deepcopy", copier)
    results = run_removal_experiments(graph, od_pairs, baseline, [candidate, candidate], relative_gap_tolerance=1e-6, max_iterations=100)
    assert [result.status for result in results] == ["ERROR", "OK"]
    assert results[0].total_runtime_seconds > 0
    assert results[1].possible_braess
