"""Métricas e figuras de V/C calculadas após a atribuição, sem alterar fluxos."""
from pathlib import Path
from statistics import mean, median
import math

from braess.models import EdgeId

THRESHOLDS = ((0.8, "0_8"), (1.0, "1_0"), (1.5, "1_5"))


def active_vc_ratios(graph, flows, minimum_active_flow):
    values = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        flow = flows.get(EdgeId(u, v, key), 0.0)
        if flow <= minimum_active_flow:
            continue
        capacity = float(data.get("capacity", 0) or 0)
        if not math.isfinite(flow) or not math.isfinite(capacity) or capacity <= 0:
            raise ValueError(f"Fluxo/capacidade inválido na aresta ativa {(u, v, key)}")
        values.append(flow / capacity)
    return values


def saturation_metrics(graph, flows, minimum_active_flow):
    values = active_vc_ratios(graph, flows, minimum_active_flow) if flows is not None else []
    metrics = {
        "minimum_active_flow": minimum_active_flow,
        "active_edge_count": len(values) if flows is not None else None,
        "max_vc_ratio": max(values) if values else None,
        "mean_active_vc_ratio": mean(values) if values else None,
        "median_active_vc_ratio": median(values) if values else None,
    }
    for threshold, suffix in THRESHOLDS:
        count = sum(value > threshold for value in values)
        metrics[f"edges_vc_gt_{suffix}"] = count if flows is not None else None
        metrics[f"percent_active_edges_vc_gt_{suffix}"] = 100 * count / len(values) if values else None
    return metrics


def plot_vc_distribution(graph, result, threshold, path, title):
    import matplotlib.pyplot as plt
    values = active_vc_ratios(graph, result.flows, threshold)
    figure, axis = plt.subplots(figsize=(9, 5.5), layout="constrained")
    try:
        if values:
            axis.hist(values, bins=30, range=(0, max(1.65, max(values) * 1.05)), color="#287e98", edgecolor="white", linewidth=.4)
        else:
            axis.text(.5, .5, "Nenhuma aresta ativa", transform=axis.transAxes, ha="center")
        for (value, _), color in zip(THRESHOLDS, ("#b28a00", "#e57818", "#c1272d")):
            axis.axvline(value, color=color, linestyle="--", linewidth=1.5, label=f"V/C = {value:g}")
        axis.set(xlabel="Fluxo / capacidade (valores reais, sem clipping)",
                 ylabel="Número de arestas ativas", xlim=(0, max(1.65, max(values, default=0) * 1.05)))
        axis.set_title(f"{title}\n{'Convergido' if result.converged else 'NO_CONVERGENCE — solução parcial'}"
                       f" · gap={result.relative_gap:.3g} · {len(values)} arestas com fluxo > {threshold:g}", fontsize=11)
        axis.legend(frameon=False)
        axis.grid(axis="y", alpha=.2)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, dpi=300)
    finally:
        plt.close(figure)


def plot_vc_demand_comparison(rows, path):
    import matplotlib.pyplot as plt
    rows = sorted(rows, key=lambda row: row["demand"])
    figure, axes = plt.subplots(1, 2, figsize=(11, 5.5), layout="constrained")
    x = list(range(len(rows)))
    labels = [f"{r['demand']:g}\n{r['status']}\ngap={r['final_relative_gap']:.2g}"
              if r["final_relative_gap"] is not None else f"{r['demand']:g}\n{r['status']}" for r in rows]
    try:
        for key, label, color in (("max_vc_ratio", "Máximo", "#c1272d"),
                                  ("mean_active_vc_ratio", "Média ativa", "#1278a0"),
                                  ("median_active_vc_ratio", "Mediana ativa", "#258149")):
            axes[0].plot(x, [r[key] if r[key] is not None else math.nan for r in rows], "o-", label=label, color=color)
        for suffix, label, color in (("0_8", "V/C > 0,8", "#b28a00"), ("1_0", "V/C > 1,0", "#c1272d")):
            axes[1].plot(x, [r[f"percent_active_edges_vc_gt_{suffix}"]
                             if r[f"percent_active_edges_vc_gt_{suffix}"] is not None else math.nan for r in rows],
                         "o-", label=label, color=color)
        axes[0].set_ylabel("Fluxo / capacidade")
        axes[0].set_ylim(bottom=0)
        percentages = [r[f"percent_active_edges_vc_gt_{suffix}"] for r in rows for suffix in ("0_8", "1_0")
                       if r[f"percent_active_edges_vc_gt_{suffix}"] is not None]
        # Preserve zero while making small fractions visible.
        percent_top = min(100, max(10, max(percentages, default=0) * 1.3))
        axes[1].set(ylabel="% das arestas ativas", ylim=(0, percent_top))
        for axis in axes:
            axis.set_xticks(x, labels)
            axis.set_xlabel("Demanda (veíc/h) · status e gap independentes da saturação")
            axis.grid(alpha=.2)
            axis.legend(frameon=False)
        figure.suptitle(f"{rows[0]['map_id']} / {rows[0]['od_pair_id']} — saturação dos baselines\n"
                        f"Arestas com fluxo > {rows[0]['minimum_active_flow']:g} veíc/h")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, dpi=300)
    finally:
        plt.close(figure)
