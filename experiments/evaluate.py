"""Budget-matched experiment orchestration (planning costs are included)."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from agent.schema import Budget


def evaluate_tasks(args, runner, budget: Budget, output: Path) -> list[dict]:
    from agent.cli import load_tasks, make_client
    from agent.controller import run
    from .analyze import analyze_results

    tasks = load_tasks(args.root, args.split)
    if not tasks:
        raise ValueError(f"No {args.split} tasks. Add audited held-out contracts before evaluation.")
    if args.repetitions < 1:
        raise ValueError("Repetitions must be positive")
    # Check provider configuration before creating a partial experiment.
    make_client(args)
    output.mkdir(parents=True, exist_ok=False)
    config = {"split": args.split, "strategies": list(dict.fromkeys(args.strategies)),
              "repetitions": args.repetitions, "budget": asdict(budget),
              "tasks": {t.id: t.digest for t in tasks}, "backend": args.backend,
              "image": args.image, "lean_toolchain": "leanprover/lean4:v4.34.1",
              "note": "One-shot uses one generation; sampling vs repair share all caps."}
    (output / "experiment.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    rows = []
    for repetition in range(args.repetitions):
        # Rotate strategy order to reduce persistent ordering effects.
        strategies = config["strategies"]
        offset = repetition % len(strategies)
        for strategy in strategies[offset:] + strategies[:offset]:
            for task in tasks:
                directory = output / strategy / f"repeat_{repetition:03}" / task.id
                result = run(task, make_client(args), runner, strategy, budget, directory)
                rows.append(asdict(result))
                print(f"{strategy:8} {task.id:24} {result.status}", flush=True)
    summary = analyze_results(output, output / "summary.csv")
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return rows


if __name__ == "__main__":
    from agent.cli import main
    import sys
    raise SystemExit(main(["evaluate", *sys.argv[1:]]))
