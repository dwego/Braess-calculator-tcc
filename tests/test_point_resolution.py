import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import networkx as nx
import pytest

from braess.experiment_config import load_config, map_extent, remap_route_nodes, route_node, validate_config
from braess.experiment_maps import snap_points
from braess.point_resolution import StreetIndex, apply_resolution, normalize_street_name
from braess import point_resolution_workflow as workflow
from resolve_tcc_points import main


def road_graph(positions, roads):
    graph = nx.MultiDiGraph(crs="epsg:4326", simplified=True, network_type="drive")
    for node, (x, y) in positions.items():
        graph.add_node(node, x=-45.89 + x / 102000, y=-23.18 + y / 111000)
    for u, v, name in roads:
        for a, b in [(u, v), (v, u)]:
            ax, ay = positions[a]
            bx, by = positions[b]
            graph.add_edge(a, b, name=name, length=((bx - ax) ** 2 + (by - ay) ** 2) ** .5,
                           highway="residential", travel_time=10.0, osmid=100 * a + b)
    return graph


@pytest.fixture
def graph():
    return road_graph(
        {1: (-100, 0), 2: (0, 0), 3: (100, 0), 4: (0, -100), 5: (0, 100),
         6: (200, 0), 7: (100, -100), 8: (100, 100)},
        [(1, 2, "Avenida Cidade Jardim"), (2, 3, "Avenida Cidade Jardim"), (3, 6, "Avenida Cidade Jardim"),
         (4, 2, "Avenida Salinas"), (2, 5, "Avenida Salinas"),
         (7, 3, "Avenida Perseu"), (3, 8, "Avenida Perseu")],
    )


@pytest.fixture
def config():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "experiments/example_scenarios.json")
    map_config = config["maps"][0]
    map_config.pop("graphml")
    map_config["locality"] = "Cidade de teste"
    map_config["points"]["A"].update(intersection="Av. Salinas x Av. Cidade Jardim", latitude=None, longitude=None)
    map_config["points"]["B"].update(intersection="Av. Perseu x Av. Cidade Jardim", latitude=None, longitude=None)
    return config


@pytest.mark.parametrize("abbreviated,full", [
    (" Av.  MÁRIO COVAS ", "Avenida Mario Covas"),
    ("R. Paraibuna", "Rua Paraibuna"),
    ("Rod. dos Tamoios", "Rodovia dos Tamoios"),
    ("Av. Pres. Juscelino Kubitschek", "Avenida Presidente Juscelino Kubitschek"),
    ("Av. Mal. Henrique Teixeira Lott", "Avenida Marechal Henrique Teixeira Lott"),
    ("Av. Dr. Sebastião Henrique da Cunha Pontes", "Avenida Doutor Sebastiao Henrique da Cunha Pontes"),
    ("SP-099", "SP099"),
])
def test_street_normalization(abbreviated, full):
    assert normalize_street_name(abbreviated) == normalize_street_name(full)


def test_direct_intersection_keeps_original_name(graph):
    point = {"label": "A", "intersection": "Av. Salinas x Av. Cidade Jardim"}
    result = StreetIndex(graph).resolve(point)
    assert result.status == "RESOLVED" and result.selected.node_id == 2
    assert result.selected.distance_error_m == 0
    resolved = apply_resolution(point, result)
    assert resolved["intersection"] == point["intersection"]
    assert resolved["latitude"] == graph.nodes[2]["y"]
    assert resolved["longitude"] == graph.nodes[2]["x"]


def test_aliases_match_reference_and_list_names(graph):
    for _, _, data in graph.edges(data=True):
        if data["name"] == "Avenida Cidade Jardim":
            data["ref"] = ["SP-099", "BR-101"]
        if data["name"] == "Avenida Salinas":
            data["name"] = ["Avenida Salinas", "Via local"]
    point = {"intersection": "Nome antigo x Rod. estadual", "street_1_aliases": ["Av. Salinas"],
             "street_2_aliases": ["SP099"]}
    result = StreetIndex(graph).resolve(point)
    assert result.selected.node_id == 2
    assert "SP-099" in result.matched_streets[1]


def test_primary_names_precede_conflicting_historical_aliases(graph):
    for _, _, data in graph.edges(data=True):
        if data["name"] == "Avenida Salinas":
            data["alt_name"] = "Avenida Cidade Jardim"
    result = StreetIndex(graph).resolve({"intersection": "Av. Salinas x Av. Cidade Jardim"})
    assert result.status == "RESOLVED" and result.selected.node_id == 2


