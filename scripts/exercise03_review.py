"""Save Lean diagnostic examples and the learner's proof-repair observation.

This supplied command runs the isolated checker. It does not pass the lesson
automatically, call a model, or provide the later final acceptance verdict.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from agent.proposal import Proposal
from agent.render import render_candidate
from agent.sandbox import DockerLeanRunner, Outcome, WorkerImage
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]
LESSON = Path("exercises/03-sandboxed-runner")
PROOF_MARKER = "  -- LEARNER PROOF STARTS HERE\n"


def validate_learner_source(root: Path, source: str) -> None:
    """Check the lesson's fixed prefix and conservative proof-body format.

    This is a teaching preflight. Elaborated theorem correspondence and axiom
    policy remain the responsibility of the Exercise 4 acceptance gate.
    """
    original = (root / LESSON / "fixtures/ProofError.lean").read_text(encoding="utf-8")
    prefix, marker, _ = original.partition(PROOF_MARKER)
    if not marker or not source.startswith(prefix + marker) or source.count(PROOF_MARKER) != 1:
        raise ValueError("Keep the import, implementation and theorem header fixed; edit only below the proof marker")
    proof = source[len(prefix + marker):]
    Proposal(implementation_body="if b ≤ a then some (a - b) else none",
             proof_body="by\n" + proof).validate()


def collect_observations(root: Path, runner: DockerLeanRunner) -> dict:
    """Retain all case attempts and an immutable summary for this invocation."""
    task = Task.load(root, "checked_subtraction")
    learner_source = (root / LESSON / "starter/Candidate.lean").read_text(encoding="utf-8")
    validate_learner_source(root, learner_source)
    proposal = Proposal.from_json((root / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text())
    cases = [
        ("syntax_error", (root / LESSON / "fixtures/SyntaxError.lean").read_text(), Outcome.ELABORATION_FAILED),
        ("proof_error", (root / LESSON / "fixtures/ProofError.lean").read_text(), Outcome.ELABORATION_FAILED),
        ("reviewed_correct", render_candidate(task, proposal), Outcome.ELABORATED),
        ("learner_candidate", learner_source, Outcome.ELABORATED),
    ]
    session = root / "runs/exercise03/lean-feedback" / uuid.uuid4().hex
    session.mkdir(parents=True, mode=0o700)
    observations = []
    for name, source, expected in cases:
        result = runner.check(task, source, artifact_root=session / name)
        record = {
            "name": name, "expected_status": expected.value, "observed_status": result.status.value,
            "expectation_met": result.status == expected, "report_path": str(result.report_path),
            "stdout_path": str(result.stdout_path), "stderr_path": str(result.stderr_path),
        }
        observations.append(record)
        print(f"{name}: {result.status.value} (expected {expected.value})")
        print(f"  report: {result.report_path}")
        print(f"  stdout: {result.stdout_path}")
        print(f"  stderr: {result.stderr_path}")
        diagnostics = (result.stdout_path.read_bytes() + b"\n" + result.stderr_path.read_bytes()).strip()
        if diagnostics:
            print(diagnostics[:4096].decode("utf-8", errors="replace"))
        if result.status == Outcome.INFRASTRUCTURE_ERROR:
            details = json.loads(result.report_path.read_text(encoding="utf-8"))
            print(details.get("infrastructure_error") or details.get("cleanup_error") or "See the worker report")
            # Stop on infrastructure failure; do not label later unchecked
            # examples as failed proofs or spend more checks on a broken worker.
            break
    report = {
        "schema_version": 1, "exercise": 3, "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Lean execution observations; implementation review and final task acceptance are separate",
        "task_digest": task.digest, "cases": observations,
        "all_expectations_met": len(observations) == len(cases) and all(row["expectation_met"] for row in observations),
        "awaiting_manual_review": True,
        "session_report": str(session / "result.json"),
    }
    (session / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-report", type=Path, default=ROOT / "runs/exercise03/image.json")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    try:
        runner = DockerLeanRunner(WorkerImage.load(args.image_report), docker_binary=args.docker)
        report = collect_observations(ROOT, runner)
        destination = ROOT / "runs/exercise03/review.json"
        temporary = destination.with_name(f".review-{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    except (OSError, ValueError) as error:
        print(f"Exercise 3 check unavailable or rejected: {error}", file=sys.stderr)
        return 2
    print(f"Observation summary: {destination}")
    if report["all_expectations_met"]:
        print("Your proof elaborated and all example checks matched. Say ok for implementation review.")
    else:
        print("Inspect the diagnostics above, fix any unexpected result, then rerun this command.")
    return 0 if report["all_expectations_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
