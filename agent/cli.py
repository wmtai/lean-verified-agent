"""CLI usable directly from a checkout: python -m agent."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

from .schema import Budget, Candidate, Task

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("one-shot", "sampling", "repair", "planning")


def add_execution_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Repository root containing tasks/ and lean/")
    parser.add_argument("--backend", choices=("docker", "local"), default="docker")
    parser.add_argument("--allow-local", action="store_true",
                        help="Allow unsandboxed Lean execution for reviewed fixtures only")
    parser.add_argument("--image", default="lean-verified-agent-verifier:4.34.1")
    parser.add_argument("--lean-timeout", type=float, default=30)


def add_budget_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--max-lean-checks", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=30000)
    parser.add_argument("--max-seconds", type=float, default=300)
    parser.add_argument("--max-output-tokens", type=int, default=4096)


def make_budget(args: argparse.Namespace) -> Budget:
    return Budget(args.max_calls, args.max_lean_checks, args.max_tokens,
                  args.max_seconds, args.max_output_tokens)


def make_runner(args: argparse.Namespace):
    from verifier.lean_runner import LeanRunner
    return LeanRunner(project_root=args.root.resolve(), backend=args.backend,
                      timeout_seconds=args.lean_timeout, image=args.image,
                      allow_local=args.allow_local)


def make_client(args: argparse.Namespace, replay: Path | None = None):
    from .model_client import ChatCompletionsClient, ReplayClient
    if replay is not None:
        return ReplayClient(replay)
    model = args.model or os.environ.get("LLM_MODEL")
    key = os.environ.get("LLM_API_KEY")
    base_url = args.base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    if not model or not key:
        raise ValueError("Live runs require LLM_MODEL (or --model) and LLM_API_KEY")
    return ChatCompletionsClient(model=model, base_url=base_url, api_key=key)


def unique_output(root: Path, label: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / f"{stamp}_{label}_{uuid.uuid4().hex[:8]}"


def load_tasks(root: Path, split: str = "dev") -> list[Task]:
    if split not in {"dev", "eval"}:
        raise ValueError("Split must be dev or eval")
    identifiers = json.loads((root / "tasks" / f"{split}.json").read_text(encoding="utf-8"))
    if (not isinstance(identifiers, list) or
            any(not isinstance(identifier, str) or
                not re.fullmatch(r"[a-z][a-z0-9_]*", identifier) for identifier in identifiers)):
        raise ValueError("Task manifest must be a list of lowercase task identifiers")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Task manifest contains duplicate identifiers")
    tasks = []
    for identifier in identifiers:
        task = Task.load(root / "tasks" / identifier / "task.json")
        if task.id != identifier or task.split != split:
            raise ValueError(f"Task {identifier} does not match its {split} manifest entry")
        tasks.append(task)
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and verify Lean implementations")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("tasks", help="List available fixed contracts")
    listing.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    listing.add_argument("--split", choices=("dev", "eval"), default="dev")
    for name in ("run", "demo"):
        command = sub.add_parser(name, help="Solve a task" if name == "run" else
                                 "Replay checked-subtraction failure and repair")
        add_execution_options(command)
        add_budget_options(command)
        command.add_argument("--task", default="checked_subtraction")
        command.add_argument("--strategy", choices=STRATEGIES, default="repair")
        command.add_argument("--output", type=Path)
        command.add_argument("--replay", type=Path)
        command.add_argument("--model")
        command.add_argument("--base-url")
    fixtures = sub.add_parser("check-fixtures", help="Verify all reviewed reference solutions")
    add_execution_options(fixtures)
    fixtures.add_argument("--output", type=Path)
    evaluate = sub.add_parser("evaluate", help="Compare strategies under shared budgets")
    add_execution_options(evaluate)
    add_budget_options(evaluate)
    evaluate.add_argument("--split", choices=("dev", "eval"), default="dev")
    evaluate.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    evaluate.add_argument("--repetitions", type=int, default=1)
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--model")
    evaluate.add_argument("--base-url")
    analyze = sub.add_parser("analyze", help="Aggregate saved result.json traces")
    analyze.add_argument("path", type=Path)
    analyze.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "tasks":
            for task in load_tasks(args.root, args.split):
                print(f"{task.id:24} {task.category:16} {task.title}")
            return 0
        if args.command == "analyze":
            from experiments.analyze import analyze_results
            print(json.dumps(analyze_results(args.path, args.csv), indent=2))
            return 0
        runner = make_runner(args)
        if args.command == "check-fixtures":
            output = args.output or unique_output(args.root / "results", "fixtures")
            checks = []
            for task in load_tasks(args.root):
                reference = args.root / "tasks" / task.id / "reference.json"
                candidate = Candidate.parse(reference.read_text(encoding="utf-8"))
                result = runner.verify(task, candidate, output / task.id)
                checks.append({"task_id": task.id, **asdict(result)})
                print(f"{task.id}: {'VERIFIED' if result.accepted else result.category}")
                if not result.accepted:
                    print(result.diagnostics, file=sys.stderr)
            if not checks:
                raise ValueError("No development fixtures found")
            output.mkdir(parents=True, exist_ok=True)
            (output / "fixtures.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
            return 0 if all(c["accepted"] for c in checks) else 1
        if args.command == "evaluate":
            from experiments.evaluate import evaluate_tasks
            output = args.output or unique_output(args.root / "results", "evaluation")
            rows = evaluate_tasks(args, runner, make_budget(args), output)
            print(f"Results: {output}")
            return 1 if any(row["status"] == "ERROR" for row in rows) else 0
        from .controller import run
        task = Task.load(args.root / "tasks" / args.task / "task.json")
        replay = args.replay
        if args.command == "demo" and replay is None:
            replay = args.root / "examples" / "checked_subtraction_repair.json"
        output = args.output or unique_output(args.root / "results", task.id)
        result = run(task, make_client(args, replay), runner, args.strategy,
                     make_budget(args), output)
        print(json.dumps(asdict(result), indent=2))
        return 0 if result.status == "VERIFIED" else 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
