"""Learner policy checks; these need neither Docker nor an API key."""

from dataclasses import replace
from pathlib import Path
import unittest

from agent.proposal import Proposal
from agent.repair import choose_action
from agent.repair_support import (Attempt, BudgetState, RepairAction, REGENERATE_STATUSES, TERMINAL_ERRORS)


AVAILABLE = BudgetState(True, None, 3, 3, 3, 3, 10000, 60, True)


def observed(status, *, proposal=True, counterexample=None):
    return Attempt(1, RepairAction.GENERATE, status,
                   Proposal("if b ≤ a then some (a - b) else none", "by simp") if proposal else None,
                   None, "Actual diagnostic", "", Path("unused-result.json"), counterexample)


class RepairPolicyTests(unittest.TestCase):
    def test_start_with_generation(self):
        self.assertEqual(choose_action((), AVAILABLE), RepairAction.GENERATE)

    def test_stop_after_success(self):
        self.assertEqual(choose_action((observed("VERIFIED"),), AVAILABLE), RepairAction.STOP)

    def test_stop_without_available_budget(self):
        exhausted = replace(AVAILABLE, can_attempt=False, reason="model-call limit", model_calls_remaining=0)
        for history in ((), (observed("ELABORATION_FAILED"),), (observed("INVALID_PROPOSAL"),)):
            self.assertEqual(choose_action(history, exhausted), RepairAction.STOP)

    def test_proof_failure_preserves_implementation(self):
        self.assertEqual(choose_action((observed("ELABORATION_FAILED"),), AVAILABLE), RepairAction.REPAIR_PROOF)

    def test_checked_counterexample_justifies_regeneration(self):
        # Synthetic, independently reviewed policy input; not inferred from a Lean exit code.
        failure = observed("ELABORATION_FAILED", counterexample="candidate 3 5 = some 0, expected none")
        self.assertEqual(choose_action((failure,), AVAILABLE), RepairAction.REGENERATE)

    def test_missing_proposal_cannot_use_proof_only_repair(self):
        self.assertEqual(choose_action((observed("ELABORATION_FAILED", proposal=False),), AVAILABLE),
                         RepairAction.REGENERATE)

    def test_format_incomplete_rejected_and_limited_attempts_regenerate(self):
        for status in REGENERATE_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(choose_action((observed(status),), AVAILABLE), RepairAction.REGENERATE)

    def test_terminal_and_unknown_errors_stop(self):
        for status in (*TERMINAL_ERRORS, "BUDGET_EXHAUSTED", "UNKNOWN_STATUS"):
            with self.subTest(status=status):
                self.assertEqual(choose_action((observed(status),), AVAILABLE), RepairAction.STOP)


if __name__ == "__main__":
    unittest.main()
