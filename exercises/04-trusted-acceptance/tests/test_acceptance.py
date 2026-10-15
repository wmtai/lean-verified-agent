"""Supplied acceptance infrastructure tests; learner repair files stay separate."""

from dataclasses import replace
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.acceptance import AcceptanceImage, AcceptanceRunner, AcceptanceStatus, policy_digest
from agent.proposal import Proposal
from agent.render import render_candidate
from agent.sandbox import ContainerRun, ContainerState, ProcessResult
from agent.task import Task


ROOT = Path(__file__).resolve().parents[3]


def observed(packet=None, *, returncode=0, **kwargs):
    payload = json.dumps(packet).encode() if packet is not None else b"not-json"
    process = ProcessResult(("docker", "start"), returncode, payload, b"", 0.1, **kwargs)
    return ContainerRun(process, ContainerState("exited", returncode, False, ""))


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.temporary.name)
        self.task = Task.load(ROOT, "checked_subtraction")
        self.source = "-- reviewed protocol test source\n"
        self.image = AcceptanceImage("sha256:" + "a" * 64, self.task.digest, "4.34.1", policy_digest(ROOT))
        self.runner = AcceptanceRunner(self.image, root=ROOT)
        self.data = b"serialized proof test data\n"
        self.export = {"protocol": 1, "stage": "export", "lean_version": "4.34.1", "status": "EXPORTED",
                       "source_sha256": hashlib.sha256(self.source.encode()).hexdigest(),
                       "export_sha256": hashlib.sha256(self.data).hexdigest(),
                       "export_b64": base64.b64encode(self.data).decode()}
        self.verify = {"protocol": 1, "stage": "verify", "lean_version": "4.34.1", "status": "VERIFIED",
                       "comparator": {"returncode": 0, "stdout": "COMPARATOR_ACCEPTED\n", "stderr": ""}}

    def tearDown(self):
        self.temporary.cleanup()

    def check(self, observations):
        with patch.object(self.runner, "_preflight"), \
                patch.object(self.runner, "_invoke_container", side_effect=observations) as invoke:
            result = self.runner.check(self.task, self.source, artifact_root=self.artifacts)
        return result, invoke

    def test_only_fresh_verified_data_can_grant_acceptance(self):
        inputs = []
        def inspect(directory, name, arguments):
            mode = arguments[0]
            filenames = {path.name for path in directory.iterdir()}
            inputs.append((mode, name, filenames))
            return observed(self.export if mode == "export" else self.verify)
        result, _ = self.check(inspect)
        self.assertEqual(result.status, AcceptanceStatus.VERIFIED)
        self.assertEqual(inputs[0][2], {"Candidate.lean"})
        self.assertEqual(inputs[1][2], {"solution.ndjson"})
        self.assertNotEqual(inputs[0][1], inputs[1][1])
        self.assertEqual((result.work_directory / "solution.ndjson").read_bytes(), self.data)
        self.assertNotIn("export_b64", result.report_path.read_text())

    def test_export_stage_cannot_claim_verified(self):
        result, invoke = self.check([observed(dict(self.export, status="VERIFIED"))])
        self.assertEqual(result.status, AcceptanceStatus.INFRASTRUCTURE_ERROR)
        self.assertEqual(invoke.call_count, 1)

    def test_bad_or_missing_serialized_data_stops_before_verifier(self):
        for changes in ({"export_sha256": "b" * 64}, {"export_b64": "***"},
                        {"export_b64": ""}, {"source_sha256": "c" * 64}):
            with self.subTest(changes=changes):
                result, invoke = self.check([observed(dict(self.export, **changes))])
                self.assertEqual(result.status, AcceptanceStatus.INFRASTRUCTURE_ERROR)
                self.assertEqual(invoke.call_count, 1)

    def test_elaboration_success_and_a_printed_claim_are_insufficient(self):
        rejected = dict(self.verify, status="SUBMISSION_REJECTED",
                        comparator={"returncode": 1, "stdout": "", "stderr": "Illegal axiom detected"})
        result, _ = self.check([observed(self.export), observed(rejected)])
        self.assertEqual(result.status, AcceptanceStatus.SUBMISSION_REJECTED)
        forged = dict(self.verify, comparator={"returncode": 1, "stdout": "COMPARATOR_ACCEPTED\n"})
        result, _ = self.check([observed(self.export), observed(forged)])
        self.assertEqual(result.status, AcceptanceStatus.INFRASTRUCTURE_ERROR)

    def test_missing_verifier_or_cleanup_error_cannot_accept(self):
        for bad in (observed(returncode=1), replace(observed(self.verify), cleanup_error="worker remained running")):
            with self.subTest(bad=bad):
                result, _ = self.check([observed(self.export), bad])
                self.assertEqual(result.status, AcceptanceStatus.INFRASTRUCTURE_ERROR)

    def test_worker_timeout_and_output_overflow_remain_distinct(self):
        for flag, expected in (("timed_out", AcceptanceStatus.TIMEOUT),
                               ("output_limit_exceeded", AcceptanceStatus.OUTPUT_LIMIT_EXCEEDED)):
            result, _ = self.check([observed(returncode=-9, **{flag: True})])
            self.assertEqual(result.status, expected)

    def test_invalid_packet_or_actual_version_cannot_accept(self):
        for run in (observed(), observed(dict(self.export, lean_version="4.30.0")),
                    observed(dict(self.export, stage="verify")), observed(dict(self.export, protocol=True))):
            with self.subTest(run=run):
                result, _ = self.check([run])
                self.assertEqual(result.status, AcceptanceStatus.INFRASTRUCTURE_ERROR)

    def test_verification_mount_cannot_include_source_or_olean_files(self):
        directory = self.artifacts / "input"
        directory.mkdir()
        (directory / "solution.ndjson").write_bytes(self.data)
        name = "lva-ex04-" + "b" * 32
        command = self.runner._create_command(directory, name, ("verify",))
        for flag in ("--read-only", "--network", "--cap-drop", "--security-opt", "--memory", "--pids-limit"):
            self.assertIn(flag, command)
        self.assertEqual(command.count("--mount"), 1)
        self.assertEqual(command[-2:], ["/opt/acceptance/worker.py", "verify"])
        (directory / "Candidate.lean").write_text(self.source)
        with self.assertRaises(ValueError):
            self.runner._create_command(directory, name, ("verify",))

    def test_changed_trusted_policy_fails_before_candidate_execution(self):
        self.runner.acceptance_image = replace(self.image, policy_digest="d" * 64)
        with patch.object(self.runner, "_invoke_container") as invoke:
            result = self.runner.check(self.task, self.source, artifact_root=self.artifacts)
        self.assertEqual(result.status, AcceptanceStatus.INFRASTRUCTURE_ERROR)
        invoke.assert_not_called()


