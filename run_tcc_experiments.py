"""CLI do pipeline experimental; toda a definição de redes e rotas vem do JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from braess.experiment_config import PLOT_LEVELS, load_config, point_members, scenario_count, select_scenarios, validate_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "resolve-points", "prepare", "run"])
    parser.add_argument("--config", type=Path, default=Path("experiments/tcc_scenarios.json"))
    parser.add_argument("--output", type=Path, help="Arquivo JSON para resolve-points; diretório novo para prepare/run.")
    parser.add_argument("--map", dest="map_id", help="Seleciona somente este ID de mapa.")
    parser.add_argument("--route", dest="route_id", help="Seleciona este ID de rota nos mapas selecionados.")
    parser.add_argument("--demand", type=float, help="Seleciona uma demanda já configurada, em veíc/h.")
    parser.add_argument("--candidate-limit", type=int, help="Máximo positivo de candidatas por cenário, inclusive listas explícitas.")
    parser.add_argument("--plot-level", choices=PLOT_LEVELS, help="PNGs: none, somente baseline, ou all; CSVs são sempre salvos.")
    args = parser.parse_args(argv)
    try:
        options = {field: getattr(args, field) for field in ("map_id", "route_id", "demand", "candidate_limit", "plot_level")}
        filtered = any(value is not None for value in options.values())
        if filtered and args.command == "resolve-points":
            raise ValueError("Os filtros de smoke test são aceitos em validate, prepare e run; não em resolve-points.")
        config = select_scenarios(load_config(args.config, require_coordinates=False), **options)
        config = validate_config(config, require_coordinates=args.command in {"prepare", "run"})
        if filtered:
            print(f"Seleção: {len(config['maps'])} mapa(s), {scenario_count(config)} cenário(s)-base.", flush=True)
        if args.command == "validate":
            missing = [f"{m['id']}/{label}" for m in config["maps"] for label, point in m["points"].items()
                       if not point_members(point) or any(member.get("latitude") is None for member in point_members(point))]
            print(f"Configuração válida: {len(config['maps'])} mapas, {scenario_count(config)} cenários-base.")
            if missing:
                print("Coordenadas pendentes: " + ", ".join(missing))
            return 0
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = args.output or Path("outputs") / f"tcc-{args.command}-{timestamp}"
        if args.command == "resolve-points":
            from resolve_tcc_points import main as resolve_main
            if args.output is None:
                output = output.with_suffix(".json")
            return resolve_main(["--config", str(args.config), "--output-config", str(output),
                                 "--output-dir", str(output.with_suffix(""))])
        elif args.command == "prepare":
            from braess.experiment_maps import prepare_inputs
            print(f"Configuração congelada: {prepare_inputs(config, output)}")
        else:
            from braess.experiments import run_experiments
            summary = run_experiments(config, output)
            print(f"{summary['status']}: {summary['completed_scenarios']} cenários; resultados em {output}")
            return 2 if summary["status"] == "COMPLETED_WITH_ERRORS" else 0
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Erro: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
