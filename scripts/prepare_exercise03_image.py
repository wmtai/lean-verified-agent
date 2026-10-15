"""Build a worker from an installed toolchain and an explicit trusted allowlist.

Supplied Exercise 3 setup, not a learner hole. No candidate is executed here.
Run with --toolchain pointing to the directory containing bin/lean and bin/lake.
The build may download the Ubuntu base image. Candidate checks use --pull never.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from agent.sandbox import EXPECTED_LEAN_VERSION, IMAGE_ID, validate_daemon_info
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_FILES = (
    "lean-toolchain", "lakefile.toml", "lake-manifest.json",
    "tasks/development/checked_subtraction/Specification.lean",
)
DOCKERFILE = "exercises/03-sandboxed-runner/worker/Dockerfile"


def prepare_context(root: Path, toolchain: Path, destination: Path) -> dict[str, str]:
    """Stage only reviewed inputs; reject toolchain links escaping its root."""
    toolchain = toolchain.resolve(strict=True)
    destination.mkdir(parents=True, exist_ok=False)
    for name in ("bin", "lib", "include", "share"):
        directory = toolchain / name
        if name in ("include", "share") and not directory.exists():
            continue
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"Toolchain requires a regular {name} directory")
        for path in directory.rglob("*"):
            if path.is_symlink():
                if not path.resolve().is_relative_to(toolchain) or Path(os.readlink(path)).is_absolute():
                    raise ValueError(f"Toolchain link must stay relative and inside its directory: {path}")
        shutil.copytree(directory, destination / "toolchain" / name, symlinks=True)
    hashes = {}
    for relative in TRUSTED_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Missing or nonlocal trusted build input: {relative}")
        target = destination / "trusted" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    shutil.copyfile(root / DOCKERFILE, destination / "Dockerfile")
    hashes[DOCKERFILE] = hashlib.sha256((destination / "Dockerfile").read_bytes()).hexdigest()
    return hashes


def invoke(command: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=timeout, check=False)
    if completed.returncode:
        raise ValueError(f"Command failed ({completed.returncode}): {' '.join(command)}\n"
                         f"{completed.stdout}\n{completed.stderr}")
    return completed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True,
                        help="Installed Linux Lean directory containing bin/lean")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--report", type=Path, default=ROOT / "runs/exercise03/image.json")
    args = parser.parse_args(argv)
    try:
        task = Task.load(ROOT, "checked_subtraction")
        toolchain = args.toolchain.expanduser().resolve(strict=True)
        version_output = invoke([str(toolchain / "bin/lean"), "--version"]).stdout
        match = re.search(r"\bversion\s+(\d+\.\d+\.\d+)", version_output)
        if not match or match.group(1) != EXPECTED_LEAN_VERSION:
            raise ValueError(f"Expected Lean {EXPECTED_LEAN_VERSION}; observed {version_output.strip()}")
        daemon = json.loads(invoke([args.docker, "info", "--format", "{{json .}}"]).stdout)
        validate_daemon_info(daemon)
        # Bind mounts require a local daemon. Docker context is a host setting,
        # and is not passed into the worker's environment.
        if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
            endpoint = os.environ["DOCKER_HOST"]
        else:
            endpoint = json.loads(invoke([
                args.docker, "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}",
            ]).stdout)
        if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
            raise ValueError("Exercise 3 requires a local Docker daemon with a Unix socket")
        with tempfile.TemporaryDirectory(prefix="lva-ex03-build-") as temporary:
            context = Path(temporary) / "context"
            print("Staging the local toolchain and four trusted files...", flush=True)
            hashes = prepare_context(ROOT, toolchain, context)
            staged_spec = context / "trusted/tasks/development/checked_subtraction/Specification.lean"
            if staged_spec.read_text(encoding="utf-8") != task.specification_source:
                raise ValueError("Trusted specification changed during image preparation; retry the build")
            image_id_file = Path(temporary) / "image-id"
            print("Building the isolated worker image (this can take several minutes)...", flush=True)
            build = invoke([args.docker, "build", "--network=none", "--iidfile", str(image_id_file),
                            "--file", str(context / "Dockerfile"), str(context)], timeout=1200)
            image_id = image_id_file.read_text().strip()
            if not IMAGE_ID.fullmatch(image_id):
                raise ValueError("Docker did not return a full image ID")
            image_metadata = json.loads(invoke([
                args.docker, "image", "inspect", image_id,
                "--format", "{{json .}}",
            ]).stdout)
        report = {
            "schema_version": 1, "built_at": datetime.now(timezone.utc).isoformat(),
            "image_id": image_id, "task_digest": task.digest,
            "lean_version": EXPECTED_LEAN_VERSION, "host_lean_version_output": version_output.strip(),
            "lean_binary_sha256": hashlib.sha256((toolchain / "bin/lean").read_bytes()).hexdigest(),
            "trusted_file_sha256": hashes, "docker_version": daemon.get("ServerVersion"),
            "architecture": image_metadata.get("Architecture"), "os": image_metadata.get("Os"),
            "image_build_log": build.stdout + build.stderr,
            "scope": "Trusted image setup; runner must measure the compiler inside this image before each check",
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary_report = args.report.with_name(args.report.name + ".tmp")
        temporary_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_report, args.report)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Worker image setup failed: {error}", file=sys.stderr)
        return 1
    print(f"Worker image: {image_id}")
    print(f"Image report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
