"""Run only the reviewed Exercise 2 proposal through the Exercise 3 worker."""

import argparse
from pathlib import Path
import sys

from agent.proposal import Proposal
from agent.render import render_candidate
from agent.sandbox import DockerLeanRunner, Outcome, WorkerImage
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-report", type=Path, default=ROOT / "runs/exercise03/image.json")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    try:
        task = Task.load(ROOT, "checked_subtraction")
        proposal = Proposal.from_json((ROOT / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text())
        runner = DockerLeanRunner(WorkerImage.load(args.image_report), docker_binary=args.docker)
        result = runner.check(task, render_candidate(task, proposal), artifact_root=ROOT / "runs/exercise03/attempts")
    except (ValueError, OSError) as error:
        print(f"Exercise 3 worker is unavailable: {error}", file=sys.stderr)
        return 1
    print(f"Observed status: {result.status}")
    print(f"Actual Lean version: {result.lean_version}")
    print(f"Report: {result.report_path}")
    print("Final task acceptance will be added in Exercise 4.")
    return 0 if result.status == Outcome.ELABORATED else 1


if __name__ == "__main__":
    raise SystemExit(main())
