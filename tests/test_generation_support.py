"""Supplied system regression tests; independent of Exercise 5 learner holes."""

from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from agent.acceptance import AcceptanceResult, AcceptanceStatus
from agent.generation import FlowError, OneShotSession, execute_one_shot
from agent.model_client import (MAX_RESPONSE_BYTES, OpenAIResponsesModel, Prompt,
                                ReplayModel, _NoRedirect, parse_response)
from agent.task import Task
from scripts.exercise05_review import find_live_evidence


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "exercises/05-one-shot-generation/fixtures"
PROMPT = Prompt("Return JSON bodies for a fixed Lean task.", "Trusted task goes here.")


def packet(name="valid"):
    return json.loads((FIXTURES / (name + ".json")).read_text())


class ProviderSupportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config_path = patch("agent.config.DEFAULT_ENV_PATH", Path(directory.name) / ".env")
        config_path.start()
        self.addCleanup(config_path.stop)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_extracts_assistant_text_and_preserves_provider_usage(self):
        response = packet()
        response["output"].insert(0, {"type": "reasoning", "text": "not the proposal"})
        response["usage"]["output_tokens_details"]["reasoning_tokens"] = 17
        reply = parse_response(response, provider="openai", requested_model="chosen", provider_requests=1)
        self.assertEqual(reply.status, "COMPLETED")
        self.assertEqual(reply.text, packet()["output"][0]["content"][0]["text"])
        self.assertEqual((reply.input_tokens, reply.output_tokens, reply.reasoning_tokens), (120, 95, 17))
        self.assertEqual(reply.usage_source, "provider")

    def test_zero_usage_is_not_replaced_with_unknown(self):
        response = packet()
        response["usage"] = {"input_tokens": 0, "output_tokens": 0}
        reply = parse_response(response, provider="openai", requested_model="chosen")
        self.assertEqual((reply.input_tokens, reply.output_tokens, reply.reasoning_tokens), (0, 0, None))

    def test_missing_invalid_usage_is_unknown(self):
        response = packet()
        response["usage"] = {"input_tokens": True, "output_tokens": -1}
        reply = parse_response(response, provider="openai", requested_model="chosen")
        self.assertIsNone(reply.input_tokens)
        self.assertIsNone(reply.output_tokens)
        self.assertEqual(reply.usage_source, "unavailable")

    def test_refusal_incomplete_error_and_empty_outputs_are_distinct(self):
        for name, expected in (("refusal", "MODEL_REFUSED"), ("incomplete", "MODEL_INCOMPLETE"),
                               ("provider_error", "MODEL_ERROR")):
            with self.subTest(name=name):
                self.assertEqual(ReplayModel(FIXTURES / (name + ".json")).generate(PROMPT).status, expected)
        for value in ([], {"status": "completed"}, {"status": "completed", "output": []}):
            self.assertEqual(parse_response(value, provider="openai", requested_model="chosen").status,
                             "MODEL_ERROR")

    def test_replay_has_no_network_and_labels_synthetic_usage(self):
        with patch("agent.model_client.request.build_opener", side_effect=AssertionError("network")):
            reply = ReplayModel(FIXTURES / "valid.json").generate(PROMPT)
        self.assertEqual(reply.status, "COMPLETED")
        self.assertEqual(reply.provider_requests, 0)
        self.assertEqual(reply.usage_source, "fixture")

    def test_missing_or_oversized_replay_is_a_model_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "response.json"
            self.assertEqual(ReplayModel(path).generate(PROMPT).status, "MODEL_ERROR")
            path.write_bytes(b" " * (MAX_RESPONSE_BYTES + 1))
            self.assertEqual(ReplayModel(path).generate(PROMPT).status, "MODEL_ERROR")

    def test_missing_key_sends_no_request(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), patch("agent.model_client.request.build_opener") as opener:
            reply = OpenAIResponsesModel("explicit-model").generate(PROMPT)
        opener.assert_not_called()
        self.assertEqual(reply.status, "MODEL_ERROR")
        self.assertEqual(reply.provider_requests, 0)

    def test_request_uses_explicit_model_schema_and_no_retries(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(packet()).encode())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), \
                patch("agent.model_client.request.build_opener", return_value=opener):
            reply = OpenAIResponsesModel("explicit-model", max_output_tokens=4000).generate(PROMPT)
        self.assertEqual(reply.status, "COMPLETED")
        opener.open.assert_called_once()
        req = opener.open.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(body["model"], "explicit-model")
        self.assertEqual(body["max_output_tokens"], 4000)
        self.assertEqual(body["input"][0]["content"], PROMPT.system)
        self.assertEqual(body["input"][1]["content"], PROMPT.user)
        self.assertFalse(body["store"])
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertFalse(body["text"]["format"]["schema"]["additionalProperties"])
        self.assertNotIn("test-secret", json.dumps(asdict(reply)))

    def test_http_transport_and_bad_json_failures_do_not_retry_or_echo_credentials(self):
        for failure in (HTTPError("https://api.openai.com", 401, "bad", {}, io.BytesIO(b"test-secret")),
                        URLError("test-secret"), TimeoutError("test-secret")):
            with self.subTest(failure=type(failure).__name__):
                opener = Mock()
                opener.open.side_effect = failure
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), \
                        patch("agent.model_client.request.build_opener", return_value=opener):
                    reply = OpenAIResponsesModel("explicit-model").generate(PROMPT)
                opener.open.assert_called_once()
                self.assertEqual(reply.status, "MODEL_ERROR")
                self.assertIsNone(reply.input_tokens)
                self.assertNotIn("test-secret", json.dumps(asdict(reply)))
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"not JSON")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), \
                patch("agent.model_client.request.build_opener", return_value=opener):
            self.assertEqual(OpenAIResponsesModel("explicit-model").generate(PROMPT).status, "MODEL_ERROR")

    def test_response_bytes_are_bounded(self):
        opener = Mock()
        stream = io.BytesIO(b" " * (MAX_RESPONSE_BYTES + 20))
        opener.open.return_value = stream
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), \
                patch("agent.model_client.request.build_opener", return_value=opener):
            reply = OpenAIResponsesModel("explicit-model").generate(PROMPT)
        self.assertEqual(reply.status, "MODEL_ERROR")
        self.assertIn("byte limit", reply.error)

    def test_redirects_never_forward_credentials(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid"))

    def test_configuration_requires_explicit_model_and_valid_limits(self):
        for kwargs in ({"model": ""}, {"model": None}, {"model": "chosen", "max_output_tokens": 0},
                       {"model": "chosen", "max_output_tokens": True},
                       {"model": "chosen", "timeout_seconds": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                OpenAIResponsesModel(**kwargs)


class SessionSupportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.task = Task.load(ROOT, "checked_subtraction")
        self.session = OneShotSession(ROOT, self.task, ReplayModel(FIXTURES / "valid.json"), self.work)

    def test_cannot_parse_or_check_before_generation(self):
        with self.assertRaises(FlowError):
            self.session.parse("{}")
        with self.assertRaises(FlowError):
            self.session.check("candidate")

    def test_cannot_generate_twice_or_replace_reply(self):
        reply = self.session.generate(PROMPT)
        with self.assertRaises(FlowError):
            self.session.generate(PROMPT)
        with self.assertRaises(FlowError):
            self.session.parse(reply.text + " ")

    def test_cannot_replace_proposal_or_rendered_source(self):
        reply = self.session.generate(PROMPT)
        proposal = self.session.parse(reply.text)
        with self.assertRaises(FlowError):
            self.session.render(None)
        source = self.session.render(proposal)
        with self.assertRaises(FlowError):
            self.session.check(source + "\n")

    def test_model_error_record_is_retained_without_checking(self):
        def flow(view, session):
            session.generate(PROMPT)
        result = execute_one_shot(ROOT, ReplayModel(FIXTURES / "refusal.json"),
                                  flow=flow, artifact_root=self.work)
        report = json.loads(result.report_path.read_text())
        self.assertEqual(result.status, "MODEL_REFUSED")
        self.assertEqual(report["acceptance_checks"], 0)
        self.assertTrue((result.report_path.parent / "model.json").is_file())

    def test_invalid_proposal_retains_raw_text(self):
        def flow(view, session):
            reply = session.generate(PROMPT)
            session.parse(reply.text)
        result = execute_one_shot(ROOT, ReplayModel(FIXTURES / "malformed.json"),
                                  flow=flow, artifact_root=self.work)
        self.assertEqual(result.status, "INVALID_PROPOSAL")
        self.assertIn("```", (result.report_path.parent / "response.txt").read_text())

    def test_cannot_return_a_claimed_verdict_without_checking(self):
        result = execute_one_shot(ROOT, ReplayModel(FIXTURES / "valid.json"),
                                  flow=lambda view, session: "VERIFIED", artifact_root=self.work)
        self.assertEqual(result.status, "CONTROLLER_ERROR")

    def test_missing_image_is_infrastructure_failure_without_host_fallback(self):
        def flow(view, session):
            reply = session.generate(PROMPT)
            source = session.render(session.parse(reply.text))
            return session.check(source)
        with patch("agent.generation.AcceptanceImage.load", side_effect=ValueError("missing")), \
                patch("agent.generation.AcceptanceRunner") as runner:
            result = execute_one_shot(ROOT, ReplayModel(FIXTURES / "valid.json"),
                                      flow=flow, artifact_root=self.work)
        self.assertEqual(result.status, "INFRASTRUCTURE_ERROR")
        runner.assert_not_called()

    def test_check_verdict_and_diagnostics_are_retained(self):
        def flow(view, session):
            reply = session.generate(PROMPT)
            return session.check(session.render(session.parse(reply.text)))
        checker = Mock()
        def check(task, source, *, artifact_root):
            artifact_root.mkdir()
            report = artifact_root / "result.json"
            report.write_text('{"status":"ELABORATION_FAILED","diagnostics":"unsolved goals"}')
            return AcceptanceResult(AcceptanceStatus.ELABORATION_FAILED, report, artifact_root)
        checker.check.side_effect = check
        result = execute_one_shot(ROOT, ReplayModel(FIXTURES / "valid.json"),
                                  flow=flow, artifact_root=self.work, checker=checker)
        self.assertEqual(result.status, "ELABORATION_FAILED")
        report = json.loads(result.report_path.read_text())
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["acceptance_checks"], 1)
        self.assertIn("unsolved goals", Path(report["acceptance_report"]).read_text())

    def test_missing_live_evidence_does_not_trigger_an_api_call(self):
        with patch("agent.model_client.request.build_opener", side_effect=AssertionError("network")):
            self.assertIsInstance(find_live_evidence(ROOT), list)


if __name__ == "__main__":
    unittest.main()
