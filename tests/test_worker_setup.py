"""Checks of supplied Exercise 3 setup; no learner runner holes are called."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from agent.sandbox import ContainerState, RunnerLimits, WorkerImage, validate_daemon_info
from scripts.prepare_exercise03_image import DOCKERFILE, TRUSTED_FILES, prepare_context


class WorkerSetupTests(unittest.TestCase):
    def test_limits_reject_nonfinite_boolean_and_nonpositive_values(self):
        RunnerLimits().validate()
        for changes in ({"wall_seconds": float("nan")}, {"wall_seconds": True},
                        {"cpus": 0}, {"memory_mb": 5}, {"pids": False}, {"output_bytes": -1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(RunnerLimits(), **changes).validate()

    def test_worker_report_requires_an_immutable_image_and_pinned_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "image.json"
            data = {"image_id": "sha256:" + "a" * 64, "task_digest": "b" * 64, "lean_version": "4.34.1"}
            report.write_text(json.dumps(data))
            self.assertEqual(WorkerImage.load(report).image_id, data["image_id"])
            for changes in ({"image_id": "image:latest"}, {"lean_version": "4.30.0"}, {"task_digest": ""}):
                report.write_text(json.dumps(dict(data, **changes)))
                with self.assertRaises(ValueError):
                    WorkerImage.load(report)

    def test_daemon_must_enforce_linux_resource_limits(self):
        info = {"OSType": "linux", "MemoryLimit": True, "SwapLimit": True,
                "CpuCfsQuota": True, "PidsLimit": True, "Warnings": None}
        validate_daemon_info(info)
        for changes in ({"OSType": "windows"}, {"MemoryLimit": False},
                        {"PidsLimit": False}, {"Warnings": ["limit unavailable"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_daemon_info(dict(info, **changes))

    def test_state_json_rejects_missing_fields_and_wrong_types(self):
        valid = {"Status": "exited", "ExitCode": 0, "OOMKilled": False, "Error": ""}
        self.assertEqual(ContainerState.from_json(json.dumps(valid).encode()).exit_code, 0)
        for payload in (b"null", b"{", json.dumps(dict(valid, ExitCode=True)).encode()):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ContainerState.from_json(payload)

    def test_image_context_contains_only_allowlisted_project_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, toolchain = base / "repo", base / "lean"
            for relative in (*TRUSTED_FILES, DOCKERFILE, ".env", "reference/secret.lean"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative)
            for name in ("bin", "lib"):
                (toolchain / name).mkdir(parents=True)
                (toolchain / name / "sample").write_text("fake installed toolchain")
            context = base / "context"
            hashes = prepare_context(root, toolchain, context)
            actual = {str(path.relative_to(context / "trusted"))
                      for path in (context / "trusted").rglob("*") if path.is_file()}
            self.assertEqual(actual, set(TRUSTED_FILES))
            self.assertEqual(set(hashes), {*TRUSTED_FILES, DOCKERFILE})
            (toolchain / "bin" / "escape").symlink_to(root / ".env")
            with self.assertRaises(ValueError):
                prepare_context(root, toolchain, base / "bad-context")


if __name__ == "__main__":
    unittest.main()
