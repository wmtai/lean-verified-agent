"""Learner loop checks; the checker here is a spy, review uses real Lean."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from agent.acceptance import AcceptanceResult, AcceptanceStatus
from agent.repair_support import BudgetLimits, execute_repair
from scripts.exercise06_run import ROOT, replay_model


class SpyChecker:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []

    def check(self, task, source, *, artifact_root):
        status = self.statuses[len(self.calls)]
        self.calls.append(source)
        artifact_root.mkdir(parents=True)
        path = artifact_root / "result.json"
        path.write_text(json.dumps({"status": status, "task_digest": task.digest,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "worker_results": {"export": {"compilation": {"stdout": "unsolved goals", "stderr": ""}}}}))
        return AcceptanceResult(AcceptanceStatus(status), path, artifact_root)


class RepairLoopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name)

    def run_case(self, name, statuses, limits=None):
        model, checker = replay_model(name), SpyChecker(statuses)
        result = execute_repair(ROOT, model, checker=checker, limits=limits, artifact_root=self.destination)
        return result, json.loads(result.report_path.read_text()), model, checker

    def test_failed_proof_then_success_preserves_implementation_and_stops(self):
        result, report, model, checker = self.run_case("proof_then_valid", ["ELABORATION_FAILED", "VERIFIED"])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(model.calls, 2)
        self.assertEqual(len(checker.calls), 2)
        self.assertEqual([a["action"] for a in report["history"]], ["GENERATE", "REPAIR_PROOF"])
        self.assertEqual(report["history"][0]["proposal"]["implementation_body"],
                         report["history"][1]["proposal"]["implementation_body"])
        for attempt in report["history"]:
            self.assertTrue(Path(attempt["report_path"]).is_file())
        self.assertEqual((report["model_calls"], report["acceptance_checks"]), (2, 2))

    def test_malformed_reply_consumes_a_call_and_regenerates(self):
        result, report, model, checker = self.run_case("format_then_valid", ["VERIFIED"])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(model.calls, 2)
        self.assertEqual(len(checker.calls), 1)
        self.assertEqual(report["history"][1]["action"], "REGENERATE")
        self.assertEqual(report["input_tokens"], 240)

    def test_budget_exhaustion_retains_three_failed_attempts(self):
        result, report, model, checker = self.run_case("always_bad", ["ELABORATION_FAILED"] * 3)
        self.assertEqual(result.status, "BUDGET_EXHAUSTED")
        self.assertEqual(model.calls, 3)
        self.assertEqual(len(report["history"]), 3)
        self.assertEqual(len(checker.calls), 3)

    def test_provider_failure_stops_without_retry(self):
        result, report, model, checker = self.run_case("provider_failure", [])
        self.assertEqual(result.status, "MODEL_ERROR")
        self.assertEqual(model.calls, 1)
        self.assertEqual(checker.calls, [])

    def test_proof_only_edit_violation_stops_before_second_check(self):
        result, report, model, checker = self.run_case("scope_violation", ["ELABORATION_FAILED"])
        self.assertEqual(result.status, "EDIT_SCOPE_VIOLATION")
        self.assertEqual(model.calls, 2)
        self.assertEqual(len(checker.calls), 1)

    def test_initial_budget_exhaustion_makes_no_model_call(self):
        result, report, model, checker = self.run_case("already_valid", [], BudgetLimits(max_model_calls=0))
        self.assertEqual(result.status, "BUDGET_EXHAUSTED")
        self.assertEqual(model.calls, 0)
        self.assertEqual(checker.calls, [])

    def test_initial_success_never_uses_the_second_response(self):
        result, report, model, checker = self.run_case("already_valid", ["VERIFIED"])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(model.calls, 1)
        self.assertEqual(len(checker.calls), 1)


if __name__ == "__main__":
    unittest.main()
