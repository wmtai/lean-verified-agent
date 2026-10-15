"""Build pinned Comparator/exporter support and a fresh-check worker image.

Only trusted upstream/setup code is built on the host. Candidate Lean is
compiled/exported in a restricted container and only serialized data reaches
the separate verifier. No Landrun fallback or host candidate execution is used.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from agent.acceptance import TRUSTED_INPUTS, policy_digest
from agent.sandbox import EXPECTED_LEAN_VERSION, IMAGE_ID, WorkerImage, validate_daemon_info
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]


def invoke(arguments, *, cwd=ROOT, timeout=60):
    result = subprocess.run(arguments, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError(f"Command failed: {' '.join(map(str, arguments))}\n{result.stdout[:6000]}\n{result.stderr[:6000]}")
    return result.stdout


def stage_driver(source: Path, root: Path, lock: dict) -> None:
    """Retain upstream comparison/replay unchanged, replace its CLI frontend."""
    main = (source / "Main.lean").read_bytes()
    if hashlib.sha256(main).hexdigest() != lock["comparator_main_sha256"]:
        raise ValueError("Pinned Comparator Main.lean checksum mismatch")
    driver, separator, _ = main.decode().partition("\ndef main (args : List String)")
    if not separator:
        raise ValueError("Cannot locate the pinned upstream CLI boundary")
    (source / "ComparatorDriver.lean").write_text(driver + "\n")
    shutil.copyfile(root / "verification/VerifyExports.lean", source / "VerifyExports.lean")
    with (source / "lakefile.toml").open("a") as handle:
        handle.write('\n[[lean_lib]]\nname = "ComparatorDriver"\n\n'
                     '[[lean_exe]]\nname = "verify_exports"\nroot = "VerifyExports"\n')
    # Pin the actual project compiler rather than relying on the upstream
    # minor-version toolchain name. Build/version checks record compatibility.
    (source / "lean-toolchain").write_text(f"leanprover/lean4:v{EXPECTED_LEAN_VERSION}\n")


def stage_python(destination: Path) -> None:
    """Copy the managed interpreter/stdlib, excluding user/site packages."""
    prefix = Path(sys.base_prefix)
    (destination / "bin").mkdir(parents=True)
    shutil.copyfile(prefix / "bin/python3.12", destination / "bin/python3.12")
    (destination / "bin/python3.12").chmod(0o755)
    shutil.copytree(prefix / "lib/python3.12", destination / "lib/python3.12",
                    ignore=shutil.ignore_patterns("site-packages", "__pycache__"))
    for path in (prefix / "lib").glob("libpython*.so*"):
        shutil.copyfile(path, destination / "lib" / path.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake", default=os.environ.get("LAKE_BINARY") or str(Path.home() / ".elan/bin/lake"))
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--base-image-report", type=Path, default=ROOT / "runs/exercise03/image.json")
    parser.add_argument("--report", type=Path, default=ROOT / "runs/exercise04/image.json")
    args = parser.parse_args(argv)
    try:
        lock = json.loads((ROOT / "verification/comparator-lock.json").read_text())
        task = Task.load(ROOT, "checked_subtraction")
        base_image = WorkerImage.load(args.base_image_report)
        if base_image.task_digest != task.digest:
            raise ValueError("Rebuild the Exercise 3 trusted image for the current task first")
        if tuple(sys.version_info[:3]) != (3, 12, 15):
            raise ValueError("Run setup with the pinned .venv/bin/python")
        daemon = json.loads(invoke([args.docker, "info", "--format", "{{json .}}"] ))
        validate_daemon_info(daemon)
        endpoint = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
        endpoint = endpoint or json.loads(invoke([args.docker, "context", "inspect", "--format",
                                                "{{json .Endpoints.docker.Host}}"] ))
        if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
            raise ValueError("A local Docker daemon is required")
        version = invoke([args.lake, "env", "lean", "--version"])
        if f"version {EXPECTED_LEAN_VERSION}," not in version:
            raise ValueError(f"Wrong build compiler: {version}")
        original_policy_digest = policy_digest(ROOT)
        base_tag = "lva-ex04-base:" + base_image.image_id.removeprefix("sha256:")
        invoke([args.docker, "image", "tag", base_image.image_id, base_tag])
        if invoke([args.docker, "image", "inspect", base_tag, "--format", "{{.Id}}"] ).strip() != base_image.image_id:
            raise ValueError("Local base-image tag does not resolve to its pinned image ID")
        with tempfile.TemporaryDirectory(prefix="lva-ex04-build-") as temporary:
            directory = Path(temporary)
            source = directory / "comparator"
            print("Fetching pinned Comparator sources...", flush=True)
            invoke(["git", "clone", "--quiet", lock["comparator_repository"], str(source)])
            invoke(["git", "checkout", "--quiet", lock["comparator_revision"]], cwd=source)
            if invoke(["git", "rev-parse", "HEAD"], cwd=source).strip() != lock["comparator_revision"]:
                raise ValueError("Comparator revision mismatch")
            stage_driver(source, ROOT, lock)
            print("Building Comparator's exporter and fresh-data checker with Lean 4.34.1...", flush=True)
            build_log = invoke([args.lake, "build", "lean4export", "verify_exports"], cwd=source, timeout=1200)
            dependency = source / ".lake/packages/lean4export"
            if invoke(["git", "rev-parse", "HEAD"], cwd=dependency).strip() != lock["exporter_revision"]:
                raise ValueError("Exporter revision mismatch")
            context = directory / "context"
            tools = context / "tools"
            tools.mkdir(parents=True)
            for origin, name in ((source / ".lake/build/bin/verify_exports", "verify_exports"),
                                 (dependency / ".lake/build/bin/lean4export", "lean4export"),
                                 (ROOT / "verification/worker.py", "worker.py"),
                                 (ROOT / "verification/Smoke.lean", "Smoke.lean"),
                                 (source / "LICENSE", "Comparator-LICENSE")):
                shutil.copyfile(origin, tools / name)
            (tools / "verify_exports").chmod(0o755)
            (tools / "lean4export").chmod(0o755)
            trusted = context / "trusted"
            trusted.mkdir()
            shutil.copyfile(ROOT / "verification/Challenge.lean", trusted / "Challenge.lean")
            shutil.copyfile(ROOT / "verification/comparator-lock.json", trusted / "comparator-lock.json")
            stage_python(context / "python")
            shutil.copyfile(ROOT / "verification/Dockerfile", context / "Dockerfile")
            if policy_digest(ROOT) != original_policy_digest or Task.load(ROOT, task.id).digest != task.digest:
                raise ValueError("Trusted inputs changed during setup; retry")
            image_file = directory / "image-id"
            print("Building the isolated acceptance image...", flush=True)
            image_log = invoke([args.docker, "build", "--pull=false", "--network=none", "--build-arg",
                                f"BASE_IMAGE={base_tag}", "--iidfile", str(image_file), str(context)], timeout=1200)
            image_id = image_file.read_text().strip()
            if not IMAGE_ID.fullmatch(image_id):
                raise ValueError("Invalid built acceptance image ID")
            tool_hashes = {name: hashlib.sha256((tools / name).read_bytes()).hexdigest()
                           for name in ("verify_exports", "lean4export")}
        report = {
            "schema_version": 1, "built_at": datetime.now(timezone.utc).isoformat(),
            "image_id": image_id, "task_digest": task.digest, "policy_digest": original_policy_digest,
            "lean_version": EXPECTED_LEAN_VERSION, "build_compiler": version.strip(),
            "source_pins": lock, "tool_binary_sha256": tool_hashes,
            "trusted_file_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in TRUSTED_INPUTS},
            "build_log": build_log + image_log,
            "isolation": "Separate Docker workers for untrusted compilation/export and fresh Comparator replay",
            "external_kernels": [],
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Acceptance setup failed: {error}", file=sys.stderr)
        return 1
    print(f"Acceptance image: {image_id}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
