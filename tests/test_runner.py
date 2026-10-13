import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.schema import Candidate, Task
from verifier.lean_runner import LeanRunner, ProcessResult, run_bounded


ROOT = Path(__file__).resolve().parents[1]
TASK = Task("identity", "Identity", "arithmetic", "dev",
            "def Spec (f : Nat → Nat) : Prop := ∀ n, f n = n", "(n : Nat) : Nat")
CANDIDATE = Candidate("n", "by intro n; rfl")


def successful_mock(command, *, cwd, timeout, env=None, **kwargs):
    """Mock the subprocess protocol only; this does not establish proof validity."""
    source = (Path(cwd) / "Candidate.lean").read_text()
    token = re.search(r'#audit_candidate "([a-f0-9]{32})"', source).group(1)
    return ProcessResult(0, "LEAN_VERIFIED_ACCEPTED:" + token)


class RunnerTests(unittest.TestCase):
    def ready_local_runner(self):
        runner = LeanRunner(ROOT, backend="local", allow_local=True)
        runner._local_ready = True
        runner._lean_binary = "lean"
        return runner

    def test_default_is_docker_and_local_requires_opt_in(self):
        self.assertEqual(LeanRunner(ROOT).backend, "docker")
        with tempfile.TemporaryDirectory() as temporary, patch("verifier.lean_runner.run_bounded") as execute:
            result = LeanRunner(ROOT, backend="local").verify(TASK, CANDIDATE, Path(temporary))
        self.assertFalse(result.accepted)
        self.assertEqual(result.category, "infrastructure_error")
        self.assertEqual(result.lean_checks, 0)
        execute.assert_not_called()

    def test_policy_rejection_never_launches_lean(self):
        with tempfile.TemporaryDirectory() as temporary, patch("verifier.lean_runner.run_bounded") as execute:
            result = LeanRunner(ROOT).verify(TASK, Candidate("sorry", "by rfl"), Path(temporary))
        self.assertEqual(result.category, "policy_rejected")
        self.assertEqual(result.lean_checks, 0)
        execute.assert_not_called()

    def test_success_requires_two_fresh_process_checks(self):
        directories = []
        def execute(*args, **kwargs):
            directories.append(kwargs["cwd"])
            return successful_mock(*args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary, patch("verifier.lean_runner.run_bounded", side_effect=execute):
            result = self.ready_local_runner().verify(TASK, CANDIDATE, Path(temporary))
        self.assertTrue(result.accepted)
        self.assertEqual(result.lean_checks, 2)
        self.assertEqual(len(set(directories)), 2)

    def test_zero_exit_without_trusted_marker_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary, patch("verifier.lean_runner.run_bounded", return_value=ProcessResult(0, "")):
            result = self.ready_local_runner().verify(TASK, CANDIDATE, Path(temporary))
        self.assertFalse(result.accepted)
        self.assertEqual(result.category, "acceptance_rejected")
        self.assertEqual(result.lean_checks, 1)

    def test_second_check_failure_revokes_initial_success(self):
        count = 0
        def execute(*args, **kwargs):
            nonlocal count
            count += 1
            return successful_mock(*args, **kwargs) if count == 1 else ProcessResult(1, "type mismatch")
        with tempfile.TemporaryDirectory() as temporary, patch("verifier.lean_runner.run_bounded", side_effect=execute):
            result = self.ready_local_runner().verify(TASK, CANDIDATE, Path(temporary))
        self.assertFalse(result.accepted)
        self.assertEqual(result.category, "type_error")
        self.assertEqual(result.lean_checks, 2)

    def test_primary_proof_error_precedes_lean_recovery_axiom(self):
        process = ProcessResult(1, "error: unsolved goals\n⊢ False\n"
                                   "error: Trusted audit: unapproved transitive axiom sorryAx")
        self.assertEqual(LeanRunner._failure_category(process, "local"), "unsolved_goals")
        self.assertEqual(LeanRunner._failure_category(
            ProcessResult(1, "error: type mismatch\nTrusted audit: unapproved transitive axiom sorryAx"),
            "local"), "type_error")

    def test_docker_failure_never_falls_back_to_local(self):
        runner = LeanRunner(ROOT)
        with tempfile.TemporaryDirectory() as temporary, patch("verifier.lean_runner.shutil.which", return_value="docker"), \
             patch("verifier.lean_runner.run_bounded", return_value=ProcessResult(125, "Cannot connect to the Docker daemon")) as execute:
            result = runner.verify(TASK, CANDIDATE, Path(temporary))
        self.assertFalse(result.accepted)
        self.assertEqual(result.category, "infrastructure_error")
        self.assertEqual(result.lean_checks, 0)
        self.assertTrue(all(call.args[0][0] == "docker" for call in execute.call_args_list))

    def test_docker_sandbox_has_only_submission_mount(self):
        command, environment = LeanRunner(ROOT)._command(Path("/tmp/submission"), "test-name")
        self.assertIsNone(environment)
        for option in ("--network", "--read-only", "--user", "--cap-drop", "--security-opt",
                       "--pids-limit", "--memory", "--cpus", "--ulimit"):
            self.assertIn(option, command)
        self.assertEqual(command.count("--mount"), 1)
        self.assertIn("type=bind,src=/tmp/submission,dst=/submission,readonly", command)
        self.assertNotIn("--privileged", command)
        with self.assertRaises(ValueError):
            LeanRunner(ROOT, image="--privileged")

    def test_timeout_and_output_limits_fail_closed(self):
        for process in (ProcessResult(-9, "", timed_out=True), ProcessResult(-9, "", output_limited=True)):
            with self.subTest(process=process), tempfile.TemporaryDirectory() as temporary, \
                 patch("verifier.lean_runner.run_bounded", return_value=process):
                result = self.ready_local_runner().verify(TASK, CANDIDATE, Path(temporary))
                self.assertFalse(result.accepted)
                self.assertIn(result.category, {"timeout", "output_limit"})

    def test_real_subprocess_is_killed_at_wall_deadline(self):
        result = run_bounded([sys.executable, "-c", "import time; time.sleep(10)"], cwd=ROOT, timeout=0.15)
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.returncode, 0)

    def test_real_subprocess_output_is_bounded(self):
        result = run_bounded([sys.executable, "-c", "print('x' * 1000000)"], cwd=ROOT,
                             timeout=2, max_output_bytes=1024)
        self.assertTrue(result.output_limited)
        self.assertEqual(len(result.output.encode()), 1024)


