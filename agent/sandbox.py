"""Supplied infrastructure for bounded checks in an isolated Docker Lean worker.

Learner exercises use DockerLeanRunner.check and inspect its retained evidence;
process management and container policy are maintained here as infrastructure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import hashlib
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time
import uuid

from agent.task import Task


EXPECTED_LEAN_VERSION = "4.34.1"
MAX_SOURCE_BYTES = 131072
CONTROL_TIMEOUT_SECONDS = 10.0
CONTROL_OUTPUT_BYTES = 65536
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
CONTAINER_NAME = re.compile(r"lva-ex03-[a-f0-9]{32}")


class Outcome(StrEnum):
    ELABORATED = "ELABORATED"
    ELABORATION_FAILED = "ELABORATION_FAILED"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


@dataclass(frozen=True)
class RunnerLimits:
    wall_seconds: float = 20.0
    memory_mb: int = 512
    cpus: float = 1.0
    pids: int = 64
    output_bytes: int = 65536
    tmpfs_mb: int = 32

    def validate(self) -> None:
        for name in ("wall_seconds", "cpus"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be positive and finite")
        for name in ("memory_mb", "pids", "output_bytes", "tmpfs_mb"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.memory_mb < 6:
            raise ValueError("Docker requires memory_mb of at least 6")


@dataclass(frozen=True)
class WorkerImage:
    image_id: str
    task_digest: str
    lean_version: str

    def validate(self) -> None:
        if not isinstance(self.image_id, str) or not IMAGE_ID.fullmatch(self.image_id):
            raise ValueError("Use the full immutable sha256 image ID from the image report")
        if not isinstance(self.task_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", self.task_digest):
            raise ValueError("Worker image requires a task snapshot digest")
        if self.lean_version != EXPECTED_LEAN_VERSION:
            raise ValueError(f"Worker image must use Lean {EXPECTED_LEAN_VERSION}")

    @classmethod
    def load(cls, path: Path) -> WorkerImage:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Image report must be an object")
            image = cls(data["image_id"], data["task_digest"], data["lean_version"])
            image.validate()
            return image
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot load worker image report: {error}") from error


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int | None
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float
    timed_out: bool = False
    output_limit_exceeded: bool = False
    startup_error: str | None = None


@dataclass(frozen=True)
class ContainerState:
    status: str
    exit_code: int
    oom_killed: bool
    error: str

    @classmethod
    def from_json(cls, payload: bytes) -> ContainerState:
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Docker returned invalid container state JSON") from error
        if (not isinstance(data, dict) or not isinstance(data.get("Status"), str)
                or type(data.get("ExitCode")) is not int
                or type(data.get("OOMKilled")) is not bool
                or not isinstance(data.get("Error"), str)):
            raise ValueError("Docker returned incomplete container state")
        return cls(data["Status"], data["ExitCode"], data["OOMKilled"], data["Error"])


@dataclass(frozen=True)
class ContainerRun:
    process: ProcessResult
    state: ContainerState | None
    infrastructure_error: str | None = None
    cleanup_error: str | None = None
    control_results: tuple[ProcessResult, ...] = ()


@dataclass(frozen=True)
class LeanRunResult:
    status: Outcome
    returncode: int | None
    elapsed_seconds: float
    lean_version: str | None
    work_directory: Path
    stdout_path: Path
    stderr_path: Path
    report_path: Path


def validate_daemon_info(info: object) -> None:
    """Reject a daemon that cannot enforce this exercise's Linux limits."""
    if not isinstance(info, dict) or info.get("OSType") != "linux":
        raise ValueError("A local Linux Docker daemon is required")
    for feature in ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit"):
        if info.get(feature) is not True:
            raise ValueError(f"Docker cannot enforce {feature}; configure cgroup delegation")
    if info.get("Warnings"):
        raise ValueError("Resolve Docker daemon warnings before candidate execution")


