"""Provided repair service tests independent of the three learner holes."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from agent.acceptance import AcceptanceResult, AcceptanceStatus
from agent.generation import BudgetExceeded, FlowError, execute_one_shot
from agent.model_client import Prompt, ReplayModel
from agent.repair_support import BudgetLimits, RepairAction, RepairSession, execute_repair
from agent.task import Task
from scripts.exercise06_run import ROOT, replay_model


PROMPT = Prompt("Return valid JSON bodies.", "Trusted test task.")


class Checker:
    def __init__(self, status="ELABORATION_FAILED"):
        self.status, self.calls = status, 0

    def check(self, task, source, *, artifact_root):
        self.calls += 1
        artifact_root.mkdir(parents=True)
        path = artifact_root / "result.json"
        path.write_text(json.dumps({"status": self.status, "task_digest": task.digest,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "worker_results": {"export": {"compilation": {"stdout": "error: unsolved goals", "stderr": ""}}}}))
        return AcceptanceResult(AcceptanceStatus(self.status), path, artifact_root)


class RepairSupportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.task = Task.load(ROOT, "checked_subtraction")

    def session(self, model=None, limits=None, checker=None, clock=None):
        arguments = {"clock": clock} if clock else {}
        return RepairSession(ROOT, self.task, model or replay_model("proof_then_valid"), self.work,
                             limits=limits, checker=checker or Checker(), **arguments)

    def test_limits_reject_negative_boolean_and_nonfinite_values(self):
        for values in ({"max_attempts": -1}, {"max_checks": True}, {"wall_seconds": float("inf")},
                       {"wall_seconds": 0}, {"max_total_tokens": 1.5}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                BudgetLimits(**values)

    def test_exhausted_budget_prevents_any_model_call(self):
        model = replay_model("proof_then_valid")
        session = self.session(model, BudgetLimits(max_model_calls=0))
        with self.assertRaises(BudgetExceeded):
            session.attempt(PROMPT, RepairAction.GENERATE)
        self.assertEqual(model.calls, 0)
        self.assertEqual(session.finish().status, "BUDGET_EXHAUSTED")

    def test_failed_attempt_is_frozen_and_full_artifacts_are_retained(self):
        session = self.session()
        attempt = session.attempt(PROMPT, RepairAction.GENERATE)
        self.assertEqual(attempt.status, "ELABORATION_FAILED")
        self.assertIn("unsolved goals", attempt.diagnostics)
        self.assertEqual((session.model_calls, session.checks), (1, 1))
        self.assertIsInstance(session.history, tuple)
        with self.assertRaises(FrozenInstanceError):
            attempt.status = "VERIFIED"
        for name in ("prompt.json", "model.json", "response.txt", "proposal.json", "Candidate.lean"):
            self.assertTrue((attempt.report_path.parent / name).exists())

    def test_proof_only_violation_rejects_before_checker(self):
        model, checker = replay_model("scope_violation"), Checker()
        session = self.session(model, checker=checker)
        session.attempt(PROMPT, RepairAction.GENERATE)
        observed = session.attempt(PROMPT, RepairAction.REPAIR_PROOF)
        self.assertEqual(observed.status, "EDIT_SCOPE_VIOLATION")
        self.assertEqual(checker.calls, 1)
        self.assertEqual(session.finish().status, "EDIT_SCOPE_VIOLATION")

    def test_no_generation_after_verified_success(self):
        model = replay_model("already_valid")
        session = self.session(model, checker=Checker("VERIFIED"))
        session.attempt(PROMPT, RepairAction.GENERATE)
        with self.assertRaises(FlowError):
            session.attempt(PROMPT, RepairAction.REGENERATE)
        self.assertEqual(model.calls, 1)

    def test_malformed_response_consumes_tokens_and_call_without_check(self):
        session = self.session(replay_model("format_then_valid"))
        observed = session.attempt(PROMPT, RepairAction.GENERATE)
        self.assertEqual(observed.status, "INVALID_PROPOSAL")
        self.assertEqual((session.model_calls, session.input_tokens, session.output_tokens, session.checks),
                         (1, 120, 95, 0))

    def test_unknown_usage_stops_before_check_and_blocks_more_calls(self):
        base = ReplayModel(ROOT / "exercises/05-one-shot-generation/fixtures/valid.json")
        class UnknownUsage:
            provider, model = "replay", "unknown-usage-fixture"
            def generate(self, prompt):
                return replace(base.generate(prompt), input_tokens=None, output_tokens=None)
        checker = Checker()
        session = self.session(UnknownUsage(), checker=checker)
        self.assertEqual(session.attempt(PROMPT, RepairAction.GENERATE).status, "BUDGET_EXHAUSTED")
        self.assertFalse(session.budget.can_attempt)
        self.assertFalse(session.usage_known)
        self.assertEqual(checker.calls, 0)

    def test_observed_token_overrun_is_explicit_and_stops_before_check(self):
        checker = Checker()
        session = self.session(limits=BudgetLimits(max_total_tokens=50), checker=checker)
        self.assertEqual(session.attempt(PROMPT, RepairAction.GENERATE).status, "BUDGET_EXHAUSTED")
        self.assertLess(session.budget.tokens_remaining, 0)
        self.assertEqual(checker.calls, 0)
        self.assertEqual(session.finish().status, "BUDGET_EXHAUSTED")

    def test_time_threshold_after_model_stops_before_check(self):
        now = [0]
        base = replay_model("already_valid")
        class Slow:
            provider, model = "replay", "simulated-time"
            def generate(self, prompt):
                now[0] = 10
                return base.generate(prompt)
        checker = Checker()
        session = self.session(Slow(), BudgetLimits(wall_seconds=5), checker, lambda: now[0])
        self.assertEqual(session.attempt(PROMPT, RepairAction.GENERATE).status, "BUDGET_EXHAUSTED")
        self.assertEqual(checker.calls, 0)

    def test_exact_token_and_operation_limits_allow_accepted_last_attempt(self):
        session = self.session(replay_model("already_valid"),
            BudgetLimits(max_attempts=1, max_model_calls=1, max_checks=1, max_submissions=1, max_total_tokens=215),
            Checker("VERIFIED"))
        session.attempt(PROMPT, RepairAction.GENERATE)
        self.assertFalse(session.budget.can_attempt)
        self.assertEqual(session.finish().status, "VERIFIED")

    def test_proof_repair_without_previous_proposal_is_rejected(self):
        session = self.session()
        with self.assertRaises(FlowError):
            session.attempt(PROMPT, RepairAction.REPAIR_PROOF)

    def test_claimed_success_without_service_finish_is_rejected(self):
        result = execute_repair(ROOT, replay_model("already_valid"),
                                flow=lambda view, session: "VERIFIED", artifact_root=self.work)
        self.assertEqual(result.status, "CONTROLLER_ERROR")

    def test_seed_is_validated_snapshotted_and_charged(self):
        def initial(view, session):
            reply = session.generate(PROMPT)
            return session.check(session.render(session.parse(reply.text)))
        seed = execute_one_shot(ROOT, replay_model("proof_then_valid"), flow=initial,
                                checker=Checker(), artifact_root=self.work / "old")
        destination = self.work / "new"
        destination.mkdir()
        session = RepairSession(ROOT, self.task, replay_model("already_valid"), destination, checker=Checker("VERIFIED"))
        session.seed(seed.report_path)
        self.assertEqual((session.model_calls, session.checks), (1, 1))
        self.assertTrue((destination / "seed/Candidate.lean").is_file())
        session.attempt(PROMPT, RepairAction.REPAIR_PROOF)
        self.assertEqual((session.model_calls, session.checks), (2, 2))
        self.assertEqual(session.finish().status, "VERIFIED")

    def test_seed_with_modified_source_is_rejected(self):
        def initial(view, session):
            reply = session.generate(PROMPT)
            return session.check(session.render(session.parse(reply.text)))
        seed = execute_one_shot(ROOT, replay_model("proof_then_valid"), flow=initial,
                                checker=Checker(), artifact_root=self.work / "old")
        (seed.report_path.parent / "Candidate.lean").write_text("changed")
        destination = self.work / "new"
        destination.mkdir()
        session = RepairSession(ROOT, self.task, replay_model("already_valid"), destination)
        with self.assertRaises(ValueError):
            session.seed(seed.report_path)


if __name__ == "__main__":
    unittest.main()
