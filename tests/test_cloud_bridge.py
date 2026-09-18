import json
import unittest
from unittest.mock import patch

from keypilot.cloud_bridge import CloudModelBridge, chat_completions_url
from keypilot.secure_store import protect_text, unprotect_text


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": "云端回答"}}]}
        ).encode("utf-8")


class CloudBridgeTests(unittest.TestCase):
    def test_normalizes_openai_compatible_base_url(self) -> None:
        self.assertEqual(
            chat_completions_url("https://api.example.com/v1"),
            "https://api.example.com/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://api.example.com"),
            "https://api.example.com/v1/chat/completions",
        )

    def test_sends_bearer_key_and_returns_answer(self) -> None:
        bridge = CloudModelBridge()
        with patch("urllib.request.urlopen", return_value=_Response()) as opened:
            answer = bridge.answer(
                "问题",
                "",
                base_url="https://api.example.com/v1",
                model="model-name",
                api_key="top-secret",
            )
        request = opened.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.headers["Authorization"], "Bearer top-secret")
        self.assertEqual(payload["model"], "model-name")
        self.assertEqual(answer.text, "云端回答")

    def test_api_key_round_trips_through_windows_dpapi(self) -> None:
        encrypted = protect_text("test-api-key")
        self.assertNotIn(b"test-api-key", encrypted)
        self.assertEqual(unprotect_text(encrypted), "test-api-key")


if __name__ == "__main__":
    unittest.main()