def run_bounded(command: list[str] | tuple[str, ...], *, timeout_seconds: float,
                max_output_bytes: int) -> ProcessResult:
    """Run a reviewed host command with bounded combined stdout/stderr.

    Capture byte streams together, cap their combined size while reading, and
    terminate the command's process group on timeout, output overflow, or parent
    exit. A short final drain preserves available diagnostics without allowing
    inherited pipe descriptors to make cleanup wait indefinitely.

    This function alone is NOT a sandbox. Local tests use reviewed Python code;
    untrusted Lean must be submitted only through DockerLeanRunner.
    """
    if (
        not isinstance(command, (list, tuple))
        or not command
        or any(not isinstance(argument, str) or not argument
            for argument in command)
    ):
        raise ValueError("command must contain nonempty string arguments")

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be positive and finite")

    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be a positive integer")

    argv = tuple(command)
    started = time.monotonic()
    deadline = started + timeout_seconds
    try:
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, start_new_session=True,
        )
    except OSError as error:
        return ProcessResult(argv, None, b"", b"", time.monotonic() - started,
                             startup_error=str(error))

    stdout = bytearray()
    stderr = bytearray()
    timed_out = False
    output_limit_exceeded = False
    cleanup_deadline = None
    selector = selectors.DefaultSelector()

    def stop_group() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        for stream, buffer in ((process.stdout, stdout), (process.stderr, stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, buffer)

        while True:
            now = time.monotonic()
            if cleanup_deadline is None:
                if process.poll() is not None:
                    # A successful direct child may still have live children.
                    stop_group()
                    cleanup_deadline = now + 0.25
                elif now >= deadline:
                    timed_out = True
                    stop_group()
                    cleanup_deadline = now + 0.25

            if cleanup_deadline is not None:
                if not selector.get_map() or now >= cleanup_deadline:
                    break
                remaining = cleanup_deadline - now
            else:
                remaining = deadline - now

            for key, _events in selector.select(timeout=min(0.05, remaining)):
                available = max_output_bytes - len(stdout) - len(stderr)
                try:
                    # Read one byte beyond capacity to distinguish exact fit
                    # from overflow, without allocating an unbounded chunk.
                    chunk = os.read(key.fd, min(65536, available + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                key.data.extend(chunk[:available])
                if len(chunk) > available:
                    output_limit_exceeded = True
                    stop_group()
                    if cleanup_deadline is None:
                        cleanup_deadline = time.monotonic() + 0.25
    finally:
        # Also applies if reading/registering raises unexpectedly.
        stop_group()
        for stream in (process.stdout, process.stderr):
            stream.close()
        selector.close()
        process.wait()

    return ProcessResult(
        command=argv, returncode=process.returncode, stdout=bytes(stdout),
        stderr=bytes(stderr), elapsed_seconds=time.monotonic() - started,
        timed_out=timed_out, output_limit_exceeded=output_limit_exceeded,
    )


def docker_create_command(docker_binary: str, image: WorkerImage, input_directory: Path,
                          container_name: str, limits: RunnerLimits,
                          lean_arguments: tuple[str, ...]) -> list[str]:
    """Construct the fixed restricted Docker create argv without executing it."""
    image.validate()
    limits.validate()
    if not isinstance(docker_binary, str) or not docker_binary or "\0" in docker_binary:
        raise ValueError("Docker executable must be a nonempty path/name")
    if not isinstance(container_name, str) or not CONTAINER_NAME.fullmatch(container_name):
        raise ValueError("Container name must be a fresh lva-ex03 UUID name")
    if lean_arguments not in (("--version",), ("-j1", "/input/Candidate.lean")):
        raise ValueError("Only compiler version and candidate checking commands are allowed")
    directory = Path(input_directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Input must be a regular nonsymlink directory")
    directory = directory.resolve()
    if any(character in str(directory) for character in (",", "\n", "\r", "\0")):
        raise ValueError("Input mount path cannot contain commas or line breaks")
    candidate = directory / "Candidate.lean"
    if ({path.name for path in directory.iterdir()} != {"Candidate.lean"}
            or candidate.is_symlink() or not candidate.is_file()):
        raise ValueError("Input directory must contain only a regular Candidate.lean file")
    return [
        docker_binary, "create", "--name", container_name,
        "--label", "lean-verified-agent.exercise=03", "--pull", "never",
        "--network", "none", "--read-only", "--user", "1000:1000",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
        "--init", "--no-healthcheck", "--pids-limit", str(limits.pids),
        "--memory", f"{limits.memory_mb}m", "--memory-swap", f"{limits.memory_mb}m",
        "--cpus", str(limits.cpus), "--shm-size", "8m", "--ulimit", "nofile=128:128",
        "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_mb}m,mode=1777",
        "--mount", f"type=bind,source={directory},target=/input,readonly",
        "--log-driver", "none", "--restart", "no", "--workdir", "/trusted",
        "--entrypoint", "/opt/lean/bin/lean", "--env", "HOME=/tmp",
        "--env", "PATH=/opt/lean/bin:/usr/bin:/bin",
        "--env", "LEAN_PATH=/trusted/.lake/build/lib/lean", image.image_id, *lean_arguments,
    ]


def classify_result(run: ContainerRun) -> Outcome:
    """Classify process/container evidence without claiming final acceptance."""
    process = run.process
    if run.infrastructure_error or run.cleanup_error or process.startup_error:
        return Outcome.INFRASTRUCTURE_ERROR
    if process.timed_out:
        return Outcome.TIMEOUT
    if process.output_limit_exceeded:
        return Outcome.OUTPUT_LIMIT_EXCEEDED
    state = run.state
    if (state is None or state.status != "exited" or state.oom_killed or state.error
            or state.exit_code != process.returncode):
        return Outcome.INFRASTRUCTURE_ERROR
    if state.exit_code == 0:
        return Outcome.ELABORATED
    if state.exit_code == 1:
        return Outcome.ELABORATION_FAILED
    return Outcome.INFRASTRUCTURE_ERROR


def _process_error(process: ProcessResult, description: str) -> str | None:
    if process.startup_error:
        return f"{description}: {process.startup_error}"
    if process.timed_out:
        return f"{description} timed out"
    if process.output_limit_exceeded:
        return f"{description} exceeded its diagnostic limit"
    if process.returncode != 0:
        detail = (process.stderr + b"\n" + process.stdout).decode("utf-8", errors="replace").strip()
        return f"{description} exited {process.returncode}: {detail[:4096]}"
    return None


def _process_record(process: ProcessResult) -> dict:
    record = asdict(process)
    record["stdout"] = process.stdout.decode("utf-8", errors="replace")
    record["stderr"] = process.stderr.decode("utf-8", errors="replace")
    return record


class DockerLeanRunner:
    def __init__(self, image: WorkerImage, *, docker_binary: str = "docker",
                 limits: RunnerLimits = RunnerLimits()):
        image.validate()
        limits.validate()
        self.image = image
        self.docker_binary = docker_binary
        self.limits = limits

    def _create_command(self, input_directory: Path, container_name: str,
                        arguments: tuple[str, ...]) -> list[str]:
        return docker_create_command(self.docker_binary, self.image, input_directory,
                                     container_name, self.limits, arguments)

    def _invoke_container(self, input_directory: Path, container_name: str,
                          lean_arguments: tuple[str, ...]) -> ContainerRun:
        """Create, attach, inspect and always remove one named fresh container."""
        create = self._create_command(input_directory, container_name, lean_arguments)
        controls = []
        state = None
        infrastructure_error = cleanup_error = None
        process = ProcessResult(tuple(create), None, b"", b"", 0)

        def control(command: list[str]) -> ProcessResult:
            result = run_bounded(command, timeout_seconds=CONTROL_TIMEOUT_SECONDS,
                                 max_output_bytes=CONTROL_OUTPUT_BYTES)
            controls.append(result)
            return result

        try:
            process = control(create)
            infrastructure_error = _process_error(process, "Docker create")
            if infrastructure_error is None:
                process = run_bounded(
                    [self.docker_binary, "start", "--attach", container_name],
                    timeout_seconds=self.limits.wall_seconds,
                    max_output_bytes=self.limits.output_bytes,
                )
                if process.startup_error:
                    infrastructure_error = f"Docker attach: {process.startup_error}"
                elif not process.timed_out and not process.output_limit_exceeded:
                    inspected = control([self.docker_binary, "inspect", "--format",
                                         "{{json .State}}", container_name])
                    infrastructure_error = _process_error(inspected, "Docker inspect")
                    if infrastructure_error is None:
                        state = ContainerState.from_json(inspected.stdout)
        except (OSError, ValueError) as error:
            infrastructure_error = f"Docker worker failed: {error}"
        finally:
            # This also stops daemon-managed work after the attached CLI was
            # killed. On timeout/overflow it runs before any inspect command.
            try:
                removed = control([self.docker_binary, "rm", "--force", container_name])
                cleanup_error = _process_error(removed, "Docker cleanup")
                if (cleanup_error and removed.returncode == 1
                        and not removed.timed_out and not removed.output_limit_exceeded
                        and b"No such container" in removed.stderr):
                    cleanup_error = None
            except (OSError, ValueError) as error:
                cleanup_error = f"Docker cleanup failed: {error}"
        return ContainerRun(process, state, infrastructure_error, cleanup_error, tuple(controls))

    def check(self, task: Task, source: str, *, artifact_root: Path) -> LeanRunResult:
        """Measure the compiler, check raw source, and retain bounded evidence."""
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Candidate source must be a nonempty string")
        try:
            encoded = source.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("Candidate source must be valid UTF-8") from error
        if len(encoded) > MAX_SOURCE_BYTES:
            raise ValueError(f"Candidate source exceeds {MAX_SOURCE_BYTES} UTF-8 bytes")

        started = time.monotonic()
        artifact_root = Path(artifact_root).expanduser().resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
        work_directory = Path(tempfile.mkdtemp(prefix="attempt-", dir=artifact_root))
        work_directory.chmod(0o700)
        (work_directory / "Candidate.lean").write_bytes(encoded)
        stdout_path, stderr_path = work_directory / "stdout.log", work_directory / "stderr.log"
        report_path = work_directory / "result.json"
        controls = []
        container_names = []
        task_digest = task.digest
        measured_version = None
        version_run = candidate_run = None
        observed = ProcessResult((), None, b"", b"", 0)
        status = Outcome.INFRASTRUCTURE_ERROR
        infrastructure_error = cleanup_error = None

        def control(command: list[str]) -> ProcessResult:
            result = run_bounded(command, timeout_seconds=CONTROL_TIMEOUT_SECONDS,
                                 max_output_bytes=CONTROL_OUTPUT_BYTES)
            controls.append(result)
            error = _process_error(result, "Docker preflight")
            if error:
                raise ValueError(error)
            return result

        try:
            self.image.validate()
            self.limits.validate()
            if task_digest != self.image.task_digest:
                raise ValueError("Task snapshot differs from the trusted worker image; rebuild the image")
            if task.lean_toolchain != f"leanprover/lean4:v{EXPECTED_LEAN_VERSION}":
                raise ValueError("Task toolchain differs from the worker's required toolchain")
            daemon = control([self.docker_binary, "info", "--format", "{{json .}}"])
            validate_daemon_info(json.loads(daemon.stdout))
            if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
                endpoint = os.environ["DOCKER_HOST"]
            else:
                context = control([self.docker_binary, "context", "inspect", "--format",
                                   "{{json .Endpoints.docker.Host}}"])
                endpoint = json.loads(context.stdout)
            if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
                raise ValueError("A local Docker daemon with a Unix socket is required")

            with tempfile.TemporaryDirectory(prefix="lva-ex03-input-", dir="/tmp") as temporary:
                directory = Path(temporary)
                directory.chmod(0o755)
                candidate_path = directory / "Candidate.lean"
                candidate_path.write_bytes(encoded)
                candidate_path.chmod(0o644)
                container_names.append("lva-ex03-" + uuid.uuid4().hex)
                version_run = self._invoke_container(directory, container_names[-1], ("--version",))
                observed = version_run.process
                if classify_result(version_run) != Outcome.ELABORATED:
                    cleanup_error = version_run.cleanup_error
                    raise ValueError(version_run.infrastructure_error or cleanup_error
                                     or "Worker compiler version check failed")
                version_match = re.search(rb"\bversion\s+(\d+\.\d+\.\d+)(?=[,\s)])",
                                          observed.stdout + b"\n" + observed.stderr)
                if version_match:
                    measured_version = version_match.group(1).decode("ascii")
                if measured_version != EXPECTED_LEAN_VERSION:
                    raise ValueError(f"Expected Lean {EXPECTED_LEAN_VERSION}; observed {measured_version!r}")
                container_names.append("lva-ex03-" + uuid.uuid4().hex)
                candidate_run = self._invoke_container(
                    directory, container_names[-1], ("-j1", "/input/Candidate.lean"),
                )
                observed = candidate_run.process
                status = classify_result(candidate_run)
                infrastructure_error = candidate_run.infrastructure_error
                cleanup_error = candidate_run.cleanup_error
                if status == Outcome.INFRASTRUCTURE_ERROR and not (infrastructure_error or cleanup_error):
                    infrastructure_error = "Worker exit/state was not an ordinary Lean compiler result"
        except (OSError, ValueError, RuntimeError) as error:
            infrastructure_error = str(error)
            status = Outcome.INFRASTRUCTURE_ERROR

        # Control commands have their own small budget. Retained primary logs
        # always obey the caller's candidate-output budget as well.
        stdout = observed.stdout[:self.limits.output_bytes]
        stderr = observed.stderr[:max(0, self.limits.output_bytes - len(stdout))]
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        report = {
            "status": status.value, "task_digest": task_digest,
            "source_sha256": hashlib.sha256(encoded).hexdigest(), "image_id": self.image.image_id,
            "lean_version": measured_version, "returncode": observed.returncode,
            "elapsed_seconds": time.monotonic() - started, "limits": asdict(self.limits),
            "timed_out": observed.timed_out, "output_limit_exceeded": observed.output_limit_exceeded,
            "infrastructure_error": infrastructure_error, "cleanup_error": cleanup_error,
            "container_names": container_names, "preflight": [_process_record(row) for row in controls],
            "version_check": _container_record(version_run), "candidate_check": _container_record(candidate_run),
            "scope": "Compiler execution evidence; final challenge-solution acceptance is separate",
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return LeanRunResult(status, observed.returncode, report["elapsed_seconds"], measured_version,
                             work_directory, stdout_path, stderr_path, report_path)


def _container_record(run: ContainerRun | None) -> dict | None:
    if run is None:
        return None
    return {"process": _process_record(run.process),
            "state": asdict(run.state) if run.state is not None else None,
            "infrastructure_error": run.infrastructure_error, "cleanup_error": run.cleanup_error,
            "control_results": [_process_record(row) for row in run.control_results]}
