"""Check Lean acceptance examples or the three learner repair files.

Default: learner files only. --examples runs the deliberately rejected teaching
fixtures, clearly labelled with their expected outcomes. No written answers.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from agent.acceptance import AcceptanceImage, AcceptanceRunner, AcceptanceStatus
from agent.proposal import Proposal
from agent.render import render_candidate
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]
LESSON = Path("exercises/04-trusted-acceptance")
LEARNER_FILES = ("RemoveAxiom.lean", "FinishHelper.lean", "RestoreContract.lean")
REJECTION_FIXTURES = ("DirectSorry.lean", "IndirectSorry.lean", "CustomAxiom.lean",
                      "AlteredContract.lean", "ChangedSpec.lean", "MissingTheorem.lean", "ForgedVerdict.lean",
                      "Noncomputable.lean")


def collect(root, runner, *, examples=False, only=None):
    task = Task.load(root, "checked_subtraction")
    if examples:
        proposal = Proposal.from_json((root / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text())
        cases = [("ReviewedCorrect", render_candidate(task, proposal), AcceptanceStatus.VERIFIED)]
        cases += [(name, (root / LESSON / "fixtures" / name).read_text(), AcceptanceStatus.SUBMISSION_REJECTED)
                  for name in REJECTION_FIXTURES]
    else:
        if only is not None and only + ".lean" not in LEARNER_FILES:
            raise ValueError("Unknown learner repair")
        cases = [(name, (root / LESSON / "starter" / name).read_text(), AcceptanceStatus.VERIFIED)
                 for name in LEARNER_FILES if only is None or name == only + ".lean"]
    destination = root / "runs/exercise04" / ("examples" if examples else "learner") / uuid.uuid4().hex
    destination.mkdir(parents=True, mode=0o700)
    results = []
    for name, source, expected in cases:
        result = runner.check(task, source, artifact_root=destination / Path(name).stem)
        details = json.loads(result.report_path.read_text())
        matched = result.status == expected
        results.append({"name": name, "status": result.status.value,
                        "expected": expected.value, "expectation_met": matched,
                        "report_path": str(result.report_path)})
        label = "PASS" if matched else "REPAIR REQUIRED"
        print(f"[{label}] {name}: {result.status.value} (expected {expected.value})")
        print(f"  report: {result.report_path}")
        if not matched:
            messages = [details.get("error")]
            for packet in details.get("worker_results", {}).values():
                for kind in ("compilation", "exporter", "smoke", "comparator"):
                    record = packet.get(kind, {})
                    messages.extend([record.get("stdout"), record.get("stderr")])
            for message in messages:
                if message:
                    print(str(message)[:4096])
        if result.status == AcceptanceStatus.INFRASTRUCTURE_ERROR:
            break
    report = {"exercise": 4, "mode": "examples" if examples else "learner",
              "selected_task": only, "all_learner_tasks_checked": not examples and only is None,
              "checked_at": datetime.now(timezone.utc).isoformat(), "cases": results,
              "all_expectations_met": len(results) == len(cases) and all(row["expectation_met"] for row in results),
              "awaiting_implementation_review": True, "session_report": str(destination / "result.json")}
    (destination / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--examples", action="store_true")
    selection.add_argument("--only", choices=[Path(name).stem for name in LEARNER_FILES])
    parser.add_argument("--image-report", type=Path, default=ROOT / "runs/exercise04/image.json")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    try:
        runner = AcceptanceRunner(AcceptanceImage.load(args.image_report), root=ROOT, docker_binary=args.docker)
        report = collect(ROOT, runner, examples=args.examples, only=args.only)
        destination = ROOT / "runs/exercise04" / ("examples.json" if args.examples else "review.json")
        temporary = destination.with_name(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        os.replace(temporary, destination)
    except (OSError, ValueError) as error:
        print(f"Acceptance checking unavailable: {error}", file=sys.stderr)
        return 2
    print(f"Summary: {destination}")
    if report["all_expectations_met"]:
        if args.examples:
            print("All expected outcomes matched.")
        elif args.only:
            print("Selected Lean repair passed. Run without --only to check all three repairs.")
        else:
            print("All three Lean repairs passed. Say ok for review.")
    else:
        print("Use the recorded checker result to repair your Lean file, then rerun.")
    return 0 if report["all_expectations_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
