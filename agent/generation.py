"""Supplied one-shot services, failure classification, and retained evidence.

The learner connects the services in agent.oneshot; this module owns transport,
parsing, filesystem records, and the existing trusted acceptance checker.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time

from agent.acceptance import AcceptanceImage, AcceptanceResult, AcceptanceRunner
from agent.model_client import ModelReply, ModelStatus, Prompt, PROPOSAL_SCHEMA
from agent.proposal import Proposal
from agent.render import render_candidate
from agent.task import Task
from agent.task_view import public_task


class FlowError(RuntimeError):
    pass


class ModelFailure(RuntimeError):
    def __init__(self, reply):
        self.reply = reply
        super().__init__(reply.error or reply.status.value)


class InvalidProposal(ValueError):
    pass


class EditScopeViolation(InvalidProposal):
    pass


class BudgetExceeded(RuntimeError):
    pass


class CheckerFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    status: str
    report_path: Path


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def learner_source_hashes(root):
    return {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest()
            for name in ("agent/prompts.py", "agent/oneshot.py")}


class OneShotSession:
    """The learner calls generate, parse, render, check exactly in that order.

    Methods save their own evidence. The authoritative verdict comes only from
    the checker. These guards catch controller mistakes; the controller itself
    is trusted Python, not a sandbox for untrusted Python code.
    """

    def __init__(self, root, task, model, work, checker=None):
        self._root, self._task, self._model, self._work = root, task, model, work
        self._checker = checker
        self.reply = None
        self._proposal = None
        self._source = None
        self.acceptance = None
        self.model_calls = 0
        self.acceptance_checks = 0
        self.model_elapsed_seconds = 0

    def generate(self, prompt: Prompt) -> ModelReply:
        if self.model_calls:
            raise FlowError("One-shot flow permits only one model call")
        if not isinstance(prompt, Prompt):
            raise FlowError("Generation prompt must be a Prompt")
        prompt.validate()
        _write_json(self._work / "prompt.json", asdict(prompt))
        self.model_calls += 1
        started = time.monotonic()
        try:
            reply = self._model.generate(prompt)
            if not isinstance(reply, ModelReply):
                raise TypeError("Invalid model reply")
        except Exception:
            # Do not persist arbitrary transport exception strings or secrets.
            reply = ModelReply(ModelStatus.MODEL_ERROR,
                               getattr(self._model, "provider", "unknown"),
                               getattr(self._model, "model", "unknown"),
                               error="Model adapter raised an unexpected error; usage unknown")
        self.model_elapsed_seconds = time.monotonic() - started
        self.reply = reply
        record = asdict(reply)
        raw = record.pop("raw_response")
        record["elapsed_seconds"] = self.model_elapsed_seconds
        _write_json(self._work / "model.json", record)
        if raw is not None:
            _write_json(self._work / "provider-response.json", raw)
        (self._work / "response.txt").write_text(reply.text, encoding="utf-8")
        if reply.status != ModelStatus.COMPLETED:
            raise ModelFailure(reply)
        return reply

    def parse(self, text: str) -> Proposal:
        if (self.reply is None or self.reply.status != ModelStatus.COMPLETED
                or text != self.reply.text or self._proposal is not None):
            raise FlowError("Parse the completed model reply once, without replacing its text")
        try:
            proposal = Proposal.from_json(text)
        except ValueError as error:
            raise InvalidProposal(str(error)) from error
        self._proposal = proposal
        _write_json(self._work / "proposal.json", asdict(proposal))
        return proposal

    def render(self, proposal: Proposal) -> str:
        if self._proposal is None or proposal is not self._proposal or self._source is not None:
            raise FlowError("Render the parsed model proposal once")
        source = render_candidate(self._task, proposal)
        self._source = source
        (self._work / "Candidate.lean").write_text(source, encoding="utf-8")
        return source

    def check(self, source: str) -> AcceptanceResult:
        if self._source is None or source != self._source or self.acceptance_checks:
            raise FlowError("Check the rendered candidate once, without changing its source")
        self.acceptance_checks += 1
        try:
            checker = self._checker
            if checker is None:
                image = AcceptanceImage.load(self._root / "runs/exercise04/image.json")
                checker = AcceptanceRunner(image, root=self._root)
            result = checker.check(self._task, source, artifact_root=self._work / "acceptance")
        except Exception as error:
            raise CheckerFailure(f"Acceptance service failed ({type(error).__name__})") from error
        if not isinstance(result, AcceptanceResult):
            raise CheckerFailure("Acceptance service returned an invalid result")
        self.acceptance = result
        return result


def execute_one_shot(root: Path, model, *, task_id="checked_subtraction", flow=None,
                     artifact_root: Path | None = None, checker=None) -> GenerationResult:
    """Load the trusted task, invoke learner flow, and always retain its outcome."""
    root = Path(root).resolve()
    destination = Path(artifact_root) if artifact_root is not None else root / "runs/exercise05/attempts"
    destination.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=destination)).resolve()
    started = time.monotonic()
    learner_flow = flow is None
    session, task, status, error_message = None, None, "CONTROLLER_ERROR", None
    try:
        task = Task.load(root, task_id)
        view = public_task(task)
        _write_json(work / "task.json", {"digest": task.digest, "public_task": asdict(view)})
        session = OneShotSession(root, task, model, work, checker)
        if flow is None:
            from agent.oneshot import run_one_shot
            flow = run_one_shot
        result = flow(view, session)
        if session.acceptance is None or result is not session.acceptance:
            raise FlowError("Return the acceptance result produced by session.check")
        status = result.status.value
    except NotImplementedError as error:
        status, error_message = "EXERCISE_INCOMPLETE", str(error)
    except ModelFailure as error:
        status, error_message = error.reply.status.value, str(error)
    except EditScopeViolation as error:
        status, error_message = "EDIT_SCOPE_VIOLATION", str(error)
    except BudgetExceeded as error:
        status, error_message = "BUDGET_EXHAUSTED", str(error)
    except InvalidProposal as error:
        status, error_message = "INVALID_PROPOSAL", str(error)
    except CheckerFailure as error:
        status, error_message = "INFRASTRUCTURE_ERROR", str(error)
    except FlowError as error:
        status, error_message = "CONTROLLER_ERROR", str(error)
    except Exception as error:
        # The supplied controller may encounter filesystem/configuration errors.
        # Do not turn arbitrary Python exception text into stored credentials.
        status = "CONTROLLER_ERROR" if session is not None else "INFRASTRUCTURE_ERROR"
        error_message = f"Run failed ({type(error).__name__}); inspect task/prompt/flow configuration"
    reply = session.reply if session else None
    acceptance = session.acceptance if session else None
    report = {
        "schema_version": 1,
        "exercise": 5,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error_message,
        "task_id": task_id,
        "task_digest": task.digest if task else None,
        "provider": getattr(model, "provider", "unknown"),
        "requested_model": getattr(model, "model", "unknown"),
        "learner_flow": learner_flow,
        "learner_source_sha256": learner_source_hashes(root),
        "generation_settings": {
            "api_url": getattr(model, "api_url", None),
            "max_output_tokens": getattr(model, "max_output_tokens", None),
            "socket_timeout_seconds": getattr(model, "timeout_seconds", None),
            "proposal_schema": PROPOSAL_SCHEMA,
            "automatic_retries": 0,
        },
        "model_calls": session.model_calls if session else 0,
        "provider_requests": reply.provider_requests if reply else 0,
        "acceptance_checks": session.acceptance_checks if session else 0,
        "elapsed_seconds": time.monotonic() - started,
        "model_elapsed_seconds": session.model_elapsed_seconds if session else 0,
        "usage": {
            "input_tokens": reply.input_tokens if reply else None,
            "output_tokens": reply.output_tokens if reply else None,
            "reasoning_tokens": reply.reasoning_tokens if reply else None,
            "source": reply.usage_source if reply else "unavailable",
        },
        "acceptance_report": str(acceptance.report_path) if acceptance else None,
        "acceptance_status": acceptance.status.value if acceptance else None,
        "awaiting_implementation_review": True,
    }
    report_path = work / "result.json"
    _write_json(report_path, report)
    return GenerationResult(status, report_path)
