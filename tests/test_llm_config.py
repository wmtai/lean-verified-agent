"""Configuration integration checks use temporary files and mocked HTTP only."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent.config import LLMConfig, read_dotenv
from agent.model_client import OpenAIResponsesModel, Prompt, ReplayModel


ROOT = Path(__file__).resolve().parents[1]


class LLMConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env_file = Path(directory.name) / ".env"
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_file_settings_override_exported_values_and_do_not_mutate_environment(self):
        self.env_file.write_text('LLM_API_URL=https://gateway.example/v1/responses\n'
                                 'LLM_API_KEY="file-secret"\nLLM_MODEL=file-model\n')
        with patch.dict(os.environ, {"OPENAI_API_KEY": "old-secret", "LLM_MODEL": "old-model"}):
            config = LLMConfig.load(self.env_file)
            self.assertEqual(config.api_key, "file-secret")
            self.assertEqual(config.model, "file-model")
            self.assertEqual(config.api_url, "https://gateway.example/v1/responses")
            self.assertEqual(os.environ["OPENAI_API_KEY"], "old-secret")
            self.assertNotIn("LLM_API_KEY", os.environ)
        self.assertNotIn("file-secret", repr(config))

    def test_comments_quotes_and_shell_syntax_stay_literal(self):
        self.env_file.write_text('# comment\nexport LLM_MODEL="model name" # comment\n'
                                 "LLM_API_KEY='$(do-not-run)${SECRET}#literal'\n"
                                 'LLM_API_URL=http://localhost:9000/v1/responses # local\n')
        config = LLMConfig.load(self.env_file)
        self.assertEqual(config.model, "model name")
        self.assertEqual(config.api_key, "$(do-not-run)${SECRET}#literal")
        self.assertEqual(config.api_url, "http://localhost:9000/v1/responses")

    def test_blank_file_key_does_not_fall_back_to_old_export(self):
        self.env_file.write_text('LLM_API_KEY=""\n')
        with patch.dict(os.environ, {"OPENAI_API_KEY": "old-secret"}):
            self.assertEqual(LLMConfig.load(self.env_file).api_key, "")

    def test_missing_file_preserves_environment_compatibility(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-secret", "OPENAI_MODEL": "legacy-model"}):
            config = LLMConfig.load(self.env_file)
        self.assertEqual(config.api_key, "legacy-secret")
        self.assertEqual(config.model, "legacy-model")

    def test_invalid_lines_do_not_echo_secret_values(self):
        for text in ('not an assignment private-secret', 'LLM_API_KEY="private-secret'):
            with self.subTest(text=text):
                self.env_file.write_text(text)
                with self.assertRaises(ValueError) as error:
                    read_dotenv(self.env_file)
                self.assertNotIn("private-secret", str(error.exception))

    def test_endpoint_must_be_http_without_embedded_credentials(self):
        for url in ('file:///tmp/data', 'https://secret@example.com/responses',
                    'https://example.com/responses?api_key=secret', 'not a url'):
            with self.subTest(url=url):
                self.env_file.write_text('LLM_API_URL=' + url + '\n')
                with self.assertRaises(ValueError):
                    LLMConfig.load(self.env_file)

    def test_live_adapter_loads_url_key_and_model_from_file(self):
        self.env_file.write_text('LLM_API_URL=https://gateway.example/v1/responses\n'
                                 'LLM_API_KEY=file-secret\nLLM_MODEL=file-model\n')
        response = json.loads((ROOT / 'exercises/05-one-shot-generation/fixtures/valid.json').read_text())
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(response).encode())
        with patch('agent.config.DEFAULT_ENV_PATH', self.env_file), \
                patch('agent.model_client.request.build_opener', return_value=opener):
            model = OpenAIResponsesModel()
            reply = model.generate(Prompt('System instruction', 'Public task'))
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://gateway.example/v1/responses')
        self.assertEqual(req.get_header('Authorization'), 'Bearer file-secret')
        self.assertEqual(json.loads(req.data)['model'], 'file-model')
        self.assertEqual(reply.status, 'COMPLETED')
        self.assertNotIn('file-secret', repr(reply))

    def test_explicit_model_override_keeps_file_endpoint_and_key(self):
        self.env_file.write_text('LLM_MODEL=file-model\nLLM_API_KEY=file-secret\n')
        model = OpenAIResponsesModel('override-model', env_file=self.env_file)
        self.assertEqual(model.model, 'override-model')

    def test_replay_does_not_read_dotenv(self):
        with patch('agent.config.read_dotenv', side_effect=AssertionError('should not read credentials')):
            reply = ReplayModel(ROOT / 'exercises/05-one-shot-generation/fixtures/valid.json').generate(
                Prompt('System instruction', 'Public task'))
        self.assertEqual(reply.status, 'COMPLETED')


if __name__ == '__main__':
    unittest.main()
