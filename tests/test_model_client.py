from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from agent.model_client import ChatCompletionsClient, ModelError, ReplayClient, _NoRedirects


class ModelClientTests(unittest.TestCase):
    def test_replay_supports_candidates_and_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_text(json.dumps([
                {"implementation": "n", "proof": "by rfl"},
                {"text": "plan", "input_tokens": 3, "output_tokens": 4},
            ]))
            client = ReplayClient(path)
            first = client.complete([], 50, 2)
            self.assertEqual(json.loads(first.text)["implementation"], "n")
            second = client.complete([], 50, 2)
            self.assertEqual((second.text, second.input_tokens, second.output_tokens), ("plan", 3, 4))
            with self.assertRaisesRegex(ModelError, "exhausted"):
                client.complete([], 50, 2)

    def test_replay_rejects_bad_token_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_text('[{"text": "x", "input_tokens": -1}]')
            with self.assertRaises(ModelError):
                ReplayClient(path)

    def test_https_or_local_http_only(self):
        for url in ["http://provider.example/v1", "ftp://provider.example", "https://user:secret@example.com/v1"]:
            with self.assertRaises(ModelError):
                ChatCompletionsClient("model", url, "secret")
        ChatCompletionsClient("model", "http://localhost:8000/v1", "")

    def test_api_request_and_usage(self):
        body = {"model": "resolved-model", "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = BytesIO(json.dumps(body).encode())
        with patch("agent.model_client.urllib.request.build_opener", return_value=opener):
            result = ChatCompletionsClient("model", "https://example.com/v1", "secret").complete(
                [{"role": "user", "content": "hello"}], 17, 3.5)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.com/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["max_tokens"], 17)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 3.5)
        self.assertEqual((result.input_tokens, result.output_tokens, result.model), (10, 5, "resolved-model"))

    def test_api_error_does_not_expose_body_or_secret(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError("https://example.com", 401, "secret", {}, BytesIO(b"secret"))
        with patch("agent.model_client.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(ModelError, "HTTP 401") as captured:
                ChatCompletionsClient("model", "https://example.com", "secret").complete([], 10, 1)
        self.assertNotIn("secret", str(captured.exception))

    def test_invalid_and_oversized_response(self):
        client = ChatCompletionsClient("model", "https://example.com", "")
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = BytesIO(b"not JSON")
        with patch("agent.model_client.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(ModelError, "invalid"):
                client.complete([], 10, 1)
        client.max_response_bytes = 4
        opener.open.return_value.__enter__.return_value = BytesIO(b"12345")
        with patch("agent.model_client.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(ModelError, "exceeds"):
                client.complete([], 10, 1)

    def test_truncated_response_keeps_text_and_usage_for_repair(self):
        body = {"choices": [{"message": {"content": '{"implementation":'}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 10}}
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = BytesIO(json.dumps(body).encode())
        with patch("agent.model_client.urllib.request.build_opener", return_value=opener):
            result = ChatCompletionsClient("model", "https://example.com", "").complete([], 10, 1)
        self.assertEqual((result.text, result.input_tokens, result.output_tokens), ('{"implementation":', 7, 10))

    def test_redirects_are_rejected_before_credential_forwarding(self):
        request = urllib.request.Request("https://example.com/v1", headers={"Authorization": "Bearer secret"})
        handler = _NoRedirects()
        self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example"))

    def test_positive_finite_limits_required(self):
        client = ChatCompletionsClient("model", "https://example.com", "")
        for max_tokens, seconds in [(0, 1), (1, 0), (1, float("inf")), (1, float("nan"))]:
            with self.assertRaises(ModelError):
                client.complete([], max_tokens, seconds)


if __name__ == "__main__":
    unittest.main()
