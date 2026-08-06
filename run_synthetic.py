from pathlib import Path

from braess.frank_wolfe import frank_wolfe
from braess.models import ODPair
from braess.outputs import (
    save_edge_results,
    save_iteration_history,
    save_summary,
)
from braess.synthetic import build_braess_network
from braess.visualization import (
    plot_convergence,
    plot_flow_comparison,
    plot_synthetic_flows,
)


OUTPUT_DIRECTORY = Path(
    "outputs/synthetic"
)


def run_scenario(
    *,
    include_connector: bool,
    scenario_name: str,
):
    graph = build_braess_network(
        include_connector=include_connector,
    )

    result = frank_wolfe(
        graph,
        [
            ODPair(
                origin="O",
                destination="D",
                demand=4000.0,
            )
        ],
        relative_gap_tolerance=1e-8,
        max_iterations=100,
    )

    scenario_directory = (
        OUTPUT_DIRECTORY / scenario_name
    )

    plot_synthetic_flows(
        graph,
        result.flows,
        scenario_directory / "network-flows.png",
        title=(
            f"{scenario_name} — "
            f"tempo médio: "
            f"{result.average_travel_time:.2f} min"
        ),
    )

    plot_convergence(
        result,
        scenario_directory / "convergence.png",
    )

    save_edge_results(
        graph,
        result,
        scenario_directory / "edge-results.csv",
    )

    save_iteration_history(
        result,
        scenario_directory / "iterations.csv",
    )

    save_summary(
        result,
        scenario_directory / "summary.json",
        extra={
            "include_connector": include_connector,
        },
    )

    return result


def main() -> None:
    without_connector = run_scenario(
        include_connector=False,
        scenario_name="without-connector",
    )

    with_connector = run_scenario(
        include_connector=True,
        scenario_name="with-connector",
    )

    plot_flow_comparison(
        without_connector,
        with_connector,
        OUTPUT_DIRECTORY / "comparison.png",
        baseline_label="Sem conexão",
        modified_label="Com conexão",
    )

    print("Experimento concluído.")

    print(
        "Sem conexão:",
        without_connector.average_travel_time,
    )

    print(
        "Com conexão:",
        with_connector.average_travel_time,
    )


if __name__ == "__main__":
    main()