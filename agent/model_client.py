"""Supplied single-call Responses API transport and deterministic replay.

No automatic retries or repair calls. HTTP credentials stay in this process;
neither the prompt nor the Lean worker receives them. No SDK is required.
"""

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import socket
from urllib import error, request

from agent.config import LLMConfig


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "implementation_body": {"type": "string"},
        "proof_body": {"type": "string"},
    },
    "required": ["implementation_body", "proof_body"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str

    def validate(self):
        for text in (self.system, self.user):
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Prompt system and user messages must be nonempty strings")
            if len(text.encode("utf-8")) > 128 * 1024:
                raise ValueError("Prompt message exceeds 128 KiB")


class ModelStatus(StrEnum):
    COMPLETED = "COMPLETED"
    MODEL_ERROR = "MODEL_ERROR"
    MODEL_REFUSED = "MODEL_REFUSED"
    MODEL_INCOMPLETE = "MODEL_INCOMPLETE"


@dataclass(frozen=True)
class ModelReply:
    status: ModelStatus
    provider: str
    requested_model: str
    model: str | None = None
    text: str = ""
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    usage_source: str = "unavailable"
    provider_requests: int = 0
    error: str | None = None
    raw_response: object = None


def parse_response(packet, *, provider, requested_model, provider_requests=0):
    """Extract visible message text; reasonings/tools are never treated as JSON."""
    base = {"provider": provider, "requested_model": requested_model,
            "provider_requests": provider_requests, "raw_response": packet}
    if not isinstance(packet, dict):
        return ModelReply(ModelStatus.MODEL_ERROR, **base, error="Provider response must be an object")
    base.update(model=packet.get("model"), response_id=packet.get("id"))
    usage = packet.get("usage")
    if isinstance(usage, dict):
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                base[key] = value
        details = usage.get("output_tokens_details")
        value = details.get("reasoning_tokens") if isinstance(details, dict) else None
        if type(value) is int and value >= 0:
            base["reasoning_tokens"] = value
        if "input_tokens" in base or "output_tokens" in base:
            base["usage_source"] = "fixture" if provider == "replay" else "provider"
    output = packet.get("output")
    if not isinstance(output, list):
        return ModelReply(ModelStatus.MODEL_ERROR, **base, error="Provider response has no output list")
    texts, refusals = [], []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
            continue
        for content in item["content"]:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
            if content.get("type") == "refusal":
                refusals.append(content.get("refusal", "Model refused"))
    text = "".join(texts)
    if packet.get("status") == "incomplete":
        return ModelReply(ModelStatus.MODEL_INCOMPLETE, **base, text=text,
                          error="Model response incomplete; inspect raw response details")
    if packet.get("status") != "completed" or packet.get("error"):
        return ModelReply(ModelStatus.MODEL_ERROR, **base, text=text,
                          error="Provider did not complete the response")
    if refusals:
        return ModelReply(ModelStatus.MODEL_REFUSED, **base, text=text,
                          error="Model refused; inspect raw response details")
    if not text.strip():
        return ModelReply(ModelStatus.MODEL_ERROR, **base, error="Provider returned no assistant text")
    return ModelReply(ModelStatus.COMPLETED, **base, text=text)


class ReplayModel:
    """Read one saved provider-shaped response; no network call or real usage."""

    provider = "replay"
    model = "replay"

    def __init__(self, path: Path):
        self.path = Path(path)

    def generate(self, prompt: Prompt) -> ModelReply:
        prompt.validate()
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("Replay response exceeds byte limit")
            packet = json.loads(data)
        except (OSError, UnicodeError, ValueError, RecursionError):
            return ModelReply(ModelStatus.MODEL_ERROR, self.provider, self.model,
                              error="Cannot read a bounded JSON replay response")
        return parse_response(packet, provider=self.provider, requested_model=self.model)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenAIResponsesModel:
    """One Responses-compatible request, .env settings, no retry/fallback.

    timeout_seconds is the socket operation timeout, not a hard wall-clock
    deadline. Timing and unknown usage are recorded rather than inferred.
    """

    provider = "openai"

    def __init__(self, model: str | None = None, *, max_output_tokens=8192, timeout_seconds=120,
                 env_file: Path | None = None):
        self._config = LLMConfig.load(env_file)
        model = self._config.model if model is None else model
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Set LLM_MODEL in .env or select a model with --model")
        if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be an integer from 16 to 32768")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be greater than zero and at most 300")
        self.model = model
        self.api_url = self._config.api_url
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: Prompt) -> ModelReply:
        prompt.validate()
        base = {"provider": self.provider, "requested_model": self.model}
        key = self._config.api_key
        if not key:
            return ModelReply(ModelStatus.MODEL_ERROR, **base,
                              error="Set LLM_API_KEY in .env; replay needs no API key")
        payload = {
            "model": self.model,
            "input": [{"role": "system", "content": prompt.system},
                      {"role": "user", "content": prompt.user}],
            "text": {"format": {"type": "json_schema", "name": "lean_proposal",
                                "strict": True, "schema": PROPOSAL_SCHEMA}},
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        try:
            req = request.Request(self.api_url, data=json.dumps(payload).encode("utf-8"),
                                  headers={"Authorization": "Bearer " + key,
                                           "Content-Type": "application/json"}, method="POST")
            opener = request.build_opener(_NoRedirect())
            with opener.open(req, timeout=self.timeout_seconds) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    return ModelReply(ModelStatus.MODEL_ERROR, **base, provider_requests=1,
                                      error="Provider response exceeds byte limit; usage unknown")
            packet = json.loads(data)
        except error.HTTPError as failure:
            # Never save headers, credentials, or an error body that could echo them.
            code = failure.code
            failure.close()
            return ModelReply(ModelStatus.MODEL_ERROR, **base, provider_requests=1,
                              error=f"LLM API HTTP {code}; no automatic retry; usage unknown")
        except (error.URLError, OSError, socket.timeout, ValueError, UnicodeError, RecursionError):
            return ModelReply(ModelStatus.MODEL_ERROR, **base, provider_requests=1,
                              error="LLM API transport/response failure; no automatic retry; usage unknown")
        return parse_response(packet, **base, provider_requests=1)
