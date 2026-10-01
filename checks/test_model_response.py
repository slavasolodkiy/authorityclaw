import io
import json
import os
import unittest
from unittest.mock import patch

from authorityclaw import extract as ex


class ModelResponseChecks(unittest.TestCase):
    def test_request_disables_thinking_and_bounds_tokens(self):
        reply = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
        with patch.object(ex.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(reply).encode())) as call:
            ex.call_llm([], ("http://example.invalid/v1", "demo-model", ""))
        request = json.loads(call.call_args.args[0].data)
        self.assertEqual(request["max_tokens"], 128)
        self.assertEqual(request["reasoning_effort"], "none")
        self.assertIs(request["chat_template_kwargs"]["enable_thinking"], False)

    def test_truncated_response_cannot_be_labeled_model_read(self):
        reply = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        with patch.object(ex.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(reply).encode())):
            with self.assertRaises(ValueError):
                ex.call_llm([], ("http://example.invalid/v1", "demo-model", ""))

    def test_invalid_output_is_explicitly_a_rules_fallback(self):
        for output in ("", "No invoice found", "{}", '{"payee":"Example"}'):
            with self.subTest(output=output), patch.dict(os.environ, {
                "AUTHORITYCLAW_LLM_URL": "http://example.invalid/v1", "AUTHORITYCLAW_LLM_MODEL": "demo-model"
            }), patch.object(ex, "call_llm", return_value=output):
                fields = ex.extract("Pay to: Example\nAmount due: 10\n")
                self.assertEqual(fields["_engine"], "rules (model unavailable: ValueError)")


if __name__ == "__main__":
    unittest.main()