def test_same_merged_edge_names_are_not_a_proven_intersection():
    graph = road_graph({1: (0, 0), 2: (100, 0)}, [(1, 2, ["Rua Um", "Rua Dois"])])
    result = StreetIndex(graph).resolve({"intersection": "Rua Um x Rua Dois"})
    assert result.status == "AMBIGUOUS" and result.selected is None


def test_multiple_distant_crossings_require_explicit_choice():
    graph = road_graph({1: (-10, 0), 2: (0, 0), 3: (0, 20), 4: (500, 0), 5: (510, 0), 6: (500, 20)},
                       [(1, 2, "Rua Um"), (2, 4, "Rua Um"), (4, 5, "Rua Um"),
                        (2, 3, "Rua Dois"), (4, 6, "Rua Dois")])
    index = StreetIndex(graph)
    point = {"intersection": "Rua Um x Rua Dois", "latitude": 1, "longitude": 2, "node_id": 99}
    ambiguous = index.resolve(point)
    assert ambiguous.status == "AMBIGUOUS" and len(ambiguous.candidates) == 2
    serialized = apply_resolution(point, ambiguous)
    assert serialized["latitude"] is None and serialized["longitude"] is None and "node_id" not in serialized
    selected = index.resolve(point | {"preferred_node_id": 4})
    assert selected.status == "RESOLVED" and selected.selected.node_id == 4
    assert index.resolve(point | {"preferred_node_id": 999}).status == "AMBIGUOUS"
    group = point | {"label": "A", "type": "junction_group", "nodes": [{"node_id": 2}, {"node_id": 4}]}
    serialized = apply_resolution(group, index.resolve(group))
    assert serialized["resolution"]["status"] == "RESOLVED"
    assert [member["node_id"] for member in serialized["nodes"]] == [2, 4]
    assert "node_id" not in serialized and "latitude" not in serialized


def test_group_chooses_different_members_by_directed_topology():
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 3, key=0, length=100)
    graph.add_edge(2, 3, key=0, length=10)
    graph.add_edge(3, 1, key=0, length=10)
    graph.add_edge(3, 2, key=0, length=100)
    points = {"A": {"type": "junction_group", "nodes": [{"node_id": 1}, {"node_id": 2}]}, "B": {"node_id": 3}}
    forward = workflow.select_route_nodes(graph, points, {"id": "A_to_B", "origin": "A", "destination": "B"})
    reverse = workflow.select_route_nodes(graph, points, {"id": "B_to_A", "origin": "B", "destination": "A"})
    assert forward["origin_node"] == 2 and reverse["destination_node"] == 1
    assert route_node(points, forward, "origin") == 2
    assert route_node(points, reverse, "destination") == 1
    assert forward["node_selection"]["origin_edges"][0]["u"] == 2
    assert len(forward["node_selection"]["candidates"]) == 2
    with pytest.raises(ValueError, match="origin_node"):
        route_node(points, {"id": "missing", "origin": "A"}, "origin")
    explicit = workflow.select_route_nodes(graph, points, {"id": "A_to_B", "origin": "A", "destination": "B", "origin_node": 1})
    assert explicit["origin_node"] == 1
    graph[1][3][0]["length"] = 11
    ambiguous = workflow.select_route_nodes(graph, points, {"id": "A_to_B", "origin": "A", "destination": "B"})
    assert ambiguous["node_selection"]["status"] == "AMBIGUOUS" and "origin_node" not in ambiguous


def test_group_extent_and_rebuilt_ids_preserve_route_members(config, graph):
    map_config = _resolve_fixture(config, graph)
    a = map_config["points"]["A"]
    second = dict(a, label="A2", latitude=graph.nodes[1]["y"], longitude=graph.nodes[1]["x"], node_id=1)
    group = {"label": "A", "type": "junction_group", "intersection": a["intersection"],
             "nodes": [dict(a, label="A1"), second]}
    map_config["points"]["A"] = group
    map_config["routes"][0]["origin_node"] = 1
    map_config["routes"][1]["destination_node"] = 2
    assert map_extent(map_config)[1] >= 600
    renamed = nx.relabel_nodes(graph, {1: 100, 2: 200})
    snapped = snap_points(renamed, map_config, require_same_node=False)
    routes = remap_route_nodes(map_config["routes"], map_config["points"], snapped)
    assert routes[0]["origin_node"] == 100 and routes[1]["destination_node"] == 200
    assert len(snapped["A"]["nodes"]) == 2
    config["maps"] = [map_config]
    validate_config(config)


