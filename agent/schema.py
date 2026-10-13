"""Shared, dependency-free data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import math
import re


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    category: str
    split: str
    specification: str
    signature: str
    constraints: tuple[str, ...] = ()
    forbidden_identifiers: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> Task:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["constraints"] = tuple(data.get("constraints", ()))
        data["forbidden_identifiers"] = tuple(data.get("forbidden_identifiers", ()))
        task = cls(**data)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", task.id):
            raise ValueError("Task id must be a lowercase identifier")
        if task.split not in {"dev", "eval"}:
            raise ValueError("Task split must be dev or eval")
        if not task.specification.strip() or not task.signature.strip():
            raise ValueError("Task requires a specification and signature")
        return task

    @property
    def digest(self) -> str:
        from dataclasses import asdict
        encoded = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Candidate:
    implementation: str
    proof: str

    @classmethod
    def parse(cls, text: str) -> Candidate:
        stripped = text.strip()
        if stripped.startswith("```json\n") and stripped.endswith("```"):
            stripped = stripped[8:-3].strip()
        data = json.loads(stripped)
        if not isinstance(data, dict) or set(data) != {"implementation", "proof"}:
            raise ValueError("Return exactly implementation and proof fields")
        if any(not isinstance(v, str) or not v.strip() for v in data.values()):
            raise ValueError("Implementation and proof must be nonempty strings")
        if sum(len(v.encode()) for v in data.values()) > 65536:
            raise ValueError("Candidate exceeds 64 KiB")
        return cls(**data)


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    category: str
    diagnostics: str
    elapsed_seconds: float
    lean_checks: int = 0


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = "unknown"


@dataclass(frozen=True)
class Budget:
    max_calls: int = 5
    max_lean_checks: int = 10
    max_tokens: int = 30000
    max_seconds: float = 300.0
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_seconds):
            raise ValueError("Time budget must be finite")
        if min(self.max_calls, self.max_lean_checks, self.max_tokens,
               self.max_seconds, self.max_output_tokens) <= 0:
            raise ValueError("All budget limits must be positive")


@dataclass
class RunResult:
    task_id: str
    strategy: str
    status: str
    attempts: int = 0
    llm_calls: int = 0
    lean_checks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    implementation_revisions: int = 0
    proof_revisions: int = 0
    failure_categories: dict[str, int] = field(default_factory=dict)
    task_digest: str = ""
    model: str = "unknown"
    run_dir: str = ""
