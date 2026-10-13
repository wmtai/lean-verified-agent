"""Budgeted generation, sampling, repair, and proof-planning experiments."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import shutil
import time
from typing import Protocol

from agent.prompts import generation_messages, planning_messages, repair_messages
from agent.repair import INFRASTRUCTURE_CATEGORIES, categorize_failure, repair_advice
from agent.schema import Budget, Candidate, ModelResponse, RunResult, Task, VerificationResult


STRATEGIES = ("one-shot", "sampling", "repair", "planning")


class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, str]], max_output_tokens: int,
                 timeout_seconds: float) -> ModelResponse: ...


class Verifier(Protocol):
    def verify(self, task: Task, candidate: Candidate, work_dir: Path,
               timeout_seconds: float | None = None) -> VerificationResult: ...


def estimate_prompt_tokens(messages: list[dict[str, str]]) -> int:
    """Reserve UTF-8 bytes plus framing as conservative tokenizer headroom.

    Exact provider tokenization is unknown. Missing provider usage is recorded
    with this estimate; the trace distinguishes it from reported usage.
    """
    return 32 + sum(len(message["content"].encode("utf-8")) + 16 for message in messages)


def _estimate_output_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def _atomic_json(path: Path, data: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(task: Task, client: ModelClient, runner: Verifier, strategy: str,
        budget: Budget, output_dir: str | Path) -> RunResult:
    """Run one task and preserve all requests, responses, and verification traces.

    The verifier owns the two independent checks needed for acceptance. Two
    checks are reserved before each candidate so a passing first check never
    silently exceeds the verification budget. All planning calls count.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "result.json").exists() or (run_dir / "attempts").exists():
        raise ValueError("Output directory already contains a run; choose a new directory")
    attempts_dir = run_dir / "attempts"
    attempts_dir.mkdir()
    started = time.monotonic()
    result = RunResult(task_id=task.id, strategy=strategy,
                       status="UNSOLVED_WITHIN_BUDGET", task_digest=task.digest,
                       model=str(getattr(client, "model", "unknown")),
                       run_dir=str(run_dir.resolve()))
    metadata = {
        "schema_version": 1,
        "budgets": asdict(budget),
        "provider": str(getattr(client, "provider", type(client).__name__)),
        "requested_model": str(getattr(client, "model", "unknown")),
        "verifier": type(runner).__name__,
        "token_accounting": "provider-reported when nonzero; conservative input estimate otherwise",
        "input_usage_estimated": False,
        "output_usage_estimated": False,
        "stop_reason": "budget exhausted",
    }
    for attribute, key in (("backend", "verifier_backend"), ("image", "verifier_image"),
                           ("lean_version", "lean_version"), ("allow_local", "allow_local")):
        value = getattr(runner, attribute, None)
        if isinstance(value, (str, bool)):
            metadata[key] = value
    _atomic_json(run_dir / "task.json", asdict(task))

    def remaining_seconds() -> float:
        return budget.max_seconds - (time.monotonic() - started)

    def save() -> None:
        result.elapsed_seconds = time.monotonic() - started
        _atomic_json(run_dir / "result.json", {**asdict(result), **metadata})

    def record_failure(category: str) -> None:
        result.failure_categories[category] = result.failure_categories.get(category, 0) + 1

    def request(messages: list[dict[str, str]], directory: Path) -> ModelResponse | None:
        reserve = estimate_prompt_tokens(messages)
        available = budget.max_tokens - result.input_tokens - result.output_tokens - reserve
        if result.llm_calls >= budget.max_calls:
            metadata["stop_reason"] = "model-call budget exhausted"
            return None
        if available < 1:
            metadata["stop_reason"] = "token budget cannot fit prompt and output"
            return None
        seconds = remaining_seconds()
        if seconds <= 0:
            metadata["stop_reason"] = "wall-time budget exhausted"
            return None
        directory.mkdir(parents=True, exist_ok=True)
        _atomic_json(directory / "prompts.json", messages)
        output_limit = min(budget.max_output_tokens, available)
        call_data = {
            "estimated_input_tokens": reserve,
            "max_output_tokens": output_limit,
            "timeout_seconds": seconds,
        }
        result.llm_calls += 1
        call_started = time.monotonic()
        try:
            response = client.complete(messages, max_output_tokens=output_limit,
                                       timeout_seconds=seconds)
            if (not isinstance(response, ModelResponse) or
                    min(response.input_tokens, response.output_tokens) < 0):
                raise ValueError("Client returned an invalid ModelResponse")
        except Exception as exc:
            # Only a sanitized exception class is persisted. A provider or
            # custom client can include a credential in its exception text.
            result.status = "ERROR"
            metadata["stop_reason"] = "model client failure"
            record_failure("model_error")
            call_data.update({"error": type(exc).__name__,
                              "elapsed_seconds": time.monotonic() - call_started})
            _atomic_json(directory / "call.json", call_data)
            return None
        input_estimated = response.input_tokens == 0
        output_estimated = response.output_tokens == 0
        charged_input = reserve if input_estimated else response.input_tokens
        charged_output = _estimate_output_tokens(response.text) if output_estimated else response.output_tokens
        result.input_tokens += charged_input
        result.output_tokens += charged_output
        result.model = response.model
        metadata["input_usage_estimated"] |= input_estimated
        metadata["output_usage_estimated"] |= output_estimated
        call_data.update({
            "model": response.model,
            "input_tokens": charged_input,
            "output_tokens": charged_output,
            "input_usage_estimated": input_estimated,
            "output_usage_estimated": output_estimated,
            "elapsed_seconds": time.monotonic() - call_started,
        })
        (directory / "response.txt").write_text(response.text, encoding="utf-8")
        _atomic_json(directory / "call.json", call_data)
        return response

    plan: str | None = None
    previous_text: str | None = None
    previous_candidate: Candidate | None = None
    previous_category = ""
    previous_diagnostics = ""
    try:
        if strategy == "planning":
            planned = request(planning_messages(task), run_dir / "planning")
            if planned is None:
                save()
                return result
            plan = planned.text
            save()

        while True:
            if result.lean_checks + 2 > budget.max_lean_checks:
                metadata["stop_reason"] = "Lean-check budget cannot fit final recheck"
                break
            if remaining_seconds() <= 0:
                metadata["stop_reason"] = "wall-time budget exhausted"
                break
            if strategy == "one-shot" and result.attempts:
                metadata["stop_reason"] = "one-shot attempt completed"
                break
            messages = generation_messages(task, plan)
            if strategy in {"repair", "planning"} and previous_text is not None:
                messages = repair_messages(task, previous_text, previous_category,
                                           previous_diagnostics,
                                           repair_advice(previous_category, previous_diagnostics), plan)
            directory = attempts_dir / f"{result.attempts + 1:04d}"
            response = request(messages, directory)
            if response is None:
                break
            result.attempts += 1
            previous_text = response.text
            try:
                candidate = Candidate.parse(response.text)
            except (ValueError, TypeError) as exc:
                previous_category = "invalid_json"
                previous_diagnostics = str(exc)
                record_failure(previous_category)
                _atomic_json(directory / "verification.json", {
                    "accepted": False, "category": previous_category,
                    "diagnostics": previous_diagnostics, "lean_checks": 0,
                })
                (directory / "diagnostics.txt").write_text(previous_diagnostics + "\n", encoding="utf-8")
                if result.input_tokens + result.output_tokens > budget.max_tokens:
                    metadata["stop_reason"] = "provider token usage exceeded total budget"
                    save()
                    break
                save()
                continue
            _atomic_json(directory / "candidate.json", asdict(candidate))
            if previous_candidate is not None:
                if candidate.implementation != previous_candidate.implementation:
                    result.implementation_revisions += 1
                elif candidate.proof != previous_candidate.proof:
                    result.proof_revisions += 1
            previous_candidate = candidate
            if result.input_tokens + result.output_tokens > budget.max_tokens:
                metadata["stop_reason"] = "provider token usage exceeded total budget"
                save()
                break
            seconds = remaining_seconds()
            if seconds <= 0:
                metadata["stop_reason"] = "wall-time budget exhausted after model call"
                save()
                break
            try:
                verification = runner.verify(task, candidate, directory,
                                             timeout_seconds=seconds)
                if (not isinstance(verification, VerificationResult) or
                        not 0 <= verification.lean_checks <= 2):
                    raise ValueError("Verifier returned invalid check accounting")
            except Exception as exc:
                result.status = "ERROR"
                metadata["stop_reason"] = "verifier infrastructure failure"
                record_failure("infrastructure_error")
                _atomic_json(directory / "verification.json", {
                    "accepted": False, "category": "infrastructure_error",
                    "diagnostics": f"Verifier raised {type(exc).__name__}", "lean_checks": 0,
                })
                save()
                break
            result.lean_checks += verification.lean_checks
            _atomic_json(directory / "verification.json", asdict(verification))
            (directory / "diagnostics.txt").write_text(verification.diagnostics, encoding="utf-8")
            if verification.accepted:
                if verification.lean_checks != 2:
                    result.status = "ERROR"
                    metadata["stop_reason"] = "acceptance requires two independent Lean checks"
                    record_failure("infrastructure_error")
                elif remaining_seconds() < 0:
                    metadata["stop_reason"] = "verification exceeded wall-time budget"
                else:
                    result.status = "VERIFIED"
                    metadata["stop_reason"] = "trusted acceptance completed"
                    _atomic_json(run_dir / "verified_candidate.json", asdict(candidate))
                    if (directory / "Candidate.lean").exists():
                        shutil.copyfile(directory / "Candidate.lean", run_dir / "Verified.lean")
                save()
                break
            previous_category = categorize_failure(verification.category, verification.diagnostics)
            previous_diagnostics = verification.diagnostics
            record_failure(previous_category)
            if previous_category in INFRASTRUCTURE_CATEGORIES:
                result.status = "ERROR"
                metadata["stop_reason"] = "verifier infrastructure failure"
                save()
                break
            save()
    finally:
        save()
    return result
