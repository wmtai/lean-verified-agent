"""Supplied infrastructure regressions; only reviewed Python runs on the host."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent.proposal import Proposal
from agent.render import render_candidate
from agent.sandbox import (
    ContainerRun, ContainerState, DockerLeanRunner, Outcome, ProcessResult,
    WorkerImage, classify_result, run_bounded,
)
from agent.task import Task


ROOT = Path(__file__).resolve().parents[3]
IMAGE_ID = "sha256:" + "a" * 64
NAME = "lva-ex03-" + "b" * 32
VERSION = b"Lean (version 4.34.1, x86_64-unknown-linux-gnu, commit test)\n"
DAEMON_INFO = {
    "OSType": "linux", "MemoryLimit": True, "SwapLimit": True,
    "CpuCfsQuota": True, "PidsLimit": True, "Warnings": None,
}


def process(code=0, stdout=b"", stderr=b"", **kwargs):
    return ProcessResult(("reviewed-test-command",), code, stdout, stderr, 0.01, **kwargs)


def container(stdout=b""):
    return ContainerRun(process(stdout=stdout), ContainerState("exited", 0, False, ""))


class BoundedProcessEdgeTests(unittest.TestCase):
    def test_closing_both_streams_does_not_end_a_running_process_early(self):
        started = time.monotonic()
        result = run_bounded(
            [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(30)"],
            timeout_seconds=0.2, max_output_bytes=100,
        )
        self.assertTrue(result.timed_out)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_exact_output_cap_is_allowed(self):
        result = run_bounded(
            [sys.executable, "-c", "import os; os.write(1, b'x' * 100)"],
            timeout_seconds=2, max_output_bytes=100,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"x" * 100)
        self.assertFalse(result.output_limit_exceeded)
        self.assertFalse(result.timed_out)

    def test_exited_parent_with_child_holding_pipes_returns_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant-survived"
            child = (
                "import time; from pathlib import Path; time.sleep(0.6); "
                f"Path({str(marker)!r}).write_text('must not survive')"
            )
            script = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child!r}])"
            started = time.monotonic()
            result = run_bounded(
                [sys.executable, "-c", script],
                timeout_seconds=2, max_output_bytes=100,
            )
            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.timed_out)
            self.assertLess(time.monotonic() - started, 1)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "A child retaining both pipes must still be terminated")


class RuntimePreflightEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.temporary.name)
        self.task = Task.load(ROOT, "checked_subtraction")
        self.runner = DockerLeanRunner(WorkerImage(IMAGE_ID, self.task.digest, "4.34.1"))
        proposal = Proposal.from_json(
            (ROOT / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text()
        )
        self.source = render_candidate(self.task, proposal)

    def tearDown(self):
        self.temporary.cleanup()

    def check(self, *, endpoint="unix:///tmp/docker.sock", docker_host="",
              docker_context="", context_result=None, observations=None):
        def dispatch(command, **kwargs):
            if list(command)[1:] == ["info", "--format", "{{json .}}"]:
                return process(stdout=json.dumps(DAEMON_INFO).encode())
            if list(command)[1:] == [
                "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}",
            ]:
                return (context_result if context_result is not None
                        else process(stdout=json.dumps(endpoint).encode()))
            raise AssertionError(f"Unexpected host command: {command!r}")

        with patch.dict(os.environ, {"DOCKER_HOST": docker_host, "DOCKER_CONTEXT": docker_context}), \
                patch("agent.sandbox.run_bounded", side_effect=dispatch) as preflight, \
                patch.object(self.runner, "_invoke_container", side_effect=(
                    [container(VERSION), container()] if observations is None else observations
                )) as invoke, \
                patch("subprocess.Popen", side_effect=AssertionError("Unexpected host execution")):
            result = self.runner.check(self.task, self.source, artifact_root=self.artifacts)
        return result, preflight, invoke

    def assert_saved_infrastructure_error(self, result):
        self.assertEqual(result.status, Outcome.INFRASTRUCTURE_ERROR)
        report = json.loads(result.report_path.read_text())
        self.assertEqual(report["status"], "INFRASTRUCTURE_ERROR")
        self.assertTrue(report["infrastructure_error"])
        self.assertTrue(result.stdout_path.is_file())
        self.assertTrue(result.stderr_path.is_file())

    def test_remote_context_stops_before_any_worker(self):
        for endpoint in ("ssh://other-host", "tcp://127.0.0.1:2375", "npipe:////./pipe/docker_engine"):
            with self.subTest(endpoint=endpoint):
                result, _, invoke = self.check(endpoint=endpoint)
                self.assert_saved_infrastructure_error(result)
                invoke.assert_not_called()

    def test_unavailable_or_malformed_context_stops_before_any_worker(self):
        observations = (
            process(1, stderr=b"context unavailable"),
            process(None, startup_error="context executable unavailable"),
            process(stdout=b"not JSON"), process(stdout=b"null"), process(stdout=b"123"),
        )
        for observation in observations:
            with self.subTest(observation=observation):
                result, _, invoke = self.check(context_result=observation)
                self.assert_saved_infrastructure_error(result)
                invoke.assert_not_called()

    def test_remote_docker_host_without_context_override_stops_before_any_worker(self):
        result, preflight, invoke = self.check(docker_host="tcp://other-host:2375")
        self.assert_saved_infrastructure_error(result)
        invoke.assert_not_called()
        self.assertFalse(any(list(call.args[0])[1] == "context" for call in preflight.call_args_list))

    def test_selected_context_overrides_docker_host(self):
        result, preflight, invoke = self.check(
            docker_host="tcp://other-host:2375", docker_context="selected-local",
        )
        self.assertEqual(result.status, Outcome.ELABORATED)
        self.assertEqual(invoke.call_count, 2)
        self.assertTrue(any(list(call.args[0])[1] == "context" for call in preflight.call_args_list))

    def test_local_docker_host_avoids_context_lookup(self):
        result, preflight, invoke = self.check(docker_host="unix:///tmp/docker.sock")
        self.assertEqual(result.status, Outcome.ELABORATED)
        self.assertEqual(invoke.call_count, 2)
        self.assertFalse(any(list(call.args[0])[1] == "context" for call in preflight.call_args_list))

    def test_missing_or_malformed_compiler_version_stops_before_source(self):
        for output in (b"", b"different compiler\n", b"Lean (version 4.34)\n", b"\xff\xfe"):
            with self.subTest(output=output):
                result, _, invoke = self.check(observations=[container(output)])
                self.assert_saved_infrastructure_error(result)
                self.assertIsNone(result.lean_version)
                self.assertEqual(invoke.call_count, 1)
                self.assertEqual(invoke.call_args.args[2], ("--version",))


class ContainerCleanupEdgeTests(unittest.TestCase):
    def test_failed_cleanup_overrides_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "Candidate.lean").write_text("-- reviewed input\n")
            runner = DockerLeanRunner(WorkerImage(IMAGE_ID, "c" * 64, "4.34.1"))
            observations = [
                process(), process(None, stdout=b"partial", timed_out=True),
                process(1, stderr=b"daemon refused container removal"),
            ]
            with patch("agent.sandbox.run_bounded", side_effect=observations) as execute:
                result = runner._invoke_container(directory, NAME, ("-j1", "/input/Candidate.lean"))
            self.assertEqual(classify_result(result), Outcome.INFRASTRUCTURE_ERROR)
            self.assertTrue(result.cleanup_error)
            self.assertTrue(result.process.timed_out)
            self.assertEqual(result.process.stdout, b"partial")
            self.assertEqual(
                [list(call.args[0])[1] for call in execute.call_args_list],
                ["create", "start", "rm"],
            )


if __name__ == "__main__":
    unittest.main()
