from threading import Event, enumerate as threads

import pytest

from braess.experiment_progress import progress_phase


def test_phase_reports_activity_and_stops_worker(monkeypatch):
    messages = []
    heartbeat_seen = Event()

    def record(message):
        messages.append(message)
        if "em execução" in message:
            heartbeat_seen.set()

    monkeypatch.setattr("braess.experiment_progress.log_progress", record)
    with progress_phase("mapa_1/A_to_B | demanda=4000 | baseline", interval=.01):
        assert heartbeat_seen.wait(2)
    assert "início" in messages[0]
    assert "concluído" in messages[-1]
    assert all("demanda=4000" in message for message in messages)
    assert not any(t.name == "experiment-progress" for t in threads())


def test_phase_preserves_solver_exception_and_stops_worker(capsys):
    error = ValueError("falha do solver")
    with pytest.raises(ValueError) as raised:
        with progress_phase("baseline"):
            raise error
    assert raised.value is error
    assert "interrompido" in capsys.readouterr().out
    assert not any(t.name == "experiment-progress" for t in threads())


def test_three_demands_have_distinct_progress_and_results(tmp_path, capsys):
    from pathlib import Path
    from braess.experiment_config import load_config, select_scenarios
    from braess.experiment_maps import prepare_inputs
    from braess.experiments import run_experiments

    config = load_config(Path(__file__).resolve().parents[1] / "experiments/example_scenarios.json")
    config["demands"] = [2000, 4000, 6000]
    config = select_scenarios(config, route_id="A_to_B", candidate_limit=1, plot_level="none")
    frozen = load_config(prepare_inputs(config, tmp_path / "inputs"))
    result = run_experiments(frozen, tmp_path / "results")
    output = capsys.readouterr().out
    assert result["completed_scenarios"] == 3
    assert result["removal_count"] == 3
    for index, demand in enumerate(config["demands"], 1):
        assert f"Cenário {index}/3 | example/A_to_B | demanda={demand} veíc/h" in output
        assert f"demanda={demand} veíc/h | baseline" in output
        assert f"demanda={demand} veíc/h | remoção 1/1" in output
        assert (tmp_path / f"results/scenarios/example/A_to_B/demand-{demand}/summary.json").exists()
    assert "iterações=" in output and "gap=" in output and "TSTT=" in output
