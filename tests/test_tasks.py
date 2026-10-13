"""Validate the development corpus and deterministic repair fixture."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from agent.schema import Candidate, Task


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"


class TaskCorpusTests(unittest.TestCase):
    def test_manifests_are_disjoint_and_cover_each_task_once(self) -> None:
        dev = json.loads((TASKS / "dev.json").read_text())
        evaluation = json.loads((TASKS / "eval.json").read_text())
        self.assertEqual(len(dev), 10)
        self.assertEqual(len(dev), len(set(dev)))
        self.assertEqual(len(evaluation), len(set(evaluation)))
        self.assertFalse(set(dev) & set(evaluation))
        discovered = {p.parent.name for p in TASKS.glob("*/task.json")}
        self.assertEqual(discovered, set(dev) | set(evaluation))
        for split, ids in (("dev", dev), ("eval", evaluation)):
            for task_id in ids:
                with self.subTest(task=task_id):
                    task = Task.load(TASKS / task_id / "task.json")
                    self.assertEqual(task.id, task_id)
                    self.assertEqual(task.split, split)

    def test_contracts_and_references_are_separate_and_complete(self) -> None:
        categories = set()
        for path in TASKS.glob("*/task.json"):
            with self.subTest(task=path.parent.name):
                raw = json.loads(path.read_text())
                self.assertEqual(set(raw), {
                    "id", "title", "category", "split", "specification",
                    "signature", "constraints", "forbidden_identifiers",
                })
                task = Task.load(path)
                categories.add(task.category)
                self.assertRegex(task.specification, r"def Spec \(f : .+\) : Prop :=")
                self.assertTrue(task.signature.startswith("("))
                self.assertGreater(len(task.constraints), 0)
                candidate = Candidate.parse((path.parent / "reference.json").read_text())
                self.assertTrue(candidate.proof.startswith("by\n"))
                self.assertNotRegex(candidate.implementation, r"(?m)^\s*(def|theorem|axiom|opaque)\b")
                self.assertNotRegex(candidate.implementation + "\n" + candidate.proof,
                                    r"\b(sorry|admit|sorryAx|native_decide|ofReduceBool|unsafe|axiom)\b")
                self.assertEqual(len(task.digest), 64)
        self.assertEqual(categories, {"arithmetic", "lists", "program_transformation"})

    def test_repair_fixture_revises_the_program_and_proof(self) -> None:
        records = json.loads((ROOT / "examples/checked_subtraction_repair.json").read_text())
        self.assertEqual(len(records), 2)
        wrong, repaired = [Candidate.parse(json.dumps(record)) for record in records]
        self.assertEqual(wrong.implementation, "some (a - b)")
        self.assertIn("simp [candidate]", wrong.proof)
        self.assertNotEqual(wrong.implementation, repaired.implementation)
        self.assertNotEqual(wrong.proof, repaired.proof)
        reference = Candidate.parse((TASKS / "checked_subtraction/reference.json").read_text())
        self.assertEqual(repaired, reference)

    def test_accumulator_reference_states_the_generalized_invariant(self) -> None:
        task = Task.load(TASKS / "accumulator_reverse/task.json")
        candidate = Candidate.parse((TASKS / "accumulator_reverse/reference.json").read_text())
        self.assertIn("let rec go", candidate.implementation)
        self.assertIn("∀ rest acc : List Nat", candidate.proof)
        self.assertIn("List.reverse", task.forbidden_identifiers)
        # The specification and proof may use reverse; the implementation may not.
        self.assertIn("xs.reverse", task.specification)
        self.assertFalse(re.search(r"\b(?:List\.)?reverse\b", candidate.implementation))


if __name__ == "__main__":
    unittest.main()
