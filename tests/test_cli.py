from contextlib import redirect_stdout
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.cli import load_tasks, main
from agent.schema import Task


class ManifestTests(unittest.TestCase):
    def test_only_manifest_members_are_loaded_and_identity_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for identifier in ("selected", "unlisted"):
                folder = root / "tasks" / identifier
                folder.mkdir(parents=True)
                task = Task(identifier, identifier, "arithmetic", "dev",
                            "def Spec (f : Nat → Nat) : Prop := ∀ n, f n = n", "(n : Nat) : Nat")
                (folder / "task.json").write_text(json.dumps(asdict(task)))
            manifest = root / "tasks" / "dev.json"
            manifest.write_text('["selected"]')
            self.assertEqual([t.id for t in load_tasks(root)], ["selected"])
            manifest.write_text('["selected", "selected"]')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_tasks(root)
            (root / "tasks" / "eval.json").write_text('["selected"]')
            with self.assertRaisesRegex(ValueError, "manifest"):
                load_tasks(root, "eval")

    def test_evaluation_returns_failure_for_infrastructure_errors(self):
        for status, expected in (("ERROR", 1), ("UNSOLVED_WITHIN_BUDGET", 0), ("VERIFIED", 0)):
            with self.subTest(status=status), patch("agent.cli.make_runner"), \
                    patch("experiments.evaluate.evaluate_tasks", return_value=[{"status": status}]), \
                    redirect_stdout(StringIO()):
                self.assertEqual(main(["evaluate"]), expected)


if __name__ == "__main__":
    unittest.main()
