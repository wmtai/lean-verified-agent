"""Supplied Exercise 6 history, replay, budget guards, and repair services.

Learner decisions live in agent.repair; no live requests are made by setup or
review. Nested attempts reuse the established parser, renderer and checker.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time

from agent.generation import (BudgetExceeded, EditScopeViolation, FlowError,
                              GenerationResult, _write_json, execute_one_shot)
from agent.model_client import ModelReply, ModelStatus, Prompt, ReplayModel
from agent.proposal import Proposal
from agent.task import Task
from agent.task_view import public_task


class RepairAction(StrEnum):
    GENERATE = "GENERATE"
    REPAIR_PROOF = "REPAIR_PROOF"
    REGENERATE = "REGENERATE"
    STOP = "STOP"


TERMINAL_ERRORS = frozenset({"MODEL_ERROR", "MODEL_REFUSED", "INFRASTRUCTURE_ERROR",
                             "CONTROLLER_ERROR", "EDIT_SCOPE_VIOLATION", "EXERCISE_INCOMPLETE"})
REGENERATE_STATUSES = frozenset({"INVALID_PROPOSAL", "MODEL_INCOMPLETE", "SUBMISSION_REJECTED",
                                "TIMEOUT", "OUTPUT_LIMIT_EXCEEDED"})


@dataclass(frozen=True)
class Attempt:
    number: int
    action: RepairAction
    status: str
    proposal: Proposal | None
    source: str | None
    diagnostics: str
    response_text: str
    report_path: Path
    # Optional independently reviewed evidence, never inferred from a proof error.
    behavioral_counterexample: str | None = None


@dataclass(frozen=True)
class BudgetLimits:
    max_attempts: int = 3
    max_model_calls: int = 3
    max_submissions: int = 3
    max_checks: int = 3
    max_total_tokens: int = 32768
    wall_seconds: float = 600

    def __post_init__(self):
        for name in ("max_attempts", "max_model_calls", "max_submissions", "max_checks", "max_total_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if (type(self.wall_seconds) not in (int, float) or not math.isfinite(self.wall_seconds)
                or self.wall_seconds <= 0):
            raise ValueError("wall_seconds must be finite and positive")


@dataclass(frozen=True)
class BudgetState:
    can_attempt: bool
    reason: str | None
    attempts_remaining: int
    model_calls_remaining: int
    submissions_remaining: int
    checks_remaining: int
    tokens_remaining: int
    seconds_remaining: float
    usage_known: bool


@dataclass(frozen=True)
class RepairOutcome:
    status: str
    accepted_report: Path | None


def source_hashes(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("agent/prompts.py", "agent/repair_prompts.py", "agent/repair.py")}


def _bounded_text(text, limit=16384):
    data = text.encode("utf-8")
    return text if len(data) <= limit else data[:limit].decode("utf-8", errors="replace") + "\n[truncated]"


def load_attempt(path, number, action):
    report = json.loads(path.read_text())
    folder = path.parent
    proposal_path = folder / "proposal.json"
    proposal = Proposal.from_json(proposal_path.read_text()) if proposal_path.exists() else None
    source_path = folder / "Candidate.lean"
    response_path = folder / "response.txt"
    messages = [report.get("error") or ""]
    if report.get("acceptance_report"):
        acceptance = json.loads(Path(report["acceptance_report"]).read_text())
        messages.append(acceptance.get("error") or "")
        for packet in acceptance.get("worker_results", {}).values():
            for kind in ("compilation", "exporter", "smoke", "comparator"):
                detail = packet.get(kind, {})
                messages.extend([detail.get("stdout") or "", detail.get("stderr") or ""])
    return Attempt(number, action, report["status"], proposal,
                   source_path.read_text() if source_path.exists() else None,
                   _bounded_text("\n".join(message for message in messages if message)),
                   _bounded_text(response_path.read_text()) if response_path.exists() else "",
                   path)


class SequenceReplay:
    provider = "replay"
    model = "sequence-replay"

    def __init__(self, paths):
        self.paths = tuple(Path(path) for path in paths)
        self.calls = 0

    def generate(self, prompt):
        index = self.calls
        self.calls += 1
        if index >= len(self.paths):
            return ModelReply(ModelStatus.MODEL_ERROR, self.provider, self.model,
                              error="Replay sequence exhausted; the controller should have stopped")
        return ReplayModel(self.paths[index]).generate(prompt)


class RepairSession:
    def __init__(self, root, task, model, work, *, limits=None, checker=None, clock=time.monotonic):
        self.root, self.task, self.model, self.work = root, task, model, work
        self.limits = limits or BudgetLimits()
        self.checker, self.clock = checker, clock
        self.started = clock()
        self._history = []
        self._seed_elapsed = 0
        self._seed_model_calls = self._seed_provider_requests = 0
        self._usage_sources = set()
        self.model_calls = self.provider_requests = self.submissions = self.checks = 0
        self.input_tokens = self.output_tokens = 0
        self.usage_known = True
        self.outcome = None

    @property
    def history(self) -> tuple[Attempt, ...]:
        return tuple(self._history)

    @property
    def budget(self) -> BudgetState:
        limits = self.limits
        remaining = (
            limits.max_attempts - len(self._history), limits.max_model_calls - self.model_calls,
            limits.max_submissions - self.submissions, limits.max_checks - self.checks,
            limits.max_total_tokens - self.input_tokens - self.output_tokens,
            limits.wall_seconds - (self.clock() - self.started + self._seed_elapsed),
        )
        names = ("attempt limit", "model-call limit", "submission limit", "check limit", "token threshold", "time threshold")
        reason = ("token usage unknown" if not self.usage_known else
                  next((name for name, value in zip(names, remaining) if value <= 0), None))
        # The live API requires at least 16 generated tokens per request.
        if reason is None and remaining[4] < 16:
            reason = "insufficient remaining token allowance"
        return BudgetState(reason is None, reason, *remaining, self.usage_known)

    def _charge(self, report):
        self.model_calls += report.get("model_calls", 0)
        self.provider_requests += report.get("provider_requests", 0)
        self.submissions += report.get("acceptance_checks", 0)
        self.checks += report.get("acceptance_checks", 0)
        if report.get("model_calls", 0):
            usage = report.get("usage", {})
            self._usage_sources.add(usage.get("source", "unavailable"))
            values = usage.get("input_tokens"), usage.get("output_tokens")
            if any(type(value) is not int or value < 0 for value in values):
                self.usage_known = False
            else:
                self.input_tokens += values[0]
                self.output_tokens += values[1]

    def seed(self, path):
        """Retain an earlier failed one-shot attempt and charge its resources."""
        if self._history:
            raise FlowError("A seed may only be loaded before new attempts")
        path = Path(path).resolve()
        report = json.loads(path.read_text())
        if report.get("task_digest") != self.task.digest or report.get("status") != "ELABORATION_FAILED":
            raise ValueError("Seed must be a failed-proof run for this exact task")
        if (type(report.get("model_calls")) is not int or report["model_calls"] != 1
                or type(report.get("acceptance_checks")) is not int or report["acceptance_checks"] != 1
                or type(report.get("provider_requests")) is not int or report["provider_requests"] not in (0, 1)):
            raise ValueError("Seed must retain its one model call, check, and provider-request count")
        elapsed = report.get("elapsed_seconds", 0)
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Seed elapsed time is invalid")
        attempt = load_attempt(path, 1, RepairAction.GENERATE)
        if attempt.proposal is None or attempt.source is None:
            raise ValueError("Seed must contain the original proposal and source")
        from agent.render import render_candidate
        if render_candidate(self.task, attempt.proposal) != attempt.source:
            raise ValueError("Seed source does not match its proposal and fixed task")
        acceptance = json.loads(Path(report["acceptance_report"]).read_text())
        if (acceptance.get("status") != "ELABORATION_FAILED"
                or acceptance.get("task_digest") != self.task.digest
                or acceptance.get("source_sha256") != hashlib.sha256(attempt.source.encode()).hexdigest()):
            raise ValueError("Seed checker evidence does not match its source")
        snapshot = self.work / "seed"
        snapshot.mkdir()
        for filename in ("result.json", "proposal.json", "Candidate.lean", "prompt.json", "model.json", "response.txt"):
            source = path.parent / filename
            if source.exists():
                (snapshot / filename).write_bytes(source.read_bytes())
        _write_json(snapshot / "origin.json", {"original_report": str(path),
                                               "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        self._history.append(attempt)
        self._charge(report)
        self._seed_elapsed = elapsed
        self._seed_model_calls = report["model_calls"]
        self._seed_provider_requests = report["provider_requests"]

    def attempt(self, prompt: Prompt, action: RepairAction) -> Attempt:
        if self.outcome is not None or (self._history and self._history[-1].status == "VERIFIED"):
            raise FlowError("Stop immediately after accepted success")
        if not self.budget.can_attempt:
            raise BudgetExceeded(self.budget.reason)
        if action not in (RepairAction.GENERATE, RepairAction.REPAIR_PROOF, RepairAction.REGENERATE):
            raise FlowError("Use a generation/repair action for an attempt")
        previous = self._history[-1] if self._history else None
        if (previous is None) != (action == RepairAction.GENERATE):
            raise FlowError("GENERATE is the first action only")
        if action == RepairAction.REPAIR_PROOF and (previous is None or previous.proposal is None):
            raise FlowError("Proof repair needs a previous parsed proposal")

        def one_attempt(view, session):
            reply = session.generate(prompt)
            used = reply.input_tokens, reply.output_tokens
            if any(type(value) is not int or value < 0 for value in used):
                raise BudgetExceeded("Token usage unknown; stop before further checking or generation")
            if sum(used) + self.input_tokens + self.output_tokens > self.limits.max_total_tokens:
                raise BudgetExceeded("Reported token threshold exceeded by the completed response")
            if self.budget.seconds_remaining <= 0:
                raise BudgetExceeded("Time threshold reached during model call")
            proposal = session.parse(reply.text)
            if (action == RepairAction.REPAIR_PROOF
                    and proposal.implementation_body != previous.proposal.implementation_body):
                raise EditScopeViolation("Proof-only repair changed implementation_body; copy it exactly")
            source = session.render(proposal)
            return session.check(source)

        original_cap = getattr(self.model, "max_output_tokens", None)
        if original_cap is not None:
            self.model.max_output_tokens = min(original_cap, self.budget.tokens_remaining)
        try:
            result = execute_one_shot(self.root, self.model, task_id=self.task.id, flow=one_attempt,
                                      checker=self.checker, artifact_root=self.work / "attempts")
        finally:
            if original_cap is not None:
                self.model.max_output_tokens = original_cap
        report = json.loads(result.report_path.read_text())
        self._charge(report)
        observed = load_attempt(result.report_path, len(self._history) + 1, action)
        self._history.append(observed)
        _write_json(self.work / "history.json", [asdict(item) | {"report_path": str(item.report_path)}
                                                for item in self.history])
        return observed

    def finish(self):
        latest = self._history[-1] if self._history else None
        elapsed_over = self.budget.seconds_remaining < 0
        tokens_over = self.budget.tokens_remaining < 0 or not self.usage_known
        if latest and latest.status in TERMINAL_ERRORS:
            status = latest.status
        elif elapsed_over or tokens_over or (latest and latest.status == "BUDGET_EXHAUSTED"):
            status = "BUDGET_EXHAUSTED"
        elif latest and latest.status == "VERIFIED":
            status = "VERIFIED"
        elif not self.budget.can_attempt:
            status = "BUDGET_EXHAUSTED"
        else:
            status = "STOPPED"
        self.outcome = RepairOutcome(status, latest.report_path if latest and latest.status == "VERIFIED" else None)
        return self.outcome


def execute_repair(root, model, *, limits=None, seed_run=None, checker=None, flow=None, artifact_root=None):
    root = Path(root).resolve()
    destination = Path(artifact_root) if artifact_root is not None else root / "runs/exercise06/attempts"
    destination.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=destination)).resolve()
    task = Task.load(root, "checked_subtraction")
    _write_json(work / "task.json", {"digest": task.digest, "public_task": asdict(public_task(task))})
    session = RepairSession(root, task, model, work, limits=limits, checker=checker)
    learner_flow = flow is None
    error = None
    try:
        if seed_run is not None:
            session.seed(seed_run)
        if flow is None:
            from agent.repair import run_repair
            flow = run_repair
        result = flow(public_task(task), session)
        if session.outcome is None or result is not session.outcome:
            raise FlowError("Return session.finish() when your policy chooses STOP")
        status = result.status
    except NotImplementedError as failure:
        status, error = "EXERCISE_INCOMPLETE", str(failure)
    except (FlowError, BudgetExceeded) as failure:
        status, error = "CONTROLLER_ERROR", str(failure)
    except Exception as failure:
        status, error = "INFRASTRUCTURE_ERROR", f"Repair service failed ({type(failure).__name__})"
    history = [asdict(item) | {"report_path": str(item.report_path)} for item in session.history]
    report = {
        "exercise": 6, "status": status, "error": error,
        "task_digest": task.digest, "learner_flow": learner_flow,
        "learner_source_sha256": source_hashes(root),
        "provider": getattr(model, "provider", "unknown"), "requested_model": getattr(model, "model", "unknown"),
        "api_url": getattr(model, "api_url", None),
        "seed_run": str(Path(seed_run).resolve()) if seed_run else None,
        "limits": asdict(session.limits), "budget": asdict(session.budget),
        "model_calls": session.model_calls, "provider_requests": session.provider_requests,
        "seed_model_calls": session._seed_model_calls, "seed_provider_requests": session._seed_provider_requests,
        "new_model_calls": session.model_calls - session._seed_model_calls,
        "new_provider_requests": session.provider_requests - session._seed_provider_requests,
        "candidate_submissions": session.submissions, "acceptance_checks": session.checks,
        "input_tokens": session.input_tokens if session.usage_known else None,
        "output_tokens": session.output_tokens if session.usage_known else None,
        "usage_known": session.usage_known,
        "usage_source": (next(iter(session._usage_sources)) if len(session._usage_sources) == 1
                         else "mixed" if session._usage_sources else "unavailable"),
        "elapsed_seconds": session.clock() - session.started + session._seed_elapsed,
        "history": history, "awaiting_implementation_review": True,
    }
    _write_json(work / "result.json", report)
    _write_json(work / "history.json", history)
    return GenerationResult(status, work / "result.json")
