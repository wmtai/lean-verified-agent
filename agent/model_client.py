"""Small, dependency-free model adapters with an offline replay mode."""

from __future__ import annotations

import json
import math
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from agent.schema import ModelResponse


class ModelError(RuntimeError):
    """A provider, transport, or response-format failure."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward a credential to a different URL through a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _token_count(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ModelError(f"{field} must be a nonnegative integer")
    return value


def _validate_request(max_output_tokens: int, timeout_seconds: float) -> None:
    if not isinstance(max_output_tokens, int) or max_output_tokens < 1:
        raise ModelError("max_output_tokens must be positive")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ModelError("timeout_seconds must be positive and finite")


class ReplayClient:
    """Consume recorded responses in order; no network or model is needed.

    Each record is either a candidate's two fields, or a response containing
    text and optional input_tokens/output_tokens. Missing usage is estimated
    by the controller and marked in the saved trace.
    """

    provider = "replay"
    model = "replay"

    def __init__(self, path: str | Path):
        try:
            records = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ModelError("Cannot read replay JSON") from exc
        if not isinstance(records, list) or not records:
            raise ModelError("Replay must contain a nonempty JSON array")
        self._records: list[ModelResponse] = []
        for record in records:
            if not isinstance(record, dict):
                raise ModelError("Each replay record must be an object")
            if set(record) == {"implementation", "proof"}:
                if not all(isinstance(value, str) for value in record.values()):
                    raise ModelError("Replay candidate fields must be strings")
                response_text = json.dumps(record, ensure_ascii=False)
            else:
                response_text = record.get("text")
                if not isinstance(response_text, str):
                    raise ModelError("Replay response requires text")
            self._records.append(ModelResponse(
                text=response_text,
                input_tokens=_token_count(record.get("input_tokens", 0), "input_tokens"),
                output_tokens=_token_count(record.get("output_tokens", 0), "output_tokens"),
                model="replay",
            ))
        self._next = 0

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int,
                 timeout_seconds: float) -> ModelResponse:
        _validate_request(max_output_tokens, timeout_seconds)
        if self._next >= len(self._records):
            raise ModelError("Replay exhausted before the run finished")
        response = self._records[self._next]
        self._next += 1
        return response


class ChatCompletionsClient:
    """Generic HTTPS chat-completions REST adapter using urllib.

    A local HTTP endpoint is also allowed for local model servers. No provider
    error body or credential is included in exception text or run artifacts.
    """

    provider = "chat-completions"
    max_response_bytes = 4 * 1024 * 1024

    def __init__(self, model: str, base_url: str, api_key: str):
        if not model.strip():
            raise ModelError("A model name is required")
        parsed = urllib.parse.urlsplit(base_url)
        local_http = (parsed.scheme == "http" and
                      parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        if (parsed.scheme != "https" and not local_http) or not parsed.netloc:
            raise ModelError("Model endpoint requires HTTPS, or HTTP on localhost")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelError("Model endpoint must not contain credentials, query, or fragment")
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int,
                 timeout_seconds: float) -> ModelResponse:
        _validate_request(max_output_tokens, timeout_seconds)
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_output_tokens,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        request = urllib.request.Request(self._url, data=payload, headers=headers, method="POST")
        try:
            opener = urllib.request.build_opener(_NoRedirects())
            with opener.open(request, timeout=timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise ModelError(f"Model API returned HTTP {status}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError("Model API transport failed or timed out") from None
        if len(raw) > self.max_response_bytes:
            raise ModelError("Model API response exceeds 4 MiB")
        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            response_text = choice["message"]["content"]
            if not isinstance(response_text, str) or not response_text.strip():
                raise ValueError("empty content")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise ValueError("invalid usage")
            reported_model = data.get("model", self.model)
            if not isinstance(reported_model, str):
                raise ValueError("invalid model")
            return ModelResponse(
                text=response_text,
                input_tokens=_token_count(usage.get("prompt_tokens", 0), "prompt_tokens"),
                output_tokens=_token_count(usage.get("completion_tokens", 0), "completion_tokens"),
                model=reported_model,
            )
        except ModelError:
            raise
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("Model API returned an invalid chat-completions response") from None
