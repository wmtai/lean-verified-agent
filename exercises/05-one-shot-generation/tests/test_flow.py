"""Learner task 2 checks use a spy checker; review also runs real Docker."""

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from agent.acceptance import AcceptanceResult, AcceptanceStatus
from agent.generation import execute_one_shot
from agent.model_client import ReplayModel
from agent.proposal import Proposal
from agent.render import render_candidate
from agent.task import Task


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class RecordingReplay(ReplayModel):
    def __init__(self, path):
        super().__init__(path)
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        return super().generate(prompt)


class SpyChecker:
    def __init__(self, status=AcceptanceStatus.VERIFIED):
        self.status = status
        self.calls = []

    def check(self, task, source, *, artifact_root):
        self.calls.append((task, source))
        artifact_root.mkdir(parents=True)
        path = artifact_root / "result.json"
        path.write_text(json.dumps({"status": self.status.value, "spy": True}))
        return AcceptanceResult(self.status, path, artifact_root)


class OneShotFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name)

    def run_case(self, name, checker=None):
        model = RecordingReplay(FIXTURES / (name + ".json"))
        checker = checker or SpyChecker()
        result = execute_one_shot(ROOT, model, artifact_root=self.destination, checker=checker)
        report = json.loads(result.report_path.read_text())
        return result, report, model, checker

    def test_valid_reply_is_parsed_rendered_checked_and_saved(self):
        result, report, model, checker = self.run_case("valid")
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(checker.calls), 1)
        task = Task.load(ROOT, "checked_subtraction")
        response = json.loads((FIXTURES / "valid.json").read_text())
        proposal = Proposal.from_json(response["output"][0]["content"][0]["text"])
        expected = render_candidate(task, proposal)
        self.assertEqual(checker.calls[0][0].digest, task.digest)
        self.assertEqual(checker.calls[0][1], expected)
        self.assertEqual((result.report_path.parent / "Candidate.lean").read_text(), expected)
        self.assertEqual(json.loads((result.report_path.parent / "proposal.json").read_text()), asdict(proposal))
        for name in ("task.json", "prompt.json", "model.json", "provider-response.json", "response.txt"):
            self.assertTrue((result.report_path.parent / name).is_file())
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(report["acceptance_checks"], 1)
        self.assertEqual(report["usage"]["source"], "fixture")

    def test_malformed_text_is_not_repaired_or_sent_to_lean(self):
        result, report, model, checker = self.run_case("malformed")
        self.assertEqual(result.status, "INVALID_PROPOSAL")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(checker.calls, [])
        self.assertEqual(report["acceptance_checks"], 0)
        self.assertTrue((result.report_path.parent / "response.txt").is_file())
        self.assertFalse((result.report_path.parent / "Candidate.lean").exists())

    def test_model_failures_stop_before_parsing_and_checking(self):
        for name, status in (("refusal", "MODEL_REFUSED"), ("incomplete", "MODEL_INCOMPLETE"),
                             ("provider_error", "MODEL_ERROR")):
            with self.subTest(name=name):
                result, report, model, checker = self.run_case(name)
                self.assertEqual(result.status, status)
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(checker.calls, [])
                self.assertEqual(report["acceptance_checks"], 0)
                self.assertFalse((result.report_path.parent / "proposal.json").exists())

    def test_checker_verdict_is_authoritative_and_does_not_trigger_retry(self):
        for status in (AcceptanceStatus.ELABORATION_FAILED, AcceptanceStatus.SUBMISSION_REJECTED,
                       AcceptanceStatus.TIMEOUT, AcceptanceStatus.INFRASTRUCTURE_ERROR):
            with self.subTest(status=status):
                result, report, model, checker = self.run_case("valid", SpyChecker(status))
                self.assertEqual(result.status, status.value)
                self.assertEqual(report["acceptance_status"], status.value)
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(len(checker.calls), 1)

    def test_all_attempts_remain_available(self):
        first, _, _, _ = self.run_case("malformed")
        second, _, _, _ = self.run_case("valid")
        self.assertEqual(first.status, "INVALID_PROPOSAL")
        self.assertEqual(second.status, "VERIFIED")
        self.assertNotEqual(first.report_path, second.report_path)
        self.assertTrue(first.report_path.is_file())
        self.assertTrue(second.report_path.is_file())


if __name__ == "__main__":
    unittest.main()
