import csv
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import networkx as nx
import pytest

from braess import experiment_maps, experiments
from braess.experiment_config import load_config, scenario_count, select_scenarios
from braess.experiment_maps import prepare_inputs
from braess.models import ODPair
from run_tcc_experiments import main


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return load_config(ROOT / "experiments/example_scenarios.json")


def rows(path):
    with path.open() as file:
        return list(csv.DictReader(file))


def test_filters_intersect_route_demands_without_mutating_input(config):
    config["demands"] = [2000, 4000]
    config["maps"][0]["routes"][0].update(demands=[6000], origin_node=1, destination_node=4)
    config["maps"].append(deepcopy(config["maps"][0]))
    config["maps"][1]["id"] = "other"
    before = deepcopy(config)
    selected = select_scenarios(config, map_id="example", route_id="A_to_B", demand=6000.0,
                                candidate_limit=3, plot_level="baseline")
    assert config == before
    assert scenario_count(selected) == 1
    assert selected["demands"] == [6000]
    assert type(selected["demands"][0]) is int
    assert selected["maps"][0]["routes"] == [config["maps"][0]["routes"][0]]
    assert selected["maps"][0]["points"] == config["maps"][0]["points"]
    assert selected["maps"][0]["graphml"] == config["maps"][0]["graphml"]
    assert selected["solver"] == config["solver"]
    assert selected["removals"]["limit"] == 3
    # 2000 exists globally, but the selected route only defines 6000.
    with pytest.raises(ValueError, match="--demand"):
        select_scenarios(config, map_id="example", route_id="A_to_B", demand=2000)
    selected = select_scenarios(config, demand=2000)
    assert scenario_count(selected) == 2
    assert all(item["routes"][0]["id"] == "B_to_A" for item in selected["maps"])
    assert select_scenarios(config) == config


@pytest.mark.parametrize("arguments", [
    ["--map", "missing"], ["--route", "missing"], ["--demand", "123"],
    ["--demand", "nan"], ["--demand", "inf"], ["--demand", "0"],
    ["--candidate-limit", "0"], ["--candidate-limit", "-1"],
    ["--candidate-limit", "1.5"], ["--plot-level", "invalid"],
])
def test_invalid_cli_selection_does_not_start_run(arguments, tmp_path, monkeypatch):
    runner = Mock(side_effect=AssertionError("Must reject before execution"))
    monkeypatch.setattr(experiments, "run_experiments", runner)
    output = tmp_path / "results"
    with pytest.raises(SystemExit) as error:
        main(["run", "--config", str(ROOT / "experiments/example_scenarios.json"),
              "--output", str(output), *arguments])
    assert error.value.code == 2
    runner.assert_not_called()
    assert not output.exists()


def test_filtered_validation_and_resolver_rejects_unsupported_flags(capsys):
    path = str(ROOT / "experiments/tcc_scenarios.json")
    arguments = ["--config", path, "--map", "mapa_1", "--route", "A_to_B", "--demand", "2000"]
    assert main(["validate", *arguments]) == 0
    assert "1 cenário(s)-base" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(["resolve-points", *arguments])
    assert error.value.code == 2


