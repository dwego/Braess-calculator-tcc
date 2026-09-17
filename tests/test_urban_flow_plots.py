from copy import deepcopy
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.figure import Figure
import networkx as nx
import numpy as np
import pytest
from shapely.geometry import LineString

from braess import experiments
from braess.experiment_config import load_config, select_scenarios
from braess.experiment_maps import load_map_snapshot, prepare_inputs
from braess.models import EdgeId
from braess.urban_flow_plots import (
    DELTA_CMAP, FLOW_CMAP, MAXIMUM_LINEWIDTH, UrbanFlowGeometry, UrbanFlowScale, flow_deltas,
    flow_linewidth, plot_delta_flows, plot_urban_flows,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def graph():
    config = load_config(ROOT / "experiments/example_scenarios.json")
    graph = load_map_snapshot(config["maps"][0])
    for _, _, data in graph.edges(data=True):
        data["capacity"] = 1000.0
    return graph


def collection(figure, gid):
    return next(artist for artist in figure.axes[0].collections if artist.get_gid() == gid)


def test_shared_scales_include_modified_peaks_and_removed_negative_delta(graph):
    removed, diverted = EdgeId(1, 2, 0), EdgeId(1, 3, 0)
    baseline, modified = {removed: 800}, {diverted: 2000}
    scale = UrbanFlowScale.from_flows(graph, [baseline, modified], baseline_flows=baseline)
    assert (scale.maximum_flow, scale.maximum_ratio, scale.maximum_delta) == (2000, 2, 2000)
    deltas = flow_deltas(graph, baseline, modified)
    assert deltas[removed] == -800 and deltas[diverted] == 2000
    assert deltas[EdgeId(4, 3, 0)] == 0
    assert baseline == {removed: 800} and modified == {diverted: 2000}
    assert UrbanFlowScale.from_flows(graph, [{}], baseline_flows={}).maximum_delta > 0


def test_linewidth_is_smooth_bounded_and_capped_for_short_segments():
    widths = [flow_linewidth(value, 2000) for value in range(0, 2001, 10)]
    assert widths == sorted(widths)
    assert max(np.diff(widths)) < .03
    assert widths[-1] == pytest.approx(MAXIMUM_LINEWIDTH)
    assert MAXIMUM_LINEWIDTH < 3
    assert flow_linewidth(2000, 2000, length_points=1) <= .45
    assert flow_linewidth(4000, 2000) == MAXIMUM_LINEWIDTH


def test_parallel_offsets_preserve_edge_identity_and_original_graph(graph):
    graph.add_edge(1, 2, key=8, capacity=1000,
                   geometry=LineString([(-45.89, -23.18), (-45.891, -23.178), (-45.889, -23.179)]))
    before = deepcopy(graph)
    geometry = UrbanFlowGeometry(graph)
    parallel = {EdgeId(1, 2, 0), EdgeId(1, 2, 7), EdgeId(2, 1, 0)}
    assert any(set(group) == parallel for group in geometry.parallel_groups)
    assert not any(EdgeId(1, 2, 8) in group for group in geometry.parallel_groups)
    display = geometry.display_geometries(.1)
    assert len({display[edge].normalize().wkb for edge in parallel}) == 3
    assert len(display) == graph.number_of_edges()
    assert display is geometry.display_geometries(.1)
    assert nx.utils.graphs_equal(before, graph)


def test_complete_background_fixed_bounds_od_markers_and_original_removed_geometry(graph, tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(Figure, "savefig", lambda self, *args, **kwargs: captured.append(self))
    before = deepcopy(graph)
    removed = EdgeId(1, 2, 0)
    geometry = UrbanFlowGeometry(graph)
    geometry.focus_on([removed])
    scale = UrbanFlowScale.from_flows(graph, [{removed: 2000}])
    options = dict(geometry=geometry, scale=scale, origin_node=1, destination_node=4,
                   origin_label="A", destination_label="B", minimum_active_flow=1e6)
    plot_urban_flows(graph, {removed: 2000}, tmp_path / "baseline.png", **options)
    modified = graph.copy()
    modified.remove_edge(removed.u, removed.v, removed.key)
    plot_urban_flows(modified, {}, tmp_path / "removed.png", removed_edge=removed, **options)
    for figure in captured:
        assert len(collection(figure, "full-road-network").get_segments()) == graph.number_of_edges()
        assert len(collection(figure, "active-flow-overlay").get_segments()) == 0
        assert {"A", "B"} <= {text.get_text() for text in figure.axes[0].texts}
    assert captured[0].axes[0].get_xlim() == captured[1].axes[0].get_xlim()
    assert captured[0].axes[0].get_ylim() == captured[1].axes[0].get_ylim()
    removed_artist = next(line for line in captured[1].axes[0].lines if line.get_gid() == "removed-edge")
    assert removed_artist.is_dashed()
    np.testing.assert_allclose(removed_artist.get_xydata(), list(geometry.geometries[removed].coords))
    assert nx.utils.graphs_equal(graph, before)


def test_styles_stay_bound_to_edge_ids_and_delta_colors_have_correct_sign(graph, tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(Figure, "savefig", lambda self, *args, **kwargs: captured.append(self))
    geometry = UrbanFlowGeometry(graph)
    baseline = {EdgeId(1, 2, 7): 900, EdgeId(4, 3, 0): 100}
    modified = {EdgeId(1, 2, 7): 100, EdgeId(4, 3, 0): 900}
    scale = UrbanFlowScale.from_flows(graph, [baseline, modified], baseline_flows=baseline)
    plot_urban_flows(graph, baseline, tmp_path / "flows.png", geometry=geometry, scale=scale)
    ordered = [edge for edge in geometry.geometries if baseline.get(edge, 0) > 0]
    expected = [FLOW_CMAP(Normalize(0, scale.maximum_ratio)(baseline[edge] / 1000)) for edge in ordered]
    np.testing.assert_allclose(collection(captured[-1], "active-flow-overlay").get_colors(), expected)
    plot_delta_flows(graph, baseline, modified, tmp_path / "delta.png", geometry=geometry, scale=scale)
    expected = [DELTA_CMAP(TwoSlopeNorm(vmin=-800, vcenter=0, vmax=800)(modified[edge] - baseline[edge]))
                for edge in ordered]
    np.testing.assert_allclose(collection(captured[-1], "delta-flow-overlay").get_colors(), expected)


def test_plotting_changes_no_numeric_exports_and_freezes_shared_scales(tmp_path):
    config = select_scenarios(load_config(ROOT / "experiments/example_scenarios.json"),
                              route_id="A_to_B", candidate_limit=1, plot_level="none")
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    numerical = tmp_path / "numerical"
    experiments.run_experiments(frozen, numerical)
    plotted = tmp_path / "plotted"
    summary = experiments.run_experiments(select_scenarios(frozen, plot_level="all"), plotted)
    assert summary["status"] == "COMPLETED"
    assert summary["completed_scenarios"] == summary["removal_count"] == 1
    for before in (numerical / "scenarios").rglob("*.csv"):
        if before.name in {"edges.csv", "convergence.csv"}:
            assert before.read_bytes() == (plotted / before.relative_to(numerical)).read_bytes()
    metadata = [json.loads(path.read_text()) for path in plotted.rglob("flow_plot.json")]
    assert len(metadata) == 2
    for key in ("scale", "bounds_m", "detail_bounds_m", "origin_node", "destination_node"):
        assert metadata[0][key] == metadata[1][key]
    assert len(list(plotted.rglob("delta_flow.png"))) == 1
    assert len(list(plotted.rglob("flows.png"))) == 2

def test_delta_palette_is_blue_gray_red_and_removal_is_prominent():
    from braess.urban_flow_plots import REMOVED_LINEWIDTH
    blue, neutral, red = [DELTA_CMAP(value)[:3] for value in (0.0, .5, 1.0)]
    assert blue[2] > blue[0] + .4
    assert red[0] > red[2] + .4
    assert max(neutral) - min(neutral) < .03
    assert .6 < min(neutral) < .85
    assert REMOVED_LINEWIDTH > MAXIMUM_LINEWIDTH
