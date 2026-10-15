"""Opt-in tests of reviewed Lean fixtures inside the completed Docker worker."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent.proposal import Proposal
from agent.render import render_candidate
from agent.sandbox import DockerLeanRunner, Outcome, RunnerLimits, WorkerImage
from agent.task import Task


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "exercises/03-sandboxed-runner/fixtures"


@unittest.skipUnless(os.environ.get("RUN_SANDBOX_INTEGRATION") == "1",
                     "set RUN_SANDBOX_INTEGRATION=1 with the supplied worker image available")
class SandboxIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lva-ex03-tests-")
        self.artifacts = Path(self.temporary.name)
        self.task = Task.load(ROOT, "checked_subtraction")
        path = Path(os.environ.get("LEAN_WORKER_IMAGE_REPORT", str(ROOT / "runs/exercise03/image.json")))
        self.image = WorkerImage.load(path)
        self.runner = DockerLeanRunner(self.image, docker_binary=os.environ.get("DOCKER_BINARY", "docker"))

    def tearDown(self):
        self.temporary.cleanup()

    def check(self, source):
        result = self.runner.check(self.task, source, artifact_root=self.artifacts / "attempts")
        report = json.loads(result.report_path.read_text())
        for name in report["container_names"]:
            self.assertRegex(name, r"^lva-ex03-[a-f0-9]{32}$")
            remaining = subprocess.run([
                self.runner.docker_binary, "container", "ls", "--all", "--filter", f"name={name}",
                "--format", "{{.Names}}",
            ], capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(remaining.returncode, 0, remaining.stderr)
            self.assertEqual(remaining.stdout.strip(), "", f"Container leaked after check: {name}")
        return result

    def test_reviewed_correct_source_elaborates(self):
        proposal = Proposal.from_json((ROOT / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text())
        result = self.check(render_candidate(self.task, proposal))
        self.assertEqual(result.status, Outcome.ELABORATED, result.report_path.read_text())
        self.assertEqual(result.lean_version, "4.34.1")

    def test_syntax_error_is_a_lean_failure(self):
        result = self.check((FIXTURES / "SyntaxError.lean").read_text())
        self.assertEqual(result.status, Outcome.ELABORATION_FAILED, result.report_path.read_text())
        self.assertIn("error:", result.stdout_path.read_text() + result.stderr_path.read_text())

    def test_unsolved_proof_retains_the_observed_goal(self):
        source = (ROOT / "exercises/01-environment/fixtures/WrongProof.lean").read_text()
        result = self.check(source)
        self.assertEqual(result.status, Outcome.ELABORATION_FAILED, result.report_path.read_text())
        self.assertIn("unsolved goals", result.stdout_path.read_text() + result.stderr_path.read_text())

    def test_sleeping_elaboration_is_stopped_and_container_is_removed(self):
        self.runner = DockerLeanRunner(self.image, docker_binary=self.runner.docker_binary,
                                        limits=replace(RunnerLimits(), wall_seconds=2.0))
        result = self.check((FIXTURES / "Timeout.lean").read_text())
        self.assertEqual(result.status, Outcome.TIMEOUT, result.report_path.read_text())
        self.assertIsNone(json.loads(result.report_path.read_text())["cleanup_error"])

    def test_host_canary_secret_and_protected_writes_are_denied(self):
        canary = self.artifacts / "protected-host-secret.txt"
        canary.write_text("fake protected test data")
        source = (FIXTURES / "Isolation.lean").read_text().replace("{{protected_path}}", json.dumps(str(canary)))
        with patch.dict(os.environ, {"LVA_EX03_FAKE_SECRET": "test-value-must-stay-on-host"}):
            result = self.check(source)
        self.assertEqual(result.status, Outcome.ELABORATED, result.report_path.read_text())
        self.assertIn(b"isolation checks passed", result.stdout_path.read_bytes())
        self.assertEqual(canary.read_text(), "fake protected test data")


if __name__ == "__main__":
    unittest.main()