def test_nearby_streets_need_local_topological_connection():
    positions = {1: (-100, 0), 2: (0, 0), 3: (100, 0), 4: (12, -100), 5: (12, 20), 6: (12, 100)}
    roads = [(1, 2, "Rua Um"), (2, 3, "Rua Um"), (4, 5, "Rua Dois"), (5, 6, "Rua Dois")]
    point = {"intersection": "Rua Um x Rua Dois"}
    disconnected = StreetIndex(road_graph(positions, roads)).resolve(point)
    assert disconnected.status == "NOT_FOUND"  # geometrias cruzam, mas não existe ligação
    connected = StreetIndex(road_graph(positions, roads + [(2, 5, "Alça")])).resolve(point)
    assert connected.status == "RESOLVED" and connected.selected.node_id == 2
    assert 10 < connected.selected.distance_error_m < 15
    assert connected.selected.method == "osm_nearby_connected_streets"


def test_distant_streets_and_unknown_streets_are_not_guessed(graph):
    result = StreetIndex(graph).resolve({"intersection": "Rua inexistente x Av. Cidade Jardim"})
    assert result.status == "NOT_FOUND"
    remote = road_graph({1: (0, 0), 2: (100, 0), 3: (0, 1000), 4: (100, 1000)},
                        [(1, 2, "Rua Um"), (3, 4, "Rua Dois"), (1, 3, "Alça")])
    assert StreetIndex(remote).resolve({"intersection": "Rua Um x Rua Dois"}).status == "NOT_FOUND"


def _resolve_fixture(config, graph):
    map_config = deepcopy(config["maps"][0])
    index = StreetIndex(graph)
    map_config["points"] = {label: apply_resolution(point, index.resolve(point))
                            for label, point in map_config["points"].items()}
    return map_config


def test_center_radius_and_expansion_preserve_reverse_route(config, graph):
    map_config = _resolve_fixture(config, graph)
    center, initial = map_extent(map_config)
    assert center[0] == pytest.approx(graph.nodes[2]["y"])
    assert center[1] == pytest.approx((graph.nodes[2]["x"] + graph.nodes[3]["x"]) / 2)
    assert 549 <= initial <= 552
    one_way = graph.copy()
    one_way.remove_edge(3, 2, 0)
    builder = Mock(side_effect=[one_way, graph])
    result, final_graph = workflow.validate_map_routes(map_config, radius_step_m=500, max_radius_m=2000,
                                                      graph_builder=builder)
    assert final_graph is graph
    assert result["radius_m"] == initial + 500
    assert result["geographic_validation"]["status"] == "RESOLVED"
    attempts = result["geographic_validation"]["attempts"]
    assert [route["connected"] for route in attempts[0]["routes"]] == [True, False]
    assert all(route["connected"] for route in attempts[1]["routes"])
    assert builder.call_args_list[0].args == (center, initial)


def test_expansion_stops_at_limit_and_records_failed_routes(config, graph):
    map_config = _resolve_fixture(config, graph)
    graph.remove_edge(3, 2, 0)
    initial = map_extent(map_config)[1]
    builder = Mock(return_value=graph)
    result, _ = workflow.validate_map_routes(map_config, radius_step_m=500, max_radius_m=initial+200,
                                            graph_builder=builder)
    assert builder.call_count == 2 and result["radius_m"] == initial+200
    assert result["geographic_validation"]["status"] == "ROUTES_DISCONNECTED"


def test_equal_group_choices_need_review_instead_of_radius_expansion(config, graph):
    map_config = _resolve_fixture(config, graph)
    first = dict(map_config["points"]["A"], label="A1")
    second = dict(first, label="A2", node_id=1,
                  latitude=graph.nodes[1]["y"], longitude=graph.nodes[1]["x"])
    map_config["points"]["A"] = {"label": "A", "intersection": first["intersection"],
                                  "type": "junction_group", "nodes": [first, second]}
    graph.add_edge(1, 3, length=100)
    graph.add_edge(3, 1, length=100)
    builder = Mock(return_value=graph)
    result, _ = workflow.validate_map_routes(map_config, radius_step_m=500, max_radius_m=2000,
                                            graph_builder=builder)
    builder.assert_called_once()
    assert result["geographic_validation"]["status"] == "AMBIGUOUS_ROUTES"
    assert all(route["node_selection"]["status"] == "AMBIGUOUS" for route in result["routes"])


def test_initial_radius_limit_prevents_download(config, graph):
    builder = Mock(side_effect=AssertionError("should not download"))
    result, final_graph = workflow.validate_map_routes(_resolve_fixture(config, graph), radius_step_m=500,
                                                      max_radius_m=100, graph_builder=builder)
    assert final_graph is None and result["geographic_validation"]["status"] == "RADIUS_LIMIT"
    builder.assert_not_called()


