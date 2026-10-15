"""Reproduce Exercise 1 observations using only its reviewed local fixtures.

This command is an environment check, not a sandbox or a final acceptance gate.
It accepts no model output or arbitrary Lean source-file argument.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION = Path("tasks/development/checked_subtraction/Specification.lean")
FIXTURE_DIRECTORY = Path("exercises/01-environment/fixtures")
FIXTURES = (
    ("Correct.lean", {"exit": "zero", "stdout_lines": ["none", "some 5"]}),
    ("WrongImplementation.lean", {"exit": "zero", "stdout_lines": ["some 0"]}),
    ("WrongProof.lean", {"exit": "nonzero", "diagnostic_contains": "unsolved goals"}),
)
SNAPSHOT_FILES = (
    Path("configs/environment.json"), Path(".python-version"), Path("pyproject.toml"),
    Path("uv.lock"), Path("lean-toolchain"), Path("lakefile.toml"),
    Path("lake-manifest.json"),
    SPECIFICATION, Path("tasks/development/checked_subtraction/task.json"),
)


class EnvironmentCheckError(RuntimeError):
    """An expected environment or command failure with an actionable message."""


def _python_version() -> str:
    return ".".join(str(part) for part in sys.version_info[:3])


def _read_config(root: Path) -> dict:
    path = root / "configs/environment.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EnvironmentCheckError("configs/environment.json must contain an object")
    for key in ("python_version", "lean_version"):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise EnvironmentCheckError(f"{key} must be an exact three-part version")
    timeout = data.get("fixture_timeout_seconds")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise EnvironmentCheckError("fixture_timeout_seconds must be positive and finite")
    return data


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _invoke(command: list[str], root: Path, timeout: float, report: dict,
            description: str) -> dict:
    started = time.monotonic()
    record = {"description": description, "command": command, "cwd": str(root),
              "timeout_seconds": timeout, "timed_out": False}
    report["commands"].append(record)
    try:
        process = subprocess.run(
            command, cwd=root, timeout=timeout, check=False,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        record.update({"returncode": None, "stdout": _text(exc.stdout),
                       "stderr": _text(exc.stderr), "timed_out": True,
                       "elapsed_seconds": time.monotonic() - started})
        raise EnvironmentCheckError(f"{description} timed out after {timeout:g} seconds") from None
    except OSError as exc:
        record.update({"returncode": None, "stdout": "", "stderr": str(exc),
                       "elapsed_seconds": time.monotonic() - started})
        raise EnvironmentCheckError(f"Cannot execute {description}: {exc}") from None
    record.update({"returncode": process.returncode, "stdout": process.stdout,
                   "stderr": process.stderr,
                   "elapsed_seconds": time.monotonic() - started})
    return record


def _require_success(record: dict) -> None:
    if record["returncode"] != 0:
        raise EnvironmentCheckError(
            f"{record['description']} failed with exit {record['returncode']}; "
            "see the recorded command diagnostics"
        )


def _lean_version(output: str) -> str:
    match = re.search(r"\bLean\s+\(?version\s+(\d+\.\d+\.\d+)(?=[,\s)])", output)
    if not match:
        raise EnvironmentCheckError("Cannot identify the Lean version from its version output")
    return match.group(1)


def _matches_expectation(record: dict, expected: dict) -> bool:
    if expected["exit"] == "zero":
        lines = [line.strip() for line in record["stdout"].splitlines() if line.strip()]
        return record["returncode"] == 0 and lines == expected["stdout_lines"]
    diagnostics = record["stdout"] + "\n" + record["stderr"]
    return record["returncode"] > 0 and expected["diagnostic_contains"] in diagnostics.lower()


def check_environment(root: Path = DEFAULT_ROOT, lake: str | None = None) -> dict:
    """Return a report even when a version, fixture, or expected command fails."""
    root = root.resolve()
    report = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Exercise 1: manually reviewed local fixtures; no sandbox or final acceptance gate",
        "repository_root": str(root),
        "configuration": None,
        "versions": {"python": _python_version(), "lean": None, "lake": None},
        "snapshot_sha256": {},
        "commands": [], "fixtures": [], "errors": [],
        "exercise1_checks_passed": False,
    }
    try:
        config = _read_config(root)
        report["configuration"] = config
        for relative in SNAPSHOT_FILES:
            path = root / relative
            if not path.is_file():
                raise EnvironmentCheckError(f"Missing reproducibility input: {relative}")
            report["snapshot_sha256"][str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
        python_pin = (root / ".python-version").read_text(encoding="utf-8").strip()
        lean_pin = (root / "lean-toolchain").read_text(encoding="utf-8").strip()
        if python_pin != config["python_version"]:
            raise EnvironmentCheckError(".python-version differs from configs/environment.json")
        if lean_pin != "leanprover/lean4:v" + config["lean_version"]:
            raise EnvironmentCheckError("lean-toolchain differs from configs/environment.json")
        if report["versions"]["python"] != config["python_version"]:
            raise EnvironmentCheckError(
                f"Python {config['python_version']} is required; "
                f"running {report['versions']['python']}. Use the pinned .venv interpreter."
            )
        for name, _ in FIXTURES:
            path = root / FIXTURE_DIRECTORY / name
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                raise EnvironmentCheckError(f"Missing or nonlocal reviewed fixture: {path}")
            report["snapshot_sha256"][str(FIXTURE_DIRECTORY / name)] = hashlib.sha256(path.read_bytes()).hexdigest()
        requested_lake = lake or os.environ.get("LAKE_BINARY") or "lake"
        lake_binary = shutil.which(str(Path(requested_lake).expanduser()))
        if lake_binary is None:
            raise EnvironmentCheckError(f"Lake executable is unavailable: {requested_lake}. Use --lake PATH or LAKE_BINARY.")
        # Elan dispatches by the executable name. Resolving its `lake` symlink
        # to `elan` would change argv[0] and invoke the wrong command.
        lake_binary = str(Path(lake_binary).absolute())
        report["lake_binary"] = lake_binary
        cwd = root
        timeout = config["fixture_timeout_seconds"]
        lake_version = _invoke([lake_binary, "--version"], cwd, timeout, report, "Lake version check")
        _require_success(lake_version)
        lake_output = (lake_version["stdout"] + "\n" + lake_version["stderr"]).strip()
        match = re.search(r"\bLake version\s+(\S+)", lake_output)
        if not match:
            raise EnvironmentCheckError("Cannot identify the Lake version from its version output")
        report["versions"]["lake"] = match.group(1)
        if "Lean version" in lake_output and _lean_version(lake_output) != config["lean_version"]:
            raise EnvironmentCheckError(f"Lake was built for a different Lean version: {lake_output}")
        lean_version = _invoke([lake_binary, "env", "lean", "--version"], cwd, timeout, report, "Lean version check")
        _require_success(lean_version)
        report["versions"]["lean"] = _lean_version(lean_version["stdout"] + "\n" + lean_version["stderr"])
        if report["versions"]["lean"] != config["lean_version"]:
            raise EnvironmentCheckError(f"Lean {config['lean_version']} is required; running {report['versions']['lean']}")
        build = _invoke([lake_binary, "build"], cwd, timeout, report, "Trusted Lean project build")
        _require_success(build)
        for name, expected in FIXTURES:
            path = root / FIXTURE_DIRECTORY / name
            record = _invoke([lake_binary, "env", "lean", str(path)], cwd, timeout, report, name)
            passed = _matches_expectation(record, expected)
            report["fixtures"].append({"path": str(FIXTURE_DIRECTORY / name),
                                       "expected_observation": expected,
                                       "observed": record,
                                       "expected_observation_met": passed})
            if not passed:
                report["errors"].append(f"{name} did not produce its expected Exercise 1 observation")
        report["exercise1_checks_passed"] = not report["errors"]
    except (EnvironmentCheckError, OSError, ValueError) as exc:
        report["errors"].append(str(exc))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Exercise repository root")
    parser.add_argument("--lake", help="Reviewed toolchain's Lake executable; otherwise LAKE_BINARY or PATH")
    parser.add_argument("--report", type=Path, help="Report path; default: ROOT/runs/exercise01/environment.json")
    args = parser.parse_args(argv)
    report = check_environment(args.root, args.lake)
    destination = args.report or args.root / "runs/exercise01/environment.json"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    except (OSError, ValueError) as exc:
        print(f"Cannot save environment report: {exc}", file=sys.stderr)
        return 1
    print(f"Report: {destination}")
    if report["exercise1_checks_passed"]:
        print("Exercise 1 environment checks passed for the three reviewed local fixtures.")
        return 0
    for error in report["errors"]:
        print(f"Environment check failed: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
