"""Execute untrusted Lean in a resource-limited Docker container by default."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

from agent.schema import Candidate, Task, VerificationResult
from .acceptance import PolicyViolation, has_acceptance_marker, render_candidate


LEAN_VERSION = "4.34.1"
DEFAULT_IMAGE = f"lean-verified-agent-verifier:{LEAN_VERSION}"
MAX_OUTPUT_BYTES = 65536


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    output: str
    timed_out: bool = False
    output_limited: bool = False


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_bounded(command: list[str], *, cwd: Path, timeout: float,
                env: dict[str, str] | None = None,
                max_output_bytes: int = MAX_OUTPUT_BYTES) -> ProcessResult:
    """Bound both execution time and captured output without buffering it all."""
    if timeout <= 0:
        return ProcessResult(-1, "Verification wall-clock deadline exhausted", timed_out=True)
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    output = bytearray()
    timed_out = False
    output_limited = False
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process(process)
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                available = max_output_bytes - len(output)
                output.extend(chunk[:available])
                if len(chunk) > available:
                    output_limited = True
                    _kill_process(process)
                    break
            if output_limited:
                break
        # A subprocess may close stdout then continue executing.
        if not timed_out and not output_limited:
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process(process)
    process.stdout.close()
    return ProcessResult(process.returncode, output.decode("utf-8", errors="replace"),
                         timed_out=timed_out, output_limited=output_limited)


class LeanRunner:
    """A fixed-source verifier with a second, fresh-process acceptance check.

    `backend="local", allow_local=True` is only for manually reviewed fixtures.
    It is deliberately never selected as a fallback when Docker fails.
    """

    lean_version = LEAN_VERSION

    def __init__(self, project_root: Path, backend: str = "docker", timeout_seconds: float = 30,
                 image: str = DEFAULT_IMAGE, allow_local: bool = False):
        if backend not in {"docker", "local"}:
            raise ValueError("Backend must be docker or local")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Timeout must be positive and finite")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*", image):
            raise ValueError("Invalid Docker image name")
        self.project_root = Path(project_root).resolve()
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self.image = image
        self.allow_local = allow_local
        self._local_ready = False
        self._lean_binary: str | None = None

    def _prepare_local(self, timeout: float) -> ProcessResult | None:
        if not self.allow_local:
            return ProcessResult(-1, "Local verification requires explicit --allow-local for reviewed fixtures")
        if self._local_ready:
            return None
        binary = os.environ.get("LEAN_BINARY") or shutil.which("lean")
        if not binary:
            return ProcessResult(-1, "Pinned Lean is unavailable; install the lean-toolchain version")
        started = time.monotonic()
        version = run_bounded([binary, "--version"], cwd=self.project_root, timeout=min(timeout, 5))
        if version.timed_out or version.returncode or not re.search(
                rf"\bversion {re.escape(LEAN_VERSION)}(?:,|\s|\))", version.output):
            return ProcessResult(-1, f"Expected Lean {LEAN_VERSION}; got: {version.output}",
                                 timed_out=version.timed_out)
        source = self.project_root / "lean" / "Trusted" / "Audit.lean"
        output = source.with_suffix(".olean")
        # Rebuild the tiny trusted module once per runner. Never accept a stale
        # cache produced under another toolchain or a previous trusted module.
        environment = os.environ.copy()
        environment["LEAN_PATH"] = str(self.project_root / "lean")
        build = run_bounded([binary, "-j1", "-M2048", "-o", str(output), str(source)],
                            cwd=self.project_root / "lean", env=environment,
                            timeout=max(0.001, timeout - (time.monotonic() - started)))
        if build.returncode or build.timed_out or build.output_limited:
            return ProcessResult(build.returncode or -1,
                                 "Trusted audit module failed to build:\n" + build.output,
                                 build.timed_out, build.output_limited)
        self._lean_binary = binary
        self._local_ready = True
        return None

    def _command(self, submission: Path, name: str) -> tuple[list[str], dict[str, str] | None]:
        if self.backend == "local":
            assert self._lean_binary is not None
            environment = os.environ.copy()
            environment["LEAN_PATH"] = str(self.project_root / "lean")
            return ([self._lean_binary, "-j1", "-M2048", "Candidate.lean"], environment)
        if "," in str(submission):
            raise ValueError("Docker submission paths may not contain commas")
        return ([
            "docker", "run", "--rm", "--pull", "never", "--name", name,
            "--network", "none", "--read-only", "--user", "10001:10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "2g", "--memory-swap", "2g",
            "--cpus", "1", "--ulimit", "nofile=256:256",
            "--mount", f"type=bind,src={submission},dst=/submission,readonly",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--workdir", "/submission",
            self.image, "lean", "-j1", "-M2048", "Candidate.lean",
        ], None)

    def _cleanup_container(self, name: str) -> None:
        try:
            run_bounded(["docker", "rm", "--force", name], cwd=self.project_root,
                        timeout=3, max_output_bytes=2048)
        except OSError:
            pass

    @staticmethod
    def _docker_launch_failed(result: ProcessResult) -> bool:
        return result.returncode in {125, 126, 127} or any(fragment in result.output.lower() for fragment in (
            "cannot connect to the docker daemon", "permission denied while trying to connect",
            "error during connect", "unable to find image", "docker: command not found",
        ))

    @staticmethod
    def _failure_category(result: ProcessResult, backend: str) -> str:
        if result.timed_out:
            return "timeout"
        if result.output_limited:
            return "output_limit"
        # Docker reserves these exit codes for setup/launch failures.
        if backend == "docker" and LeanRunner._docker_launch_failed(result):
            return "infrastructure_error"
        if "Trusted candidate boundary:" in result.output:
            return "policy_rejected"
        if "unsolved goals" in result.output:
            return "unsolved_goals"
        if "type mismatch" in result.output or "application type mismatch" in result.output:
            return "type_error"
        if "unexpected token" in result.output or "unknown identifier" in result.output:
            return "elaboration_error"
        if "Trusted audit:" in result.output:
            return "acceptance_rejected"
        return "lean_error"

    def verify(self, task: Task, candidate: Candidate, work_dir: Path,
               timeout_seconds: float | None = None) -> VerificationResult:
        started = time.monotonic()
        timeout = self.timeout_seconds if timeout_seconds is None else min(
            self.timeout_seconds, timeout_seconds)
        token = uuid.uuid4().hex
        try:
            source = render_candidate(task, candidate, token)
        except (PolicyViolation, ValueError, TypeError) as error:
            return VerificationResult(False, "policy_rejected", str(error),
                                      time.monotonic() - started, 0)
        if timeout <= 0:
            return VerificationResult(False, "timeout", "Verification deadline exhausted", 0, 0)
        deadline = started + timeout
        checks = 0
        diagnostics: list[str] = []
        try:
            if self.backend == "local":
                preparation = self._prepare_local(max(0.001, deadline - time.monotonic()))
                if preparation is not None:
                    category = "timeout" if preparation.timed_out else "infrastructure_error"
                    return VerificationResult(False, category, preparation.output,
                                              time.monotonic() - started, 0)
            elif not shutil.which("docker"):
                return VerificationResult(False, "infrastructure_error", "Docker is unavailable",
                                          time.monotonic() - started, 0)
            work_dir = Path(work_dir).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)
            # The permanent artifact is available for trace inspection; the
            # container receives only a disposable directory containing source.
            (work_dir / "Candidate.lean").write_text(source, encoding="utf-8")
            for check in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return VerificationResult(False, "timeout", "Independent verification deadline exhausted",
                                              time.monotonic() - started, checks)
                with tempfile.TemporaryDirectory(prefix="lean-check-", dir=work_dir) as temporary:
                    submission = Path(temporary)
                    submission.chmod(0o755)
                    (submission / "Candidate.lean").write_text(source, encoding="utf-8")
                    (submission / "Candidate.lean").chmod(0o644)
                    name = "lean-verifier-" + uuid.uuid4().hex
                    command, environment = self._command(submission, name)
                    try:
                        result = run_bounded(command, cwd=submission, timeout=remaining, env=environment)
                        # A Docker launch failure did not actually check Lean.
                        if not (self.backend == "docker" and self._docker_launch_failed(result)):
                            checks += 1
                    finally:
                        if self.backend == "docker":
                            self._cleanup_container(name)
                    label = "Initial check" if check == 0 else "Independent recheck"
                    diagnostics.append(f"{label}:\n{result.output}")
                    if result.returncode or result.timed_out or result.output_limited:
                        return VerificationResult(False, self._failure_category(result, self.backend),
                                                  "\n".join(diagnostics), time.monotonic() - started, checks)
                    if not has_acceptance_marker(result.output, token):
                        return VerificationResult(False, "acceptance_rejected",
                                                  "\n".join(diagnostics) + "\nTrusted acceptance marker is missing",
                                                  time.monotonic() - started, checks)
        except (OSError, ValueError) as error:
            return VerificationResult(False, "infrastructure_error", str(error),
                                      time.monotonic() - started, checks)
        return VerificationResult(True, "verified", "\n".join(diagnostics),
                                  time.monotonic() - started, checks)