def test_snap_too_far_fails_and_new_topology_can_change_node_ids(config, graph):
    map_config = _resolve_fixture(config, graph)
    renamed = nx.relabel_nodes(graph, {2: 200, 3: 300})
    with pytest.raises(ValueError, match="node_id diverge"):
        snap_points(renamed, map_config)
    points = snap_points(renamed, map_config, require_same_node=False)
    assert points["A"]["node_id"] == 200 and points["A"]["snap_distance_m"] < .001
    map_config["points"]["A"]["longitude"] += .01
    initial = map_extent(map_config)[1]
    result, _ = workflow.validate_map_routes(map_config, radius_step_m=500, max_radius_m=initial,
                                            graph_builder=lambda *args: graph)
    assert result["points"]["A"]["resolution"]["status"] == "SNAP_TOO_FAR"


def test_resolution_json_csv_and_figures_are_generated_without_solver(config, graph, tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "load_search_graph", Mock(return_value=(graph, {"sha256": "fixture"})))
    monkeypatch.setattr(workflow, "build_graph", Mock(return_value=graph))
    import braess.frank_wolfe as fw
    solver = Mock(side_effect=AssertionError("No traffic assignment during resolution"))
    monkeypatch.setattr(fw, "frank_wolfe", solver)
    output = tmp_path / "resolved.json"
    images = tmp_path / "images"
    summary = workflow.resolve_configuration(config, output, images)
    assert summary["complete"]
    reloaded = load_config(output)
    assert reloaded["maps"][0]["points"]["A"]["node_id"] == 2
    assert Path(reloaded["maps"][0]["graphml"]).is_file()
    assert "snap_distance_m" in (images / "resolved_points.csv").read_text()
    from PIL import Image
    with Image.open(images / "example_points.png") as image:
        assert image.info["dpi"] == pytest.approx((300, 300), abs=.1)
    assert (images / "example_A.png").is_file() and (images / "example_B.png").is_file()
    solver.assert_not_called()
    with pytest.raises(FileExistsError):
        workflow.resolve_configuration(config, output, tmp_path / "again")


def test_unresolved_point_does_not_stop_other_maps(config, graph, tmp_path, monkeypatch):
    second = deepcopy(config["maps"][0])
    second["id"] = "second"
    config["maps"][0]["points"]["A"]["intersection"] = "Via inexistente x Av. Cidade Jardim"
    config["maps"].append(second)
    monkeypatch.setattr(workflow, "load_search_graph", Mock(return_value=(graph, {})))
    builder = Mock(return_value=graph)
    monkeypatch.setattr(workflow, "build_graph", builder)
    import braess.point_resolution_plots as plots
    monkeypatch.setattr(plots, "plot_validation_maps", lambda *args, **kw: [])
    output = tmp_path / "resolved.json"
    summary = workflow.resolve_configuration(config, output, tmp_path / "images")
    assert not summary["complete"]
    assert summary["maps"] == {"example": "INCOMPLETE", "second": "RESOLVED"}
    assert summary["points"][0]["latitude"] is None
    builder.assert_called_once()
    with pytest.raises(ValueError, match="geográfica incompleta"):
        load_config(output)
    assert load_config(output, require_coordinates=False)


def test_invalid_aliases_are_rejected(config):
    config["maps"][0]["points"]["A"]["street_1_aliases"] = "not a list"
    with pytest.raises(ValueError, match="street_1_aliases"):
        validate_config(config, require_coordinates=False)


def test_cli_requires_explicit_in_place(config, graph, tmp_path, monkeypatch):
    source = tmp_path / "scenarios.json"
    source.write_text(json.dumps(config))
    with pytest.raises(SystemExit) as error:
        main(["--config", str(source), "--output-config", str(source)])
    assert error.value.code == 2
    monkeypatch.setattr(workflow, "load_search_graph", Mock(return_value=(graph, {})))
    monkeypatch.setattr(workflow, "build_graph", Mock(return_value=graph))
    import braess.point_resolution_plots as plots
    monkeypatch.setattr(plots, "plot_validation_maps", lambda *args, **kw: [])
    assert main(["--config", str(source), "--in-place", "--output-dir", str(tmp_path / "images")]) == 0
    backups = list(tmp_path.glob("scenarios.json.*.bak"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == config
    assert json.loads(source.read_text())["maps"][0]["points"]["A"]["latitude"] is not None
