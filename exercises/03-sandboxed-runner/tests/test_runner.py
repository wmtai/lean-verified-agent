"""Supplied infrastructure regressions: reviewed processes and mocked Docker.

Learners work on Lean/agent exercises; these tests maintain the runner for them.
No Lean source is executed on the host. Live checks are in test_integration.py.
"""

from dataclasses import replace
import hashlib
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
    CONTROL_OUTPUT_BYTES, CONTROL_TIMEOUT_SECONDS, MAX_SOURCE_BYTES,
    ContainerRun, ContainerState, DockerLeanRunner, Outcome, ProcessResult,
    RunnerLimits, WorkerImage, classify_result, docker_create_command, run_bounded,
)
from agent.task import Task


ROOT = Path(__file__).resolve().parents[3]
IMAGE_ID = "sha256:" + "a" * 64
NAME = "lva-ex03-" + "b" * 32
VERSION = b"Lean (version 4.34.1, x86_64-unknown-linux-gnu, commit test)\n"
DAEMON_INFO = {"OSType": "linux", "MemoryLimit": True, "SwapLimit": True,
               "CpuCfsQuota": True, "PidsLimit": True, "Warnings": None}


def process(code=0, stdout=b"", stderr=b"", **kwargs):
    return ProcessResult(("test-command",), code, stdout, stderr, 0.05, **kwargs)


def container(code=0, stdout=b"", stderr=b"", **kwargs):
    return ContainerRun(process(code, stdout, stderr, **kwargs),
                        ContainerState("exited", code, False, ""))


class BoundedProcessTests(unittest.TestCase):
    def execute(self, script, *, timeout=2, limit=65536):
        return run_bounded([sys.executable, "-c", script],
                           timeout_seconds=timeout, max_output_bytes=limit)

    def test_captures_both_streams_and_success(self):
        result = self.execute("import sys; print('out'); print('err', file=sys.stderr)")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"out\n")
        self.assertEqual(result.stderr, b"err\n")
        self.assertFalse(result.timed_out)
        self.assertFalse(result.output_limit_exceeded)
        self.assertGreaterEqual(result.elapsed_seconds, 0)

    def test_preserves_failure_diagnostics(self):
        result = self.execute("import sys; print('observed failure', file=sys.stderr); sys.exit(1)")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"observed failure", result.stderr)
        self.assertIsNone(result.startup_error)

    def test_os_launch_failure_is_a_result(self):
        result = run_bounded(["/definitely/missing/lva-program"],
                             timeout_seconds=1, max_output_bytes=1000)
        self.assertIsNone(result.returncode)
        self.assertTrue(result.startup_error)
        self.assertFalse(result.timed_out)

    def test_timeout_keeps_partial_output_and_returns_promptly(self):
        started = time.monotonic()
        result = self.execute("import time; print('started', flush=True); time.sleep(30)", timeout=0.2)
        self.assertTrue(result.timed_out)
        self.assertIn(b"started", result.stdout)
        self.assertLess(time.monotonic() - started, 2)

    def test_output_limit_is_combined_and_stops_the_process(self):
        result = self.execute(
            "import os\nwhile True:\n os.write(1, b'x' * 4096)\n os.write(2, b'y' * 4096)",
            limit=1024,
        )
        self.assertTrue(result.output_limit_exceeded)
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 1024)
        self.assertFalse(result.timed_out)

    def test_large_stderr_does_not_deadlock_stdout(self):
        result = self.execute("import os; os.write(2, b'e' * 150000); os.write(1, b'o' * 150000)",
                              limit=400000)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"o" * 150000)
        self.assertEqual(result.stderr, b"e" * 150000)

    def test_diagnostics_are_captured_as_original_bytes(self):
        result = self.execute("import os; os.write(1, bytes([255, 0, 10]))")
        self.assertEqual(result.stdout, bytes([255, 0, 10]))

    def test_timed_out_descendant_cannot_write_later(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant-survived"
            child = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(marker)!r}).write_text('bad')"
            script = ("import subprocess, sys, time; "
                      f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)")
            result = self.execute(script, timeout=0.2)
            self.assertTrue(result.timed_out)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "Timeout must terminate the whole process group")

    def test_descendant_cannot_outlive_a_successfully_exited_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant-survived"
            child = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(marker)!r}).write_text('bad')"
            script = ("import subprocess, sys; "
                      f"subprocess.Popen([sys.executable, '-c', {child!r}], "
                      "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)")
            result = self.execute(script)
            self.assertEqual(result.returncode, 0)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "Completed calls must clean up remaining descendants")

    def test_invalid_limits_and_shell_strings_are_rejected(self):
        for command, timeout, limit in (
            ("echo hi", 1, 100), ([], 1, 100), ([7], 1, 100),
            ([sys.executable], 0, 100), ([sys.executable], float("nan"), 100),
            ([sys.executable], True, 100), ([sys.executable], 1, False),
            ([sys.executable], 1, 0),
        ):
            with self.subTest(command=command, timeout=timeout, limit=limit), self.assertRaises(ValueError):
                run_bounded(command, timeout_seconds=timeout, max_output_bytes=limit)


class SandboxCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lva input ")
        self.input = Path(self.temporary.name)
        (self.input / "Candidate.lean").write_text("-- reviewed test input\n")
        self.image = WorkerImage(IMAGE_ID, "c" * 64, "4.34.1")
        self.limits = RunnerLimits()

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, **kwargs):
        arguments = {"docker_binary": "/usr/bin/docker", "image": self.image,
                     "input_directory": self.input, "container_name": NAME,
                     "limits": self.limits, "lean_arguments": ("-j1", "/input/Candidate.lean")}
        arguments.update(kwargs)
        return docker_create_command(**arguments)

    def test_required_isolation_and_resource_controls(self):
        command = self.command()
        self.assertEqual(command[:2], ["/usr/bin/docker", "create"])
        self.assertEqual(command[-3:], [IMAGE_ID, "-j1", "/input/Candidate.lean"])
        required = {
            "--name": NAME, "--network": "none", "--user": "1000:1000", "--cap-drop": "ALL",
            "--security-opt": "no-new-privileges=true", "--pull": "never",
            "--pids-limit": "64", "--memory": "512m", "--memory-swap": "512m",
            "--workdir": "/trusted", "--entrypoint": "/opt/lean/bin/lean",
            "--log-driver": "none", "--shm-size": "8m", "--ulimit": "nofile=128:128",
            "--restart": "no",
        }
        for flag, value in required.items():
            with self.subTest(flag=flag):
                self.assertEqual(command[command.index(flag) + 1], value)
        self.assertEqual(float(command[command.index("--cpus") + 1]), 1.0)
        for flag in ("--read-only", "--init", "--no-healthcheck"):
            self.assertIn(flag, command)
        tmpfs = command[command.index("--tmpfs") + 1]
        self.assertEqual(tmpfs.split(":"), ["/tmp", "rw,noexec,nosuid,nodev,size=32m,mode=1777"])

    def test_mount_is_exactly_the_one_input_directory_read_only(self):
        command = self.command()
        self.assertEqual(command.count("--mount"), 1)
        self.assertEqual(command[command.index("--mount") + 1],
                         f"type=bind,source={self.input.resolve()},target=/input,readonly")
        for forbidden in ("--volume", "-v", "--env-file", "--privileged", "--use-api-socket",
                          "--pid", "--ipc", "--device", "--rm"):
            self.assertNotIn(forbidden, command)
        environment = [command[index + 1] for index, value in enumerate(command) if value == "--env"]
        self.assertEqual(set(environment), {"HOME=/tmp", "PATH=/opt/lean/bin:/usr/bin:/bin",
                                           "LEAN_PATH=/trusted/.lake/build/lib/lean"})

    def test_version_check_uses_same_policy_without_candidate_argument(self):
        command = self.command(lean_arguments=("--version",))
        self.assertEqual(command[-2:], [IMAGE_ID, "--version"])
        self.assertIn("--read-only", command)

    def test_rejects_mutable_images_bad_names_and_arbitrary_commands(self):
        for changes in (
            {"image": replace(self.image, image_id="ubuntu:latest")},
            {"container_name": "an-existing-user-container"},
            {"lean_arguments": ("--run", "/input/Candidate.lean")},
            {"lean_arguments": ("/bin/sh", "-c", "anything")},
            {"limits": replace(self.limits, pids=0)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.command(**changes)

    def test_rejects_extra_files_and_input_symlinks(self):
        secret = self.input / ".env"
        secret.write_text("fake protected credential")
        with self.assertRaises(ValueError):
            self.command()
        secret.unlink()
        candidate = self.input / "Candidate.lean"
        candidate.unlink()
        candidate.symlink_to(ROOT / "lean-toolchain")
        with self.assertRaises(ValueError):
            self.command()

    def test_rejects_missing_directories_and_mount_option_injection(self):
        for name in ("unsafe,path", "unsafe\npath"):
            directory = self.input / name
            directory.mkdir()
            (directory / "Candidate.lean").write_text("-- reviewed input")
        for directory in (self.input / "missing", self.input / "unsafe,path", self.input / "unsafe\npath"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.command(input_directory=directory)

    def test_rejects_a_symlink_to_an_otherwise_valid_input_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            link = Path(temporary) / "input-link"
            link.symlink_to(self.input, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.command(input_directory=link)


class ClassificationTests(unittest.TestCase):
    def test_success_is_elaborated_without_a_final_verdict(self):
        self.assertEqual(classify_result(container()), Outcome.ELABORATED)
        self.assertNotIn("VERIFIED", [item.value for item in Outcome])

    def test_syntax_and_unsolved_proofs_are_failures_with_preserved_evidence(self):
        for output in (b"error: unexpected token", b"error: unsolved goals"):
            run = container(1, stdout=output)
            self.assertEqual(classify_result(run), Outcome.ELABORATION_FAILED)
            self.assertEqual(run.process.stdout, output)

    def test_time_and_output_limits_have_distinct_statuses(self):
        self.assertEqual(classify_result(ContainerRun(process(None, timed_out=True), None)), Outcome.TIMEOUT)
        self.assertEqual(classify_result(ContainerRun(process(None, output_limit_exceeded=True), None)),
                         Outcome.OUTPUT_LIMIT_EXCEEDED)

    def test_transport_crash_oom_and_cleanup_failures_are_infrastructure_errors(self):
        for run in (
            ContainerRun(process(0), None),
            ContainerRun(process(0), ContainerState("running", 0, False, "")),
            ContainerRun(process(137), ContainerState("exited", 137, True, "")),
            ContainerRun(process(0), ContainerState("exited", 0, False, "failed to start")),
            ContainerRun(process(1), ContainerState("exited", 0, False, "")),
            container(125), container(126), container(127), container(139), container(-9),
            replace(container(), cleanup_error="container removal failed"),
            replace(container(), infrastructure_error="daemon unavailable"),
            ContainerRun(process(None, startup_error="missing executable"), None),
        ):
            with self.subTest(run=run):
                self.assertEqual(classify_result(run), Outcome.INFRASTRUCTURE_ERROR)


class ContainerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.input = Path(self.temporary.name)
        (self.input / "Candidate.lean").write_text("-- reviewed input")
        self.runner = DockerLeanRunner(WorkerImage(IMAGE_ID, "c" * 64, "4.34.1"))
        self.state = json.dumps({"Status": "exited", "ExitCode": 0,
                                 "OOMKilled": False, "Error": ""}).encode()

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, observations):
        with patch("agent.sandbox.run_bounded", side_effect=observations) as execute:
            result = self.runner._invoke_container(self.input, NAME, ("-j1", "/input/Candidate.lean"))
        return result, execute.call_args_list

    def test_create_attach_inspect_remove_order_and_limits(self):
        result, calls = self.invoke([process(stdout=b"container-id"), process(stdout=b"checked"),
                                     process(stdout=self.state), process()])
        self.assertEqual(classify_result(result), Outcome.ELABORATED)
        self.assertEqual([list(call.args[0])[1] for call in calls], ["create", "start", "inspect", "rm"])
        self.assertEqual(list(calls[1].args[0]), ["docker", "start", "--attach", NAME])
        self.assertEqual(list(calls[2].args[0]), ["docker", "inspect", "--format", "{{json .State}}", NAME])
        self.assertEqual(list(calls[3].args[0]), ["docker", "rm", "--force", NAME])
        self.assertEqual(calls[1].kwargs["timeout_seconds"], self.runner.limits.wall_seconds)
        for call in (calls[0], calls[2], calls[3]):
            self.assertEqual(call.kwargs["timeout_seconds"], CONTROL_TIMEOUT_SECONDS)
            self.assertEqual(call.kwargs["max_output_bytes"], CONTROL_OUTPUT_BYTES)

    def test_create_failure_never_starts_and_still_cleans_up(self):
        result, calls = self.invoke([process(125, stderr=b"daemon unavailable"), process()])
        self.assertEqual(classify_result(result), Outcome.INFRASTRUCTURE_ERROR)
        self.assertEqual([list(call.args[0])[1] for call in calls], ["create", "rm"])
        self.assertIn(b"daemon unavailable", result.process.stderr)

    def test_timeout_removes_daemon_work_without_inspection_first(self):
        result, calls = self.invoke([process(), process(None, stdout=b"partial", timed_out=True), process()])
        self.assertEqual(classify_result(result), Outcome.TIMEOUT)
        self.assertEqual([list(call.args[0])[1] for call in calls], ["create", "start", "rm"])
        self.assertIsNone(result.state)
        self.assertEqual(result.process.stdout, b"partial")

    def test_output_overflow_also_removes_container(self):
        result, calls = self.invoke([process(), process(None, output_limit_exceeded=True), process()])
        self.assertEqual(classify_result(result), Outcome.OUTPUT_LIMIT_EXCEEDED)
        self.assertEqual([list(call.args[0])[1] for call in calls], ["create", "start", "rm"])

    def test_unreadable_container_state_is_infrastructure_failure(self):
        result, calls = self.invoke([process(), process(), process(stdout=b"not-json"), process()])
        self.assertEqual(classify_result(result), Outcome.INFRASTRUCTURE_ERROR)
        self.assertEqual(list(calls[-1].args[0])[1], "rm")

    def test_inspection_failure_is_not_a_proof_failure(self):
        result, calls = self.invoke([process(), process(), process(1, stderr=b"lost daemon"), process()])
        self.assertEqual(classify_result(result), Outcome.INFRASTRUCTURE_ERROR)
        self.assertEqual(list(calls[-1].args[0])[1], "rm")

    def test_cleanup_failure_overrides_success(self):
        result, _ = self.invoke([process(), process(), process(stdout=self.state),
                                 process(1, stderr=b"cannot remove container")])
        self.assertTrue(result.cleanup_error)
        self.assertEqual(classify_result(result), Outcome.INFRASTRUCTURE_ERROR)


class LeanRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.temporary.name)
        self.task = Task.load(ROOT, "checked_subtraction")
        self.image = WorkerImage(IMAGE_ID, self.task.digest, "4.34.1")
        self.runner = DockerLeanRunner(self.image)
        proposal = Proposal.from_json((ROOT / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text())
        self.source = render_candidate(self.task, proposal)

    def tearDown(self):
        self.temporary.cleanup()

    def check(self, observations=None, daemon=None):
        def preflight_result(command, **kwargs):
            if list(command)[1] == "context":
                return process(stdout=b'"unix:///tmp/test-docker.sock"')
            return daemon if daemon is not None else process(stdout=json.dumps(DAEMON_INFO).encode())

        with patch.dict(os.environ, {"DOCKER_HOST": "", "DOCKER_CONTEXT": ""}), \
                patch("agent.sandbox.run_bounded", side_effect=preflight_result) as preflight, \
                patch.object(self.runner, "_invoke_container", side_effect=(
                [container(stdout=VERSION), container()] if observations is None else observations
        )) as invoke, patch("subprocess.Popen", side_effect=AssertionError("Host execution bypassed run_bounded")):
            result = self.runner.check(self.task, self.source, artifact_root=self.artifacts)
        return result, preflight, invoke

    def test_success_saves_source_capped_logs_actual_version_and_provenance(self):
        observations = [container(stdout=VERSION), container(stdout=b"checked\n", stderr=b"warning\n")]
        result, _, invoke = self.check(observations)
        self.assertEqual(result.status, Outcome.ELABORATED)
        self.assertEqual(result.lean_version, "4.34.1")
        self.assertEqual(result.work_directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(result.stdout_path.read_bytes(), b"checked\n")
        self.assertEqual(result.stderr_path.read_bytes(), b"warning\n")
        self.assertEqual((result.work_directory / "Candidate.lean").read_text(), self.source)
        report = json.loads(result.report_path.read_text())
        self.assertEqual(report["status"], "ELABORATED")
        self.assertEqual(report["task_digest"], self.task.digest)
        self.assertEqual(report["source_sha256"], hashlib.sha256(self.source.encode()).hexdigest())
        self.assertEqual(report["image_id"], IMAGE_ID)
        self.assertEqual(report["lean_version"], "4.34.1")
        for field in ("limits", "returncode", "elapsed_seconds", "timed_out",
                      "output_limit_exceeded", "infrastructure_error", "cleanup_error", "container_names"):
            self.assertIn(field, report)
        self.assertEqual(report["container_names"], [call.args[1] for call in invoke.call_args_list])
        self.assertEqual(invoke.call_args_list[0].args[2], ("--version",))
        self.assertEqual(invoke.call_args_list[1].args[2], ("-j1", "/input/Candidate.lean"))
        self.assertNotEqual(invoke.call_args_list[0].args[1], invoke.call_args_list[1].args[1])

    def test_staging_contains_only_candidate_and_is_removed_afterwards(self):
        directories = []

        def observe(directory, name, arguments):
            directories.append(directory)
            self.assertEqual({path.name for path in directory.iterdir()}, {"Candidate.lean"})
            self.assertEqual((directory / "Candidate.lean").read_text(), self.source)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
            self.assertEqual((directory / "Candidate.lean").stat().st_mode & 0o777, 0o644)
            self.assertFalse(directory.is_relative_to(ROOT))
            self.assertFalse(directory.is_relative_to(self.artifacts))
            self.assertRegex(name, r"^lva-ex03-[a-f0-9]{32}$")
            return container(stdout=VERSION if arguments == ("--version",) else b"")

        self.check(observations=observe)
        self.assertTrue(directories)
        self.assertTrue(all(not path.exists() for path in directories))

    def test_each_attempt_is_preserved_and_trusted_sources_stay_unchanged(self):
        trusted = [ROOT / "tasks/development/checked_subtraction/Specification.lean",
                   ROOT / "tasks/development/checked_subtraction/candidate_template.lean"]
        before = [path.read_bytes() for path in trusted]
        first, _, _ = self.check()
        first_report = first.report_path.read_bytes()
        second, _, _ = self.check()
        self.assertNotEqual(first.work_directory, second.work_directory)
        self.assertEqual(first.report_path.read_bytes(), first_report)
        self.assertEqual(before, [path.read_bytes() for path in trusted])

    def test_wrong_image_snapshot_stops_before_candidate_execution(self):
        self.runner.image = replace(self.image, task_digest="d" * 64)
        result, _, invoke = self.check()
        self.assertEqual(result.status, Outcome.INFRASTRUCTURE_ERROR)
        self.assertTrue(result.report_path.is_file())
        invoke.assert_not_called()

    def test_actual_wrong_version_stops_before_source_execution(self):
        result, _, invoke = self.check([container(stdout=VERSION.replace(b"4.34.1", b"4.30.0"))])
        self.assertEqual(result.status, Outcome.INFRASTRUCTURE_ERROR)
        self.assertEqual(result.lean_version, "4.30.0")
        self.assertEqual(invoke.call_count, 1)

    def test_missing_docker_saves_failure_without_a_host_fallback(self):
        result, _, invoke = self.check(daemon=process(None, startup_error="docker is unavailable"))
        self.assertEqual(result.status, Outcome.INFRASTRUCTURE_ERROR)
        self.assertIn("docker", result.report_path.read_text().lower())
        invoke.assert_not_called()

    def test_unsupported_limits_fail_before_running_any_lean(self):
        unsupported = dict(DAEMON_INFO, MemoryLimit=False)
        result, _, invoke = self.check(daemon=process(stdout=json.dumps(unsupported).encode()))
        self.assertEqual(result.status, Outcome.INFRASTRUCTURE_ERROR)
        invoke.assert_not_called()

    def test_invalid_source_is_rejected(self):
        for source in (None, "", " \n", "x" * (MAX_SOURCE_BYTES + 1), "\ud800"):
            with self.subTest(source_type=type(source)), self.assertRaises(ValueError):
                self.runner.check(self.task, source, artifact_root=self.artifacts)

    def test_failed_and_limited_checks_keep_their_status_and_logs(self):
        for observation, expected in (
            (container(1, stdout=b"error: unsolved goals"), Outcome.ELABORATION_FAILED),
            (ContainerRun(process(None, stdout=b"partial", timed_out=True), None), Outcome.TIMEOUT),
            (ContainerRun(process(None, stdout=b"bounded", output_limit_exceeded=True), None),
             Outcome.OUTPUT_LIMIT_EXCEEDED),
        ):
            with self.subTest(expected=expected):
                result, _, _ = self.check([container(stdout=VERSION), observation])
                self.assertEqual(result.status, expected)
                self.assertEqual(result.stdout_path.read_bytes(), observation.process.stdout)
                self.assertEqual(json.loads(result.report_path.read_text())["status"], expected.value)


if __name__ == "__main__":
    unittest.main()
