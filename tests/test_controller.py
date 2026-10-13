from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent.controller import estimate_prompt_tokens, run
from agent.prompts import generation_messages
from agent.schema import Budget, Candidate, ModelResponse, Task, VerificationResult


TASK = Task("identity", "Identity", "arithmetic", "dev",
            "def Spec (f : Nat → Nat) : Prop := ∀ n, f n = n", "(n : Nat) : Nat")


def response(implementation="n", proof="by intro n; rfl"):
    return ModelResponse(json.dumps({"implementation": implementation, "proof": proof}),
                         input_tokens=1, output_tokens=1, model="test")


class FakeClient:
    provider = "fake"
    model = "test"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, max_output_tokens, timeout_seconds):
        self.calls.append((messages, max_output_tokens, timeout_seconds))
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class FakeRunner:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def verify(self, task, candidate, work_dir, timeout_seconds=None):
        self.calls.append((candidate, timeout_seconds))
        (work_dir / "Candidate.lean").write_text(candidate.implementation + "\n" + candidate.proof)
        return next(self.results)


FAILED = VerificationResult(False, "lean_error", "error: unsolved goals\n⊢ n = n", 0.01, 1)
ACCEPTED = VerificationResult(True, "verified", "kernel and independent check passed", 0.01, 2)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "run"

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, strategy, responses, checks, **limits):
        client = FakeClient(responses)
        runner = FakeRunner(checks)
        budget = Budget(max_tokens=100000, **limits)
        result = run(TASK, client, runner, strategy, budget, self.directory)
        return result, client, runner

    def test_repair_feedback_and_preserved_trace(self):
        result, client, runner = self.execute("repair", [response(proof="by rfl"), response()], [FAILED, ACCEPTED])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual((result.attempts, result.llm_calls, result.lean_checks), (2, 2, 3))
        self.assertEqual(result.proof_revisions, 1)
        feedback = client.calls[1][0][-1]["content"]
        self.assertIn("unsolved goals", feedback)
        self.assertIn("no counterexample", feedback)
        self.assertTrue((self.directory / "attempts/0002/Candidate.lean").exists())
        self.assertTrue((self.directory / "Verified.lean").exists())
        self.assertTrue((self.directory / "attempts/0001/candidate.json").exists())
        summary = json.loads((self.directory / "result.json").read_text())
        self.assertEqual(summary["task_digest"], TASK.digest)
        self.assertEqual(summary["budgets"]["max_calls"], 5)
        self.assertGreater(runner.calls[0][1], 0)

    def test_sampling_has_no_previous_candidate_or_diagnostics(self):
        result, client, _ = self.execute("sampling", [response("n + 0"), response()], [FAILED, ACCEPTED])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(client.calls[0][0], client.calls[1][0])
        self.assertNotIn("unsolved goals", str(client.calls[1][0]))
        self.assertEqual(result.implementation_revisions, 1)

    def test_planning_counts_calls_and_tokens(self):
        plan = ModelResponse("Use identity and reflexivity.", 2, 3, "test")
        result, client, _ = self.execute("planning", [plan, response()], [ACCEPTED])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual((result.llm_calls, result.attempts), (2, 1))
        self.assertEqual((result.input_tokens, result.output_tokens), (3, 4))
        self.assertIn(plan.text, str(client.calls[1][0]))
        self.assertTrue((self.directory / "planning/response.txt").exists())

    def test_planning_cannot_use_an_extra_call(self):
        result, client, runner = self.execute("planning", [ModelResponse("plan", 1, 1)], [], max_calls=1)
        self.assertEqual(result.status, "UNSOLVED_WITHIN_BUDGET")
        self.assertEqual((result.llm_calls, result.attempts, len(runner.calls)), (1, 0, 0))

    def test_one_shot_has_exactly_one_attempt(self):
        result, client, _ = self.execute("one-shot", [response(), response()], [FAILED, ACCEPTED])
        self.assertEqual(result.status, "UNSOLVED_WITHIN_BUDGET")
        self.assertEqual((result.attempts, len(client.calls)), (1, 1))

    def test_reserves_final_independent_check(self):
        result, client, runner = self.execute("repair", [response(), response()], [FAILED, ACCEPTED], max_lean_checks=2)
        self.assertEqual(result.lean_checks, 1)
        self.assertEqual((len(client.calls), len(runner.calls)), (1, 1))

    def test_no_call_when_final_check_cannot_fit(self):
        result, client, runner = self.execute("repair", [response()], [ACCEPTED], max_lean_checks=1)
        self.assertEqual(result.status, "UNSOLVED_WITHIN_BUDGET")
        self.assertEqual((len(client.calls), len(runner.calls)), (0, 0))

    def test_token_exhaustion_prevents_calls(self):
        client, runner = FakeClient([response()]), FakeRunner([ACCEPTED])
        result = run(TASK, client, runner, "repair", Budget(max_tokens=1), self.directory)
        self.assertEqual(result.status, "UNSOLVED_WITHIN_BUDGET")
        self.assertEqual(len(client.calls), 0)

    def test_request_output_is_capped_by_prompt_headroom(self):
        reserve = estimate_prompt_tokens(generation_messages(TASK))
        client, runner = FakeClient([response()]), FakeRunner([ACCEPTED])
        run(TASK, client, runner, "repair", Budget(max_tokens=reserve + 7), self.directory)
        self.assertEqual(client.calls[0][1], 7)

    def test_provider_token_overrun_does_not_allow_verification(self):
        reserve = estimate_prompt_tokens(generation_messages(TASK))
        overrun = ModelResponse(response().text, reserve + 10, 10)
        client, runner = FakeClient([overrun]), FakeRunner([ACCEPTED])
        result = run(TASK, client, runner, "repair", Budget(max_tokens=reserve + 7), self.directory)
        self.assertEqual(result.status, "UNSOLVED_WITHIN_BUDGET")
        self.assertEqual(len(runner.calls), 0)
        self.assertTrue((self.directory / "attempts/0001/candidate.json").exists())

    def test_json_error_reaches_repair_without_lean_check(self):
        result, client, runner = self.execute("repair", [ModelResponse("not json", 1, 1), response()], [ACCEPTED])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.failure_categories["invalid_json"], 1)
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("valid JSON", client.calls[1][0][-1]["content"])

    def test_infrastructure_failure_is_error(self):
        infrastructure = VerificationResult(False, "infrastructure_error", "Docker not found", 0, 0)
        result, _, _ = self.execute("repair", [response()], [infrastructure])
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.failure_categories, {"infrastructure_error": 1})

    def test_api_failure_is_error_and_does_not_log_exception_secrets(self):
        result, _, _ = self.execute("repair", [RuntimeError("secret-api-key")], [])
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.llm_calls, 1)
        self.assertNotIn("secret-api-key", (self.directory / "attempts/0001/call.json").read_text())

    def test_acceptance_with_only_one_check_is_error(self):
        result, _, _ = self.execute("one-shot", [response()], [VerificationResult(True, "verified", "", 0, 1)])
        self.assertEqual(result.status, "ERROR")

    def test_estimated_usage_is_explicit(self):
        result, _, _ = self.execute("one-shot", [ModelResponse(response().text)], [ACCEPTED])
        summary = json.loads((self.directory / "result.json").read_text())
        self.assertTrue(summary["input_usage_estimated"])
        self.assertTrue(summary["output_usage_estimated"])
        self.assertGreater(result.input_tokens, 0)

    def test_existing_run_cannot_be_overwritten(self):
        self.execute("one-shot", [response()], [ACCEPTED])
        with self.assertRaises(ValueError):
            run(TASK, FakeClient([]), FakeRunner([]), "repair", Budget(), self.directory)


if __name__ == "__main__":
    unittest.main()
