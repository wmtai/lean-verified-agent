"""Offline checker tests and opt-in checks of the reviewed Lean fixtures."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_environment import (
    DEFAULT_ROOT, FIXTURE_DIRECTORY, FIXTURES, SPECIFICATION, check_environment, main,
)


PYTHON_VERSION = "3.12.15"
LEAN_VERSION = "4.34.1"


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def successful_observations():
    return [
        completed("Lake version 5.0.0-src+test (Lean version 4.34.1)\n"),
        completed("Lean (version 4.34.1, x86_64-unknown-linux-gnu, commit test)\n"),
        completed(),
        completed("none\nsome 5\n"),
        completed("some 0\n"),
        completed("WrongProof.lean:8:0: error: unsolved goals\n⊢ some 0 = none\n", 1),
    ]


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        files = {
            "configs/environment.json": json.dumps({
                "python_version": PYTHON_VERSION, "lean_version": LEAN_VERSION,
                "fixture_timeout_seconds": 30,
            }),
            ".python-version": PYTHON_VERSION + "\n",
            "pyproject.toml": '[project]\nname = "exercise-one"\nversion = "0.1.0"\n',
            "uv.lock": "version = 1\n",
            "lean/lean-toolchain": "leanprover/lean4:v4.34.1\n",
            "lean/lakefile.toml": 'name = "exercise"\n',
            "lean/lake-manifest.json": '{"packages": []}\n',
            str(SPECIFICATION): "namespace TaskSpec\nend TaskSpec\n",
            "tasks/development/checked_subtraction/task.json": '{"id":"checked_subtraction"}\n',
        }
        files.update({str(FIXTURE_DIRECTORY / name): "-- reviewed fixture\n" for name, _ in FIXTURES})
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def run_check(self, observations=None, python_version=PYTHON_VERSION, lake="/tools/lake"):
        with patch("scripts.check_environment._python_version", return_value=python_version), \
                patch("scripts.check_environment.shutil.which", return_value=lake), \
                patch("scripts.check_environment.subprocess.run", side_effect=(
                    successful_observations() if observations is None else observations
                )) as execute:
            return check_environment(self.root), execute

    def test_reproduces_all_three_distinct_observations_and_records_provenance(self):
        report, execute = self.run_check()
        self.assertTrue(report["exercise1_checks_passed"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["versions"], {
            "python": PYTHON_VERSION, "lean": LEAN_VERSION, "lake": "5.0.0-src+test",
        })
        self.assertEqual([row["observed"]["returncode"] for row in report["fixtures"]], [0, 0, 1])
        self.assertTrue(all(row["expected_observation_met"] for row in report["fixtures"]))
        self.assertEqual(len(report["snapshot_sha256"][str(SPECIFICATION)]), 64)
        self.assertIn("configs/environment.json", report["snapshot_sha256"])
        source_commands = [call.args[0] for call in execute.call_args_list[3:]]
        self.assertEqual(source_commands, [
            ["/tools/lake", "env", "lean", str(self.root / FIXTURE_DIRECTORY / name)]
            for name, _ in FIXTURES
        ])
        for call in execute.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.root / "lean")
            self.assertEqual(call.kwargs["timeout"], 30)
            self.assertEqual(call.kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("VERIFIED", json.dumps(report))

    def test_wrong_python_stops_before_tool_execution(self):
        report, execute = self.run_check(python_version="3.11.9")
        self.assertFalse(report["exercise1_checks_passed"])
        self.assertIn("Python 3.12.15 is required; running 3.11.9", report["errors"][0])
        execute.assert_not_called()

    def test_python_and_lean_pins_must_match_recorded_configuration(self):
        for relative, wrong_pin in ((".python-version", "3.11.9"), ("lean/lean-toolchain", "leanprover/lean4:v4.30.0")):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_text()
                path.write_text(wrong_pin)
                report, execute = self.run_check()
                self.assertFalse(report["exercise1_checks_passed"])
                self.assertIn("differs", report["errors"][0])
                execute.assert_not_called()
                path.write_text(original)

    def test_wrong_lean_stops_before_building_or_checking_fixtures(self):
        observations = successful_observations()
        observations[1] = completed("Lean (version 4.30.0, test)\n")
        report, execute = self.run_check(observations)
        self.assertFalse(report["exercise1_checks_passed"])
        self.assertIn("Lean 4.34.1 is required; running 4.30.0", report["errors"][0])
        self.assertEqual(execute.call_count, 2)

    def test_missing_lake_is_actionable(self):
        report, execute = self.run_check(lake=None)
        self.assertFalse(report["exercise1_checks_passed"])
        self.assertIn("Use --lake PATH or LAKE_BINARY", report["errors"][0])
        execute.assert_not_called()

    def test_lake_shim_symlink_preserves_its_dispatch_name(self):
        tool_directory = self.root / "tool-shims"
        tool_directory.mkdir()
        elan = tool_directory / "elan"
        elan.write_text("#!/bin/sh\nexit 0\n")
        elan.chmod(0o755)
        lake = tool_directory / "lake"
        lake.symlink_to(elan)
        report, execute = self.run_check(lake=str(lake))
        self.assertTrue(report["exercise1_checks_passed"])
        self.assertEqual(report["lake_binary"], str(lake))
        self.assertTrue(all(call.args[0][0] == str(lake) for call in execute.call_args_list))

    def test_failed_build_preserves_diagnostics_and_does_not_check_fixtures(self):
        observations = successful_observations()
        observations[2] = completed(returncode=1, stderr="error: trusted specification failed to build")
        report, execute = self.run_check(observations)
        self.assertFalse(report["exercise1_checks_passed"])
        self.assertIn("Trusted Lean project build failed with exit 1", report["errors"][0])
        self.assertIn("trusted specification", report["commands"][-1]["stderr"])
        self.assertEqual(report["fixtures"], [])
        self.assertEqual(execute.call_count, 3)

    def test_timeout_is_a_failed_check_even_for_the_expected_failing_proof(self):
        observations = successful_observations()
        observations[-1] = subprocess.TimeoutExpired(["lake"], 30, output=b"partial output", stderr=b"partial diagnostic")
        report, _ = self.run_check(observations)
        self.assertFalse(report["exercise1_checks_passed"])
        self.assertIn("WrongProof.lean timed out after 30 seconds", report["errors"][0])
        record = report["commands"][-1]
        self.assertTrue(record["timed_out"])
        self.assertIsNone(record["returncode"])
        self.assertEqual(record["stdout"], "partial output")

    def test_a_crash_or_unrelated_error_does_not_count_as_the_expected_proof_failure(self):
        for observation in (completed("unsolved goals", -9), completed("error: unknown identifier", 1), completed("unsolved goals", 0)):
            with self.subTest(returncode=observation.returncode, output=observation.stdout):
                observations = successful_observations()
                observations[-1] = observation
                report, _ = self.run_check(observations)
                self.assertFalse(report["exercise1_checks_passed"])
                self.assertFalse(report["fixtures"][-1]["expected_observation_met"])

    def test_wrong_execution_output_fails_even_when_all_commands_return_expected_exit_codes(self):
        observations = successful_observations()
        observations[3] = completed("some 0\nsome 5\n")
        report, _ = self.run_check(observations)
        self.assertFalse(report["exercise1_checks_passed"])
        self.assertIn("Correct.lean", report["errors"][0])

    def test_missing_or_symlinked_fixture_is_rejected_before_tool_execution(self):
        path = self.root / FIXTURE_DIRECTORY / "Correct.lean"
        path.unlink()
        report, execute = self.run_check()
        self.assertFalse(report["exercise1_checks_passed"])
        execute.assert_not_called()
        path.symlink_to(self.root / SPECIFICATION)
        report, execute = self.run_check()
        self.assertFalse(report["exercise1_checks_passed"])
        execute.assert_not_called()

    def test_malformed_configuration_is_reported_without_tracebacks(self):
        path = self.root / "configs/environment.json"
        for config in ([], {"python_version": PYTHON_VERSION, "lean_version": LEAN_VERSION, "fixture_timeout_seconds": True}):
            with self.subTest(config=config):
                path.write_text(json.dumps(config))
                report, execute = self.run_check()
                self.assertFalse(report["exercise1_checks_passed"])
                self.assertTrue(report["errors"])
                execute.assert_not_called()

    def test_cli_writes_a_failure_report_and_returns_nonzero(self):
        stdout, stderr = StringIO(), StringIO()
        with patch("scripts.check_environment._python_version", return_value="3.11.9"), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--root", str(self.root)])
        self.assertEqual(exit_code, 1)
        saved = json.loads((self.root / "runs/exercise01/environment.json").read_text())
        self.assertFalse(saved["exercise1_checks_passed"])
        self.assertIn("Python 3.12.15 is required", stderr.getvalue())

    def test_explicit_lake_overrides_environment_and_custom_report_is_saved(self):
        destination = self.root / "custom/report.json"
        with patch("scripts.check_environment._python_version", return_value=PYTHON_VERSION), \
                patch.dict(os.environ, {"LAKE_BINARY": "/ignored/lake"}), \
                patch("scripts.check_environment.shutil.which", return_value="/chosen/lake") as locate, \
                patch("scripts.check_environment.subprocess.run", side_effect=successful_observations()), \
                redirect_stdout(StringIO()):
            exit_code = main(["--root", str(self.root), "--lake", "/chosen/lake", "--report", str(destination)])
        self.assertEqual(exit_code, 0)
        locate.assert_called_once_with("/chosen/lake")
        self.assertTrue(json.loads(destination.read_text())["exercise1_checks_passed"])


@unittest.skipUnless(os.environ.get("RUN_LEAN_INTEGRATION") == "1", "set RUN_LEAN_INTEGRATION=1 for reviewed local Lean checks")
class ReviewedLeanIntegrationTests(unittest.TestCase):
    def test_pinned_environment_and_reviewed_fixtures(self):
        report = check_environment(DEFAULT_ROOT)
        self.assertTrue(report["exercise1_checks_passed"], json.dumps(report, indent=2))
        self.assertEqual(len(report["fixtures"]), 3)
        self.assertTrue(all(row["expected_observation_met"] for row in report["fixtures"]))


if __name__ == "__main__":
    unittest.main()
