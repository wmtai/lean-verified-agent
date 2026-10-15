"""Learner task 1 checks: public information and the output contract."""

from dataclasses import fields
from pathlib import Path
import unittest

from agent.model_client import Prompt
from agent.prompts import build_generation_prompt
from agent.task import Task
from agent.task_view import public_task


ROOT = Path(__file__).resolve().parents[3]


class GenerationPromptTests(unittest.TestCase):
    def test_prompt_includes_fixed_task_information_and_response_fields(self):
        view = public_task(Task.load(ROOT, "checked_subtraction"))
        prompt = build_generation_prompt(view)
        self.assertIsInstance(prompt, Prompt)
        prompt.validate()
        combined = prompt.system + "\n" + prompt.user
        for required in (view.specification_source.strip(), view.implementation_type,
                         view.implementation_header, view.theorem_header,
                         view.template_source.strip(), view.lean_toolchain,
                         "implementation_body", "proof_body") + view.permitted_imports:
            with self.subTest(required=required):
                self.assertIn(required, combined)
        for example in view.public_examples:
            for value in (*example.arguments, example.expected):
                self.assertIn(str(value), combined)
        self.assertIn("json", combined.lower())

    def test_view_excludes_evaluator_metadata_and_answers(self):
        view = public_task(Task.load(ROOT, "checked_subtraction"))
        public_fields = {field.name for field in fields(view)}
        self.assertNotIn("metadata_json", public_fields)
        self.assertNotIn("reference_solution", public_fields)
        self.assertNotIn("root", public_fields)
        prompt = build_generation_prompt(view)
        combined = prompt.system + "\n" + prompt.user
        self.assertNotIn(str(ROOT), combined)
        self.assertNotIn("exercises/02-tasks-and-submissions/fixtures/proposal.json", combined)


if __name__ == "__main__":
    unittest.main()