@pytest.mark.parametrize("route_id,origin,destination", [
    ("A_to_B", 1425164988, 2024367595),
    ("B_to_A", 2024367595, 1425156870),
])
def test_cli_single_scenario_preserves_directional_group_nodes(config, tmp_path, monkeypatch,
                                                               route_id, origin, destination):
    # Synthetic geometry with the real member IDs: tests binding, not real traffic.
    original = experiment_maps.load_map_snapshot(config["maps"][0])
    node_ids = {1: 1425156870, 2: 1425164988, 4: 2024367595}
    graph = nx.relabel_nodes(original, node_ids)
    snapshot = tmp_path / "group.graphml"
    experiment_maps.ox.io.save_graphml(graph, snapshot)
    map_config = config["maps"][0]
    map_config.update(id="mapa_2", graphml=str(snapshot))
    map_config["points"]["A"] = {
        "label": "A", "intersection": "Synthetic interchange", "type": "junction_group",
        "nodes": [{"label": f"A{index}", "node_id": node,
                   "latitude": graph.nodes[node]["y"], "longitude": graph.nodes[node]["x"]}
                  for index, node in enumerate((1425156870, 1425164988), 1)],
    }
    map_config["routes"][0].update(origin_node=1425164988, destination_node=2024367595)
    map_config["routes"][1].update(origin_node=2024367595, destination_node=1425156870)
    explicit = [(1, 2, 7), (1, 2, 0), (1, 3, 0), (2, 4, 0)]
    map_config["removal_edges"] = [{"u": node_ids.get(u, u), "v": node_ids.get(v, v), "key": key}
                                   for u, v, key in explicit]
    config["demands"] = [2000, 4000]
    frozen = load_config(prepare_inputs(config, tmp_path / "prepared"))
    # An unrelated unresolved map must not prevent the selected map from running.
    unresolved = deepcopy(frozen["maps"][0])
    unresolved.update(id="unresolved", geographic_validation={"status": "INCOMPLETE"})
    unresolved["points"]["B"].update(latitude=None, longitude=None)
    frozen["maps"].append(unresolved)
    input_path = tmp_path / "scenarios.json"
    input_path.write_text(json.dumps(frozen))
    before = input_path.read_bytes()
    baseline_solver = Mock(wraps=experiments.frank_wolfe)
    removal_runner = Mock(wraps=experiments.run_single_removal)
    monkeypatch.setattr(experiments, "frank_wolfe", baseline_solver)
    monkeypatch.setattr(experiments, "run_single_removal", removal_runner)
    monkeypatch.setattr(experiment_maps, "build_graph", Mock(side_effect=AssertionError("network")))
    output = tmp_path / "smoke"
    assert main(["run", "--config", str(input_path), "--output", str(output),
                 "--map", "mapa_2", "--route", route_id, "--demand", "2000",
                 "--candidate-limit", "3", "--plot-level", "none"]) == 0
    baseline_solver.assert_called_once()
    assert baseline_solver.call_args.args[1] == [ODPair(origin, destination, 2000)]
    assert baseline_solver.call_args.kwargs == config["solver"]
    assert removal_runner.call_count == 3
    assert all(call.args[1] == [ODPair(origin, destination, 2000)] for call in removal_runner.call_args_list)
    metadata = json.loads((output / "experiment.json").read_text())
    assert metadata["scenario_count"] == metadata["completed_scenarios"] == 1
    baseline = rows(output / "baselines.csv")
    assert len(baseline) == 1
    assert (baseline[0]["origin_node"], baseline[0]["destination_node"]) == (str(origin), str(destination))
    selected = load_config(output / "inputs/scenarios.json")
    assert len(selected["maps"]) == len(selected["maps"][0]["routes"]) == 1
    assert len(selected["maps"][0]["points"]["A"]["nodes"]) == 2
    assert len(selected["maps"][0]["removal_edges"]) == 3
    assert (output / f"scenarios/mapa_2/{route_id}/demand-2000/baseline/solver.json").is_file()
    assert not list(output.rglob("*.png"))
    assert input_path.read_bytes() == before


@pytest.mark.parametrize("level,expected_images", [("none", 0), ("baseline", 1), ("all", 2)])
def test_cli_plot_levels_and_automatic_candidate_limit(config, tmp_path, monkeypatch, level, expected_images):
    config["images"]["enabled"] = False  # CLI baseline/all explicitly enable plotting.
    frozen = prepare_inputs(config, tmp_path / "inputs")
    exporter = Mock()
    monkeypatch.setattr(experiments, "_export_images", exporter)
    output = tmp_path / "results"
    assert main(["run", "--config", str(frozen), "--output", str(output), "--map", "example",
                 "--route", "A_to_B", "--demand", "2000", "--candidate-limit", "1",
                 "--plot-level", level]) == 0
    assert exporter.call_count == expected_images
    if expected_images:
        assert exporter.call_args_list[0].args[2].name == "baseline"
    assert len(rows(output / "baselines.csv")) == len(rows(output / "removals.csv")) == 1
    assert len(list(output.rglob("edges.csv"))) == len(list(output.rglob("convergence.csv"))) == 2
    assert load_config(output / "inputs/scenarios.json")["images"]["plot_level"] == level
