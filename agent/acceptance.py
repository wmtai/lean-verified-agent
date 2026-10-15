"""Fixed-spec acceptance using isolated export and fresh Comparator replay.

The trusted verifier imports no candidate code or candidate olean artifacts.
Only the serialized declaration environment crosses the worker boundary.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from agent.sandbox import (
    CONTROL_OUTPUT_BYTES, CONTROL_TIMEOUT_SECONDS, EXPECTED_LEAN_VERSION,
    MAX_SOURCE_BYTES, ContainerRun, DockerLeanRunner, Outcome, RunnerLimits,
    WorkerImage, _container_record, _process_error, classify_result, run_bounded,
    validate_daemon_info,
)
from agent.task import Task


MAX_EXPORT_BYTES = 16 * 1024 * 1024
MAX_PACKET_BYTES = 24 * 1024 * 1024
TRUSTED_INPUTS = (
    "verification/comparator-lock.json", "verification/VerifyExports.lean",
    "verification/Challenge.lean", "verification/Smoke.lean",
    "verification/worker.py", "verification/Dockerfile",
)


class AcceptanceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    SUBMISSION_REJECTED = "SUBMISSION_REJECTED"
    ELABORATION_FAILED = "ELABORATION_FAILED"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


def policy_digest(root: Path) -> str:
    snapshot = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in TRUSTED_INPUTS}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class AcceptanceImage:
    image_id: str
    task_digest: str
    lean_version: str
    policy_digest: str

    @classmethod
    def load(cls, path: Path) -> "AcceptanceImage":
        try:
            data = json.loads(path.read_text())
            result = cls(**{name: data[name] for name in cls.__dataclass_fields__})
            WorkerImage(result.image_id, result.task_digest, result.lean_version).validate()
            if not isinstance(result.policy_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", result.policy_digest):
                raise ValueError("Invalid acceptance policy digest")
            return result
        except (OSError, TypeError, KeyError, ValueError) as error:
            raise ValueError(f"Cannot load acceptance image: {error}") from error


@dataclass(frozen=True)
class AcceptanceResult:
    status: AcceptanceStatus
    report_path: Path
    work_directory: Path


class AcceptanceRunner(DockerLeanRunner):
    def __init__(self, image: AcceptanceImage, *, root: Path,
                 docker_binary: str = "docker", limits: RunnerLimits | None = None):
        limits = limits or RunnerLimits(wall_seconds=40, memory_mb=1024, output_bytes=MAX_PACKET_BYTES,
                                       tmpfs_mb=96)
        super().__init__(WorkerImage(image.image_id, image.task_digest, image.lean_version),
                         docker_binary=docker_binary, limits=limits)
        self.acceptance_image = image
        self.root = root.resolve()

    def _create_command(self, input_directory: Path, container_name: str,
                        arguments: tuple[str, ...]) -> list[str]:
        if arguments not in (("export",), ("verify",)):
            raise ValueError("Only export and verify worker stages are allowed")
        if not re.fullmatch(r"lva-ex04-[a-f0-9]{32}", container_name):
            raise ValueError("Invalid acceptance container name")
        directory = Path(input_directory)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Worker input must be a nonsymlink directory")
        directory = directory.resolve()
        if any(char in str(directory) for char in (",", "\n", "\r", "\0")):
            raise ValueError("Invalid worker mount path")
        filename = "Candidate.lean" if arguments == ("export",) else "solution.ndjson"
        path = directory / filename
        if ({entry.name for entry in directory.iterdir()} != {filename}
                or path.is_symlink() or not path.is_file()):
            raise ValueError(f"Worker input must contain only {filename}")
        return [
            self.docker_binary, "create", "--name", container_name,
            "--label", "lean-verified-agent.exercise=04", "--pull", "never",
            "--network", "none", "--read-only", "--user", "1000:1000",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
            "--init", "--no-healthcheck", "--pids-limit", str(self.limits.pids),
            "--memory", f"{self.limits.memory_mb}m", "--memory-swap", f"{self.limits.memory_mb}m",
            "--cpus", str(self.limits.cpus), "--shm-size", "8m", "--ulimit", "nofile=128:128",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={self.limits.tmpfs_mb}m,mode=1777",
            "--mount", f"type=bind,source={directory},target=/input,readonly",
            "--log-driver", "none", "--restart", "no", "--workdir", "/trusted",
            "--env", "HOME=/tmp", "--entrypoint", "/opt/python/bin/python3.12",
            self.image.image_id, "-I", "/opt/acceptance/worker.py", *arguments,
        ]

    def _preflight(self, task: Task) -> None:
        if task.digest != self.image.task_digest or policy_digest(self.root) != self.acceptance_image.policy_digest:
            raise ValueError("Task/policy differs from the prepared acceptance image; rebuild it")
        if task.lean_toolchain != f"leanprover/lean4:v{EXPECTED_LEAN_VERSION}":
            raise ValueError("Task toolchain does not match the acceptance checker")
        def control(arguments):
            result = run_bounded([self.docker_binary, *arguments], timeout_seconds=CONTROL_TIMEOUT_SECONDS,
                                 max_output_bytes=CONTROL_OUTPUT_BYTES)
            error = _process_error(result, "Acceptance Docker preflight")
            if error:
                raise ValueError(error)
            return json.loads(result.stdout)
        validate_daemon_info(control(["info", "--format", "{{json .}}"] ))
        endpoint = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
        endpoint = endpoint or control(["context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"])
        if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
            raise ValueError("Acceptance requires a local Docker daemon")

    def _stage(self, directory: Path, name: str, data: bytes, mode: str, container_names: list[str]) -> ContainerRun:
        directory.mkdir(mode=0o755)
        (directory / name).write_bytes(data)
        (directory / name).chmod(0o644)
        container_names.append("lva-ex04-" + uuid.uuid4().hex)
        return self._invoke_container(directory, container_names[-1], (mode,))

    @staticmethod
    def _packet(run: ContainerRun, mode: str) -> dict:
        result = json.loads(run.process.stdout)
        if (not isinstance(result, dict) or type(result.get("protocol")) is not int
                or result.get("protocol") != 1 or result.get("stage") != mode
                or result.get("lean_version") != EXPECTED_LEAN_VERSION):
            raise ValueError("Invalid acceptance worker protocol/version")
        return result

    def check(self, task: Task, source: str, *, artifact_root: Path) -> AcceptanceResult:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Candidate source must be nonempty text")
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("Candidate must be valid UTF-8") from error
        if len(source_bytes) > MAX_SOURCE_BYTES:
            raise ValueError("Candidate exceeds the source byte limit")
        started = time.monotonic()
        artifact_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="attempt-", dir=artifact_root)).resolve()
        (work / "Candidate.lean").write_bytes(source_bytes)
        stages, packets, names = {}, {}, []
        status = AcceptanceStatus.INFRASTRUCTURE_ERROR
        error = None
        try:
            self._preflight(task)
            with tempfile.TemporaryDirectory(prefix="lva-ex04-", dir="/tmp") as temporary:
                base = Path(temporary)
                exported = self._stage(base / "export", "Candidate.lean", source_bytes, "export", names)
                stages["export"] = exported
                observed = classify_result(exported)
                if observed != Outcome.ELABORATED:
                    status = (AcceptanceStatus(observed.value) if observed in (Outcome.TIMEOUT, Outcome.OUTPUT_LIMIT_EXCEEDED)
                              else AcceptanceStatus.INFRASTRUCTURE_ERROR)
                    error = exported.infrastructure_error or exported.cleanup_error
                else:
                    packet = self._packet(exported, "export")
                    encoded_export = packet.pop("export_b64", None)
                    packets["export"] = packet
                    if packet.get("source_sha256") != hashlib.sha256(source_bytes).hexdigest():
                        raise ValueError("Export worker source identity mismatch")
                    if packet.get("status") != "EXPORTED":
                        status = AcceptanceStatus(packet["status"])
                        if status == AcceptanceStatus.VERIFIED:
                            raise ValueError("Export stage cannot grant acceptance")
                    else:
                        if not isinstance(encoded_export, str) or len(encoded_export) > (MAX_EXPORT_BYTES + 2) // 3 * 4:
                            raise ValueError("Missing/oversized serialized declaration environment")
                        data = base64.b64decode(encoded_export, validate=True)
                        if not 0 < len(data) <= MAX_EXPORT_BYTES:
                            raise ValueError("Serialized environment exceeds its byte limit")
                        if hashlib.sha256(data).hexdigest() != packet.get("export_sha256"):
                            raise ValueError("Serialized environment hash mismatch")
                        (work / "solution.ndjson").write_bytes(data)
                        verified = self._stage(base / "verify", "solution.ndjson", data, "verify", names)
                        stages["verify"] = verified
                        observed = classify_result(verified)
                        if observed != Outcome.ELABORATED:
                            status = (AcceptanceStatus(observed.value) if observed in (Outcome.TIMEOUT, Outcome.OUTPUT_LIMIT_EXCEEDED)
                                      else AcceptanceStatus.INFRASTRUCTURE_ERROR)
                            error = verified.infrastructure_error or verified.cleanup_error
                        else:
                            packet = self._packet(verified, "verify")
                            packets["verify"] = packet
                            status = AcceptanceStatus(packet["status"])
                            if status == AcceptanceStatus.VERIFIED:
                                comparator = packet.get("comparator", {})
                                if (comparator.get("returncode") != 0
                                        or "COMPARATOR_ACCEPTED" not in comparator.get("stdout", "").splitlines()):
                                    raise ValueError("Fresh checker did not confirm acceptance")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exception:
            status = AcceptanceStatus.INFRASTRUCTURE_ERROR
            error = str(exception)
        records = {}
        for mode, run in stages.items():
            record = _container_record(run)
            # Large exports live in solution.ndjson, not duplicate JSON logs.
            record["process"]["stdout"] = json.dumps(packets.get(mode, {})) if mode in packets else record["process"]["stdout"][:65536]
            records[mode] = record
        report = {
            "status": status.value, "task_digest": task.digest,
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "image_id": self.image.image_id, "policy_digest": self.acceptance_image.policy_digest,
            "elapsed_seconds": time.monotonic() - started, "limits": asdict(self.limits),
            "container_names": names, "stages": records, "worker_results": packets,
            "error": error, "kernel": "Lean 4.34.1 via pinned Comparator replay",
            "checked_artifact": str(work / "solution.ndjson") if status == AcceptanceStatus.VERIFIED else None,
        }
        path = work / "result.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        return AcceptanceResult(status, path, work)
