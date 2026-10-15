"""Check learner prompt/flow tests, replay outcomes, and an existing live run.

This command never makes a paid API request. Live runs are explicit through
scripts.exercise05_run --live --model <your model>.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
import uuid

from agent.generation import execute_one_shot, learner_source_hashes
from agent.model_client import ReplayModel
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "exercises/05-one-shot-generation"
EXPECTED = {
    "valid": "VERIFIED", "proof_error": "ELABORATION_FAILED",
    "malformed": "INVALID_PROPOSAL", "refusal": "MODEL_REFUSED",
    "incomplete": "MODEL_INCOMPLETE", "provider_error": "MODEL_ERROR",
}
LIVE_OUTCOMES = {"VERIFIED", "ELABORATION_FAILED", "SUBMISSION_REJECTED", "TIMEOUT",
                 "OUTPUT_LIMIT_EXCEEDED", "INVALID_PROPOSAL", "MODEL_REFUSED", "MODEL_INCOMPLETE"}


def find_live_evidence(root):
    hashes = learner_source_hashes(root)
    digest = Task.load(root, "checked_subtraction").digest
    matches = []
    for path in (root / "runs/exercise05/attempts").glob("run-*/result.json"):
        try:
            report = json.loads(path.read_text())
            model = json.loads((path.parent / "model.json").read_text())
            if (report.get("provider") == "openai" and report.get("learner_flow") is True
                    and report.get("status") in LIVE_OUTCOMES
                    and report.get("learner_source_sha256") == hashes
                    and report.get("task_digest") == digest
                    and report.get("model_calls") == 1 and report.get("provider_requests") == 1
                    and isinstance(model.get("response_id"), str) and model["response_id"]
                    and (path.parent / "provider-response.json").is_file()):
                matches.append(str(path))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(matches)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("prompt",), help="Focused first-task checks; no Docker/API")
    args = parser.parse_args(argv)
    pattern = "test_prompt.py" if args.only else "test_*.py"
    suite = unittest.defaultTestLoader.discover(str(LESSON / "tests"), pattern=pattern)
    test_result = unittest.TextTestRunner(verbosity=2).run(suite)
    destination = ROOT / "runs/exercise05/reviews" / uuid.uuid4().hex
    destination.mkdir(parents=True)
    cases = []
    if test_result.wasSuccessful() and args.only is None:
        for name, expected in EXPECTED.items():
            result = execute_one_shot(ROOT, ReplayModel(LESSON / "fixtures" / (name + ".json")),
                                      artifact_root=destination / name)
            matched = result.status == expected
            cases.append({"name": name, "status": result.status, "expected": expected,
                          "expectation_met": matched, "report_path": str(result.report_path)})
            print(f"[{'PASS' if matched else 'CHECK REQUIRED'}] {name}: {result.status} (expected {expected})")
            print(f"  report: {result.report_path}")
            if result.status in {"CONTROLLER_ERROR", "EXERCISE_INCOMPLETE", "INFRASTRUCTURE_ERROR"}:
                break
    live = find_live_evidence(ROOT) if args.only is None else []
    replay_passed = len(cases) == len(EXPECTED) and all(case["expectation_met"] for case in cases)
    ready = test_result.wasSuccessful() and replay_passed and bool(live)
    report = {
        "exercise": 5, "checked_at": datetime.now(timezone.utc).isoformat(),
        "selected_task": args.only, "learner_tests_run": test_result.testsRun,
        "learner_tests_passed": test_result.wasSuccessful(), "cases": cases,
        "all_replay_expectations_met": replay_passed,
        "live_run_reports": live, "completion_evidence_ready": ready,
        "learner_source_sha256": learner_source_hashes(ROOT),
        "awaiting_implementation_review": True,
        "session_report": str(destination / "review.json"),
    }
    text = json.dumps(report, indent=2) + "\n"
    (destination / "review.json").write_text(text)
    (ROOT / "runs/exercise05/review.json").write_text(text)
    print(f"Summary: {ROOT / 'runs/exercise05/review.json'}")
    if args.only:
        print("Prompt checks passed; next connect the flow." if test_result.wasSuccessful()
              else "Complete build_generation_prompt; these checks run without Docker or an API key.")
        return 0 if test_result.wasSuccessful() else 1
    if ready:
        print("Replay and live-run evidence ready. Say ok for implementation review.")
    elif replay_passed:
        print("Replay checks passed. A real-model run with the current learner code is still required.")
        print("Use scripts.exercise05_run --live --model with a model you can access; then rerun review.")
    else:
        print("Complete the learner prompt/flow and resolve unexpected outcomes, then rerun.")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