@unittest.skipUnless(os.environ.get("RUN_LEAN_INTEGRATION") == "1", "Set RUN_LEAN_INTEGRATION=1 for audited fixture checks")
class RealLeanAuditTests(unittest.TestCase):
    def test_trusted_fixture_accepts_and_wrong_program_fails(self):
        task = Task.load(ROOT / "tasks" / "checked_subtraction" / "task.json")
        reference = Candidate(**json.loads((ROOT / "tasks" / "checked_subtraction" / "reference.json").read_text()))
        runner = LeanRunner(ROOT, backend="local", allow_local=True)
        with tempfile.TemporaryDirectory() as temporary:
            valid = runner.verify(task, reference, Path(temporary) / "valid")
            wrong = runner.verify(task, Candidate("some (a - b)", reference.proof), Path(temporary) / "wrong")
        self.assertTrue(valid.accepted, valid.diagnostics)
        self.assertEqual(valid.lean_checks, 2)
        self.assertFalse(wrong.accepted)
        self.assertEqual(wrong.lean_checks, 1)
        self.assertEqual(wrong.category, "unsolved_goals")

    def test_audit_itself_rejects_sorry_and_arbitrary_axiom(self):
        # Bypass the Python gate only in this controlled test to exercise the
        # trusted Lean checker directly against unfinished/axiomatized proofs.
        runner = LeanRunner(ROOT, backend="local", allow_local=True)
        preparation = runner._prepare_local(30)
        self.assertIsNone(preparation, preparation)
        for declaration in ("theorem candidate_correct : Spec candidate := by sorry",
                            "axiom candidate_correct : Spec candidate",
                            "axiom cheat : ∀ n : Nat, 0 = n\ntheorem candidate_correct : Spec candidate := cheat"):
            source = ("import Std\nimport Trusted.Audit\nnamespace Generated\n"
                      + TASK.specification + "\ndef candidate (n : Nat) : Nat := 0\n"
                      + declaration + '\nend Generated\n#audit_candidate "' + "a" * 32 + '"\n')
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "Candidate.lean").write_text(source)
                command, environment = runner._command(directory, "unused")
                result = run_bounded(command, cwd=directory, env=environment, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("LEAN_VERIFIED_ACCEPTED:", result.output)


if __name__ == "__main__":
    unittest.main()
