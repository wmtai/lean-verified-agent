"""Reviewed term-boundary regressions; CI executes these in the Docker verifier."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from agent.controller import run
from agent.model_client import ReplayClient
from agent.schema import Budget, Candidate, Task
from verifier.acceptance import validate_candidate
from verifier.lean_runner import LeanRunner


ROOT = Path(__file__).resolve().parents[1]
TASK = Task("identity", "Identity", "arithmetic", "dev",
            "def Spec (f : Nat → Nat) : Prop := ∀ n, f n = n", "(n : Nat) : Nat")
PROOF = "by intro n; rfl"


@unittest.skipUnless(os.environ.get("RUN_LEAN_INTEGRATION") == "1",
                     "Set RUN_LEAN_INTEGRATION=1 for reviewed term-boundary fixtures")
class CandidateBoundaryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        backend = os.environ.get("LEAN_TEST_BACKEND", "local")
        cls.runner = LeanRunner(ROOT, backend=backend, allow_local=backend == "local")

    def verify(self, candidate):
        with tempfile.TemporaryDirectory() as temporary:
            return self.runner.verify(TASK, candidate, Path(temporary))

    def assert_boundary_rejected(self, candidate, field):
        # These fixtures deliberately pass the lexical policy. The trusted
        # parser, rather than a list of known command keywords, rejects them.
        validate_candidate(TASK, candidate)
        result = self.verify(candidate)
        self.assertFalse(result.accepted, result.diagnostics)
        self.assertEqual(result.category, "policy_rejected", result.diagnostics)
        self.assertEqual(result.lean_checks, 1)
        self.assertIn(f"{field} must be exactly one Lean term", result.diagnostics)
        self.assertNotIn("LEAN_VERIFIED_ACCEPTED:", result.diagnostics)

    def test_extra_declaration_is_rejected_from_both_bodies(self):
        # The extra simplifier declaration is a no-op. No system access or
        # environment changes are attempted by this regression fixture.
        for keyword in ("simproc", "simproc_decl"):
            for field, term in (("implementation", "n"), ("proof", PROOF)):
                with self.subTest(keyword=keyword, field=field):
                    body = f"{term}\n)\n{keyword} noop (_ + _) := (\nfun _ => return .continue"
                    candidate = Candidate(body, PROOF) if field == "implementation" else Candidate("n", body)
                    self.assert_boundary_rejected(candidate, field)

    def test_trailing_input_is_rejected_from_both_bodies(self):
        self.assert_boundary_rejected(Candidate("n\n)\n(0", PROOF), "implementation")
        self.assert_boundary_rejected(Candidate("n", PROOF + "\n)\n(0"), "proof")

    def test_both_bodies_are_parsed_before_implementation_elaboration(self):
        self.assert_boundary_rejected(Candidate("unknownCandidateBody", PROOF + "\n)"), "proof")

    def test_comments_quotes_backslashes_and_unicode_round_trip(self):
        comment = '/- outer " \\ /- nested -/ \b\f\x00\x7f α 😀 -/'
        candidate = Candidate("n " + comment + " -- trailing comment",
                              "by\n  intro n\n  exact rfl " + comment + " -- trailing comment")
        result = self.verify(candidate)
        self.assertTrue(result.accepted, result.diagnostics)
        self.assertEqual(result.lean_checks, 2)

    def test_local_recursion_and_invariant_proof_still_verify(self):
        task = Task.load(ROOT / "tasks" / "accumulator_reverse" / "task.json")
        reference = Candidate(**json.loads((ROOT / "tasks" / task.id / "reference.json").read_text()))
        with tempfile.TemporaryDirectory() as temporary:
            result = self.runner.verify(task, reference, Path(temporary))
        self.assertTrue(result.accepted, result.diagnostics)
        self.assertEqual(result.lean_checks, 2)

    def test_boundary_failure_can_be_repaired_with_correct_check_accounting(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            records = directory / "responses.json"
            records.write_text(json.dumps([
                {"implementation": "n\n)", "proof": PROOF},
                {"implementation": "n", "proof": PROOF},
            ]), encoding="utf-8")
            result = run(TASK, ReplayClient(records), self.runner, "repair",
                         Budget(max_calls=2, max_lean_checks=3), directory / "run")
            self.assertEqual(result.status, "VERIFIED")
            self.assertEqual((result.attempts, result.llm_calls, result.lean_checks), (2, 2, 3))
            self.assertEqual(result.failure_categories, {"policy_rejected": 1})
            self.assertTrue((directory / "run" / "Verified.lean").is_file())


if __name__ == "__main__":
    unittest.main()
