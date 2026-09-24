"""Resolve interseções OSM, valida mapas/rotas e exporta imagens. Não executa Frank-Wolfe."""
from __future__ import annotations

import argparse
from pathlib import Path

from braess.experiment_config import load_config
from braess.point_resolution_workflow import resolve_configuration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("experiments/tcc_scenarios.json"))
    destinations = parser.add_mutually_exclusive_group()
    destinations.add_argument("--output-config", type=Path)
    destinations.add_argument("--in-place", action="store_true", help="Atualiza o JSON original, criando backup.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tcc-point-resolution"))
    parser.add_argument("--search-graphml", type=Path, help="Rede OSMnx ampla local; evita o download da rede temporária.")
    parser.add_argument("--maximum-intersection-error-m", type=float)
    parser.add_argument("--radius-step-m", type=float)
    parser.add_argument("--max-radius-m", type=float)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config, require_coordinates=False)
        settings = config.setdefault("point_resolution", {})
        for field in ("maximum_intersection_error_m", "radius_step_m", "max_radius_m"):
            value = getattr(args, field)
            if value is not None:
                settings[field] = value
        output = args.config if args.in_place else (args.output_config or args.config.with_name(args.config.stem + "_resolved.json"))
        if output.resolve() == args.config.resolve() and not args.in_place:
            raise ValueError("Para atualizar o original, use --in-place explicitamente.")
        summary = resolve_configuration(config, output, args.output_dir,
                                        search_graphml=args.search_graphml, in_place=args.in_place)
        print(f"\nJSON: {output}\nImagens e CSV: {args.output_dir}", flush=True)
        unresolved = [f"{row['map_id']}/{row['point_label']} ({row['status']})"
                      for row in summary["points"] if row["status"] != "RESOLVED"]
        print("Pontos pendentes: " + (", ".join(unresolved) if unresolved else "nenhum"), flush=True)
        print("Mapas: " + ", ".join(f"{key}={value}" for key, value in summary["maps"].items()), flush=True)
        return 0 if summary["complete"] else 2
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Erro: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
