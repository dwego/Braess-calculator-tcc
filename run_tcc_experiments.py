"""CLI do pipeline experimental; toda a definição de redes e rotas vem do JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from braess.experiment_config import load_config, scenario_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "resolve-points", "prepare", "run"])
    parser.add_argument("--config", type=Path, default=Path("experiments/tcc_scenarios.json"))
    parser.add_argument("--output", type=Path, help="Arquivo JSON para resolve-points; diretório novo para prepare/run.")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config, require_coordinates=args.command in {"prepare", "run"})
        if args.command == "validate":
            missing = [f"{m['id']}/{label}" for m in config["maps"] for label, point in m["points"].items()
                       if point.get("latitude") is None]
            print(f"Configuração válida: {len(config['maps'])} mapas, {scenario_count(config)} cenários-base.")
            if missing:
                print("Coordenadas pendentes: " + ", ".join(missing))
            return 0
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = args.output or Path("outputs") / f"tcc-{args.command}-{timestamp}"
        if args.command == "resolve-points":
            from braess.experiment_maps import resolve_points
            if args.output is None:
                output = output.with_suffix(".json")
            failures = resolve_points(config, output)
            print(f"Coordenadas salvas em {output}. Confira as interseções antes de preparar os mapas.")
            if failures:
                print("Resolução pendente: " + ", ".join(failures))
                return 2
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
