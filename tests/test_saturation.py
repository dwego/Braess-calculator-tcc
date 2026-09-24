from copy import deepcopy
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import networkx as nx
import numpy as np
import pytest

from braess.models import EdgeId
from braess.saturation import active_vc_ratios, saturation_metrics
from braess.urban_flow_plots import FLOW_CMAP, UrbanFlowScale, plot_urban_flows

ROOT = Path(__file__).resolve().parents[1]


def test_active_only_statistics_strict_thresholds_and_no_mutation():
    graph = nx.MultiDiGraph()
    flows = {}
    # 100 inactive roads must not dilute the active-edge averages.
    for key, flow in enumerate([40, 80, 100, 150, 200] + [0] * 100):
        graph.add_edge(1, 2, key=key, capacity=100)
        flows[EdgeId(1, 2, key)] = flow
    before, original_flows = deepcopy(graph), flows.copy()
    metrics = saturation_metrics(graph, flows, 40)
    assert metrics["active_edge_count"] == 4
    assert metrics["max_vc_ratio"] == 2
    assert metrics["mean_active_vc_ratio"] == pytest.approx(1.325)
    assert metrics["median_active_vc_ratio"] == 1.25
    for suffix, count in [("0_8", 3), ("1_0", 2), ("1_5", 1)]:
        assert metrics[f"edges_vc_gt_{suffix}"] == count
        assert metrics[f"percent_active_edges_vc_gt_{suffix}"] == count * 25
    assert nx.utils.graphs_equal(graph, before)
    assert flows == original_flows


def test_empty_active_set_is_distinct_from_missing_solution():
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, capacity=100)
    empty = saturation_metrics(graph, {}, 40)
    missing = saturation_metrics(graph, None, 40)
    assert empty["active_edge_count"] == 0
    assert empty["edges_vc_gt_1_0"] == 0
    assert empty["max_vc_ratio"] is None
    assert empty["percent_active_edges_vc_gt_1_0"] is None
    assert missing["active_edge_count"] is None
    assert missing["edges_vc_gt_1_0"] is None


def test_invalid_active_capacity_is_not_silently_reported_as_uncongested():
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, capacity=0)
    with pytest.raises(ValueError, match="inválido"):
        active_vc_ratios(graph, {EdgeId(1, 2, 0): 100}, 40)


def test_fixed_color_scale_across_demand_peaks_and_clipping(tmp_path, monkeypatch):
    from matplotlib.figure import Figure
    from braess.experiment_config import load_config
    from braess.experiment_maps import load_map_snapshot
    graph = load_map_snapshot(load_config(ROOT / "experiments/example_scenarios.json")["maps"][0])
    for _, _, _, data in graph.edges(keys=True, data=True):
        data["capacity"] = 100
    edge = EdgeId(*next(iter(graph.edges(keys=True))))
    captured = []
    monkeypatch.setattr(Figure, "savefig", lambda self, *a, **k: captured.append(self))

    def color(value, maximum):
        plot_urban_flows(graph, {edge: value}, tmp_path / "flow.png",
                         scale=UrbanFlowScale(maximum, maximum / 100, maximum))
        overlay = next(c for c in captured[-1].axes[0].collections if c.get_gid() == "active-flow-overlay")
        return overlay.get_colors()[0]

    np.testing.assert_allclose(color(100, 2000), color(100, 6000))
    np.testing.assert_allclose(color(150, 2000), color(600, 6000))
    # Capacity reached is warm, while low utilization is blue.
    red, green, blue, _ = color(100, 2000)
    assert red > .9 and green > .5 and blue < .3
    assert FLOW_CMAP(0.0)[2] > FLOW_CMAP(0.0)[0]


def test_partial_results_export_saturation_without_braess(tmp_path):
    from braess.experiment_config import load_config, select_scenarios
    from braess.experiment_maps import prepare_inputs
    from braess.experiments import run_experiments

    config = load_config(ROOT / "experiments/example_scenarios.json")
    config["demands"] = [2000, 4000, 6000]
    config["solver"]["max_iterations"] = 1
    config = select_scenarios(config, route_id="A_to_B", candidate_limit=1, plot_level="all")
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    output = tmp_path / "results"
    metadata = run_experiments(frozen, output)
    assert metadata["completed_scenarios"] == metadata["removal_count"] == 3
    baselines = list(csv.DictReader((output / "baselines.csv").open()))
    assert (output / "baselines.csv").read_bytes() == (output / "scenario_summary.csv").read_bytes()
    for row in baselines:
        path = output / "scenarios/example/A_to_B" / f"demand-{row['demand']}"
        summary = json.loads((path / "baseline/summary.json").read_text())
        assert float(row["max_vc_ratio"]) == summary["max_vc_ratio"]
        assert (path / "baseline/vc_distribution.png").exists()
        assert (path / "scenario_summary.csv").exists()
        removal = json.loads(next(path.glob("removals/*/result.json")).read_text())
        assert removal["status"] == "NO_CONVERGENCE"
        assert removal["possible_braess"] is False
        assert removal["iterations"] == 1
        assert removal["final_relative_gap"] >= 0
        assert removal["max_vc_ratio"] > 0
    assert (output / "scenarios/example/A_to_B/vc_demand_comparison.png").exists()
