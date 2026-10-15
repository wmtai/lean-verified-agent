"""Supplied lesson wiring preserves fixed contracts and execution evidence."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent.sandbox import LeanRunResult, Outcome
from scripts.exercise03_review import LESSON, collect_observations, validate_learner_source


ROOT = Path(__file__).resolve().parents[1]


class FakeRunner:
    def __init__(self, *, learner_status=Outcome.ELABORATION_FAILED, first_status=None):
        self.learner_status = learner_status
        self.first_status = first_status
        self.calls = []

    def check(self, task, source, *, artifact_root):
        self.calls.append(artifact_root.name)
        status = {"syntax_error": Outcome.ELABORATION_FAILED,
                  "proof_error": Outcome.ELABORATION_FAILED,
                  "reviewed_correct": Outcome.ELABORATED,
                  "learner_candidate": self.learner_status}[artifact_root.name]
        if len(self.calls) == 1 and self.first_status is not None:
            status = self.first_status
        artifact_root.mkdir(parents=True)
        directory = Path(tempfile.mkdtemp(dir=artifact_root))
        (directory / "Candidate.lean").write_text(source)
        stdout, stderr, report = directory / "stdout.log", directory / "stderr.log", directory / "result.json"
        stdout.write_bytes(b"retained test diagnostics")
        stderr.write_bytes(b"")
        report.write_text(json.dumps({"status": status.value}))
        return LeanRunResult(status, 0 if status == Outcome.ELABORATED else 1, 0.1,
                             "4.34.1", directory, stdout, stderr, report)


class ExerciseThreeLessonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        files = ["lean-toolchain", "tasks/development/checked_subtraction/task.json",
                 "tasks/development/checked_subtraction/Specification.lean",
                 "tasks/development/checked_subtraction/candidate_template.lean",
                 "exercises/02-tasks-and-submissions/fixtures/proposal.json"]
        files += [str(LESSON / name) for name in (
            "fixtures/ProofError.lean", "fixtures/SyntaxError.lean", "starter/Candidate.lean",
        )]
        for relative in files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)

    def tearDown(self):
        self.temporary.cleanup()

    def collect(self, runner):
        with redirect_stdout(StringIO()):
            return collect_observations(self.root, runner)

    def test_changed_contract_or_unfinished_proof_is_rejected_before_execution(self):
        source = (self.root / LESSON / "starter/Candidate.lean").read_text()
        validate_learner_source(self.root, source)
        for changed in (source.replace("TaskSpec.CheckedSubSpec candidate", "True"),
                        source.replace("if b ≤ a then some (a - b) else none", "some 0"),
                        source + "\n  sorry\n"):
            with self.subTest(changed=changed[-70:]), self.assertRaises(ValueError):
                validate_learner_source(self.root, changed)

    def test_initial_failure_is_saved_as_an_observation_awaiting_review(self):
        runner = FakeRunner()
        report = self.collect(runner)
        self.assertEqual(runner.calls, ["syntax_error", "proof_error", "reviewed_correct", "learner_candidate"])
        self.assertFalse(report["all_expectations_met"])
        self.assertTrue(report["awaiting_manual_review"])
        self.assertTrue(Path(report["session_report"]).is_file())
        for row in report["cases"]:
            self.assertTrue(Path(row["stdout_path"]).is_file())

    def test_successful_reruns_preserve_history_and_do_not_pass_the_lesson_automatically(self):
        first = self.collect(FakeRunner(learner_status=Outcome.ELABORATED))
        first_bytes = Path(first["session_report"]).read_bytes()
        second = self.collect(FakeRunner(learner_status=Outcome.ELABORATED))
        self.assertTrue(first["all_expectations_met"])
        self.assertTrue(first["awaiting_manual_review"])
        self.assertNotEqual(first["session_report"], second["session_report"])
        self.assertEqual(Path(first["session_report"]).read_bytes(), first_bytes)

    def test_infrastructure_error_stops_unchecked_cases_without_math_claims(self):
        runner = FakeRunner(first_status=Outcome.INFRASTRUCTURE_ERROR)
        report = self.collect(runner)
        self.assertEqual(runner.calls, ["syntax_error"])
        self.assertFalse(report["all_expectations_met"])
        self.assertEqual(report["cases"][0]["observed_status"], "INFRASTRUCTURE_ERROR")


if __name__ == "__main__":
    unittest.main()
