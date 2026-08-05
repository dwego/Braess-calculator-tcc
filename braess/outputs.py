from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import networkx as nx

from braess.frank_wolfe import FrankWolfeResult
from braess.models import EdgeId


def save_edge_results(
    graph: nx.MultiDiGraph,
    result: FrankWolfeResult,
    output_path: str | Path,
) -> None:
    """
    Salva os resultados finais de cada aresta em CSV.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "u",
        "v",
        "key",
        "name",
        "highway",
        "length",
        "lanes",
        "free_flow_time",
        "capacity",
        "flow",
        "travel_time",
        "volume_capacity_ratio",
    ]

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for u, v, key, data in graph.edges(
            keys=True,
            data=True,
        ):
            edge = EdgeId(u, v, key)
            flow = result.flows.get(edge, 0.0)

            capacity = _as_float(
                data.get("capacity")
            )

            ratio = (
                flow / capacity
                if capacity > 0.0
                else 0.0
            )

            writer.writerow(
                {
                    "u": u,
                    "v": v,
                    "key": key,
                    "name": data.get("name", ""),
                    "highway": data.get(
                        "highway_normalized",
                        data.get("highway", ""),
                    ),
                    "length": data.get("length", ""),
                    "lanes": data.get(
                        "lanes_normalized",
                        data.get("lanes", ""),
                    ),
                    "free_flow_time": data.get(
                        "free_flow_time",
                        "",
                    ),
                    "capacity": capacity,
                    "flow": flow,
                    "travel_time": data.get(
                        "travel_time",
                        "",
                    ),
                    "volume_capacity_ratio": ratio,
                }
            )


def save_iteration_history(
    result: FrankWolfeResult,
    output_path: str | Path,
) -> None:
    """
    Salva o histórico de convergência do Frank-Wolfe.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(
            [
                "iteration",
                "relative_gap",
                "step_size",
                "beckmann_objective",
                "total_system_travel_time",
            ]
        )

        for item in result.history:
            writer.writerow(
                [
                    item.iteration,
                    item.relative_gap,
                    item.step_size,
                    item.beckmann_objective,
                    item.total_system_travel_time,
                ]
            )


def save_summary(
    result: FrankWolfeResult,
    output_path: str | Path,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Salva as principais métricas do cenário em JSON.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "converged": result.converged,
        "iterations": result.iterations,
        "relative_gap": result.relative_gap,
        "total_system_travel_time": (
            result.total_system_travel_time
        ),
        "average_travel_time": (
            result.average_travel_time
        ),
        "beckmann_objective": (
            result.beckmann_objective
        ),
    }

    if extra:
        summary.update(extra)

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summary,
            file,
            ensure_ascii=False,
            indent=2,
        )


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0

    if isinstance(value, int | float):
        return float(value)

    return 0.0