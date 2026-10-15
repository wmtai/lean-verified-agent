"""Focused learner checks for feedback and proof-only scope instructions."""

import json
from pathlib import Path
import unittest

from agent.proposal import Proposal
from agent.repair_prompts import build_repair_prompt
from agent.repair_support import Attempt, RepairAction
from agent.task import Task
from agent.task_view import public_task


ROOT = Path(__file__).resolve().parents[3]


def previous_attempt(status="ELABORATION_FAILED", parsed=True):
    packet = json.loads((ROOT / "exercises/05-one-shot-generation/fixtures/proof_error.json").read_text())
    text = packet["output"][0]["content"][0]["text"]
    return Attempt(1, RepairAction.GENERATE, status, Proposal.from_json(text) if parsed else None,
                   None, "error: unsolved goals\na b : Nat\nh : a < b\n⊢ candidate a b = none",
                   text if parsed else "Here is JSON: ```{broken}```", Path("unused-result.json"))


class RepairPromptTests(unittest.TestCase):
    def test_proof_repair_includes_task_previous_bodies_and_actual_diagnostics(self):
        task = public_task(Task.load(ROOT, "checked_subtraction"))
        previous = previous_attempt()
        prompt = build_repair_prompt(task, previous, RepairAction.REPAIR_PROOF)
        prompt.validate()
        combined = prompt.system + "\n" + prompt.user
        for required in (task.specification_source.strip(), task.implementation_header, task.theorem_header,
                         previous.status, previous.diagnostics, "REPAIR_PROOF", "implementation_body", "proof_body"):
            self.assertIn(required, combined)
        for body in (previous.proposal.implementation_body, previous.proposal.proof_body):
            self.assertTrue(body in combined or json.dumps(body, ensure_ascii=False) in combined)
        self.assertTrue("exact" in combined.lower() or "unchanged" in combined.lower())
        self.assertNotIn(str(ROOT), combined)

    def test_regeneration_handles_missing_proposal_and_keeps_format_feedback(self):
        task = public_task(Task.load(ROOT, "checked_subtraction"))
        previous = previous_attempt("INVALID_PROPOSAL", parsed=False)
        prompt = build_repair_prompt(task, previous, RepairAction.REGENERATE)
        prompt.validate()
        combined = prompt.system + "\n" + prompt.user
        for required in ("REGENERATE", "INVALID_PROPOSAL", previous.response_text,
                         "implementation_body", "proof_body", task.theorem_header):
            self.assertIn(required, combined)


if __name__ == "__main__":
    unittest.main()
