"""Run learner checks and deterministic repair replays; never call a live API."""

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import unittest
import uuid

from agent.repair_support import execute_repair, source_hashes
from agent.task import Task
from scripts.exercise06_run import ROOT, LESSON, replay_model


EXPECTED = {
    "proof_then_valid": ("VERIFIED", 2, 2),
    "format_then_valid": ("VERIFIED", 2, 1),
    "always_bad": ("BUDGET_EXHAUSTED", 3, 3),
    "provider_failure": ("MODEL_ERROR", 1, 0),
    "refusal": ("MODEL_REFUSED", 1, 0),
    "incomplete_then_valid": ("VERIFIED", 2, 1),
    "scope_violation": ("EDIT_SCOPE_VIOLATION", 2, 1),
    "already_valid": ("VERIFIED", 1, 1),
}


def find_live_evidence(root):
    matches = []
    digest, hashes = Task.load(root, "checked_subtraction").digest, source_hashes(root)
    for path in (root / "runs/exercise06/attempts").glob("run-*/result.json"):
        try:
            report = json.loads(path.read_text())
            new_live = []
            for attempt in report["history"]:
                nested = Path(attempt["report_path"])
                if not nested.is_relative_to(path.parent / "attempts"):
                    continue  # An old seed alone is not evidence of new model work.
                model = json.loads((nested.parent / "model.json").read_text())
                if model.get("provider") == "openai" and model.get("response_id") and model.get("provider_requests") == 1:
                    new_live.append(model)
            if (report.get("learner_flow") is True and report.get("provider") == "openai"
                    and report.get("task_digest") == digest
                    and report.get("learner_source_sha256") == hashes
                    and report.get("status") not in {"EXERCISE_INCOMPLETE", "CONTROLLER_ERROR", "INFRASTRUCTURE_ERROR", "MODEL_ERROR", "STOPPED"}
                    and new_live):
                matches.append(str(path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(matches)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("prompt", "policy"))
    args = parser.parse_args(argv)
    pattern = f"test_{args.only}.py" if args.only else "test_*.py"
    suite = unittest.defaultTestLoader.discover(str(LESSON / "tests"), pattern=pattern)
    checks = unittest.TextTestRunner(verbosity=2).run(suite)
    destination = ROOT / "runs/exercise06/reviews" / uuid.uuid4().hex
    destination.mkdir(parents=True)
    cases = []
    if checks.wasSuccessful() and args.only is None:
        for name, (expected, calls, lean_checks) in EXPECTED.items():
            model = replay_model(name)
            result = execute_repair(ROOT, model, artifact_root=destination / name)
            report = json.loads(result.report_path.read_text())
            matched = (result.status == expected and report["model_calls"] == calls
                       and report["acceptance_checks"] == lean_checks and model.calls == calls)
            cases.append({"name": name, "status": result.status, "expected": expected,
                          "model_calls": report["model_calls"], "checks": report["acceptance_checks"],
                          "expectation_met": matched, "report_path": str(result.report_path)})
            print(f"[{'PASS' if matched else 'CHECK REQUIRED'}] {name}: {result.status}, "
                  f"{report['model_calls']} calls, {report['acceptance_checks']} checks")
            print(f"  report: {result.report_path}")
            if result.status in {"INFRASTRUCTURE_ERROR", "CONTROLLER_ERROR", "EXERCISE_INCOMPLETE"}:
                break
    replay_passed = len(cases) == len(EXPECTED) and all(case["expectation_met"] for case in cases)
    live = find_live_evidence(ROOT) if args.only is None else []
    ready = checks.wasSuccessful() and replay_passed and bool(live)
    report = {"exercise": 6, "checked_at": datetime.now(timezone.utc).isoformat(),
              "selected_task": args.only, "learner_tests_run": checks.testsRun,
              "learner_tests_passed": checks.wasSuccessful(), "cases": cases,
              "all_replay_expectations_met": replay_passed, "live_run_reports": live,
              "completion_evidence_ready": ready, "learner_source_sha256": source_hashes(ROOT),
              "awaiting_implementation_review": True, "session_report": str(destination / "review.json")}
    text = json.dumps(report, indent=2) + "\n"
    (destination / "review.json").write_text(text)
    (ROOT / "runs/exercise06/review.json").write_text(text)
    print(f"Summary: {ROOT / 'runs/exercise06/review.json'}")
    if args.only:
        return 0 if checks.wasSuccessful() else 1
    if ready:
        print("Evidence ready. Say ok for implementation review.")
    elif replay_passed:
        print("Replays passed; run the live repair flow using .env, then rerun review.")
    else:
        print("Complete the learner functions and resolve unexpected outcomes, then rerun.")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