@unittest.skipUnless(os.environ.get("RUN_ACCEPTANCE_INTEGRATION") == "1",
                     "set RUN_ACCEPTANCE_INTEGRATION=1 with the prepared acceptance image")
class AcceptanceIntegrationTests(unittest.TestCase):
    def test_noncomputable_implementation_has_no_executable_smoke_result(self):
        image = AcceptanceImage.load(ROOT / "runs/exercise04/image.json")
        runner = AcceptanceRunner(image, root=ROOT)
        source = (ROOT / "exercises/04-trusted-acceptance/fixtures/Noncomputable.lean").read_text()
        result = runner.check(Task.load(ROOT, "checked_subtraction"), source,
                              artifact_root=ROOT / "runs/exercise04/noncomputable-check")
        self.assertEqual(result.status, AcceptanceStatus.SUBMISSION_REJECTED, result.report_path.read_text())
        report = json.loads(result.report_path.read_text())
        self.assertEqual(report["worker_results"]["export"]["compilation"]["returncode"], 0)
        self.assertNotEqual(report["worker_results"]["export"]["smoke"]["returncode"], 0)

    def test_valid_solution_and_all_policy_rejection_examples(self):
        from scripts.exercise04_review import collect
        image = AcceptanceImage.load(ROOT / "runs/exercise04/image.json")
        runner = AcceptanceRunner(image, root=ROOT)
        report = collect(ROOT, runner, examples=True)
        self.assertTrue(report["all_expectations_met"], json.dumps(report, indent=2))

    def test_malformed_export_is_rejected_in_fresh_checker(self):
        image = AcceptanceImage.load(ROOT / "runs/exercise04/image.json")
        runner = AcceptanceRunner(image, root=ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input"
            path.mkdir(mode=0o755)
            (path / "solution.ndjson").write_text('{"status":"VERIFIED"}')
            (path / "solution.ndjson").chmod(0o644)
            run = runner._invoke_container(path, "lva-ex04-" + "c" * 32, ("verify",))
        packet = runner._packet(run, "verify")
        self.assertEqual(packet["status"], "SUBMISSION_REJECTED")
        self.assertIsNone(run.cleanup_error)


if __name__ == "__main__":
    unittest.main()
