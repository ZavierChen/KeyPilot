import json
import unittest
from pathlib import Path
from unittest.mock import patch

from keypilot.assistant_router import SkillRegistry
from keypilot.ollama_bridge import OllamaBridge


PROJECT_DIR = Path(__file__).resolve().parent.parent


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


class OllamaBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry(PROJECT_DIR / "skills")
        self.bridge = OllamaBridge(self.registry)

    def _mock_response(self, result: dict) -> _Response:
        return _Response({"message": {"content": json.dumps(result, ensure_ascii=False)}})

    def test_accepts_valid_known_skill_call(self) -> None:
        result = {
            "matched": True,
            "skill_id": "set_volume",
            "arguments": {"operation": "set", "percent": 50},
            "spoken_response": "音量已调到一半。",
            "confidence": 0.95,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            call = self.bridge.route("声音别那么大，放一半就行")
        self.assertEqual(call.skill_id, "set_volume")
        self.assertEqual(call.arguments["percent"], 50)

    def test_model_is_only_kept_warm_for_a_short_command_burst(self) -> None:
        result = {"matched": False, "skill_id": "", "arguments": {}}
        with patch(
            "urllib.request.urlopen", return_value=self._mock_response(result)
        ) as mocked_open:
            self.bridge.route("解释量子纠缠")

        request = mocked_open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["keep_alive"], "45s")

    def test_rejects_hallucinated_argument(self) -> None:
        result = {
            "matched": True,
            "skill_id": "set_volume",
            "arguments": {"operation": "set", "percent": 50, "shell": "danger"},
            "spoken_response": "好了。",
            "confidence": 0.99,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            self.assertIsNone(self.bridge.route("音量一半"))

    def test_rejects_out_of_range_value(self) -> None:
        result = {
            "matched": True,
            "skill_id": "set_volume",
            "arguments": {"operation": "set", "percent": 500},
            "spoken_response": "好了。",
            "confidence": 0.99,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            self.assertIsNone(self.bridge.route("音量设成五百"))

    def test_rejects_unknown_or_low_confidence(self) -> None:
        result = {
            "matched": False,
            "skill_id": "",
            "arguments": {},
            "spoken_response": "",
            "confidence": 0.2,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            self.assertIsNone(self.bridge.route("解释量子纠缠"))

    def test_answers_simple_question_locally(self) -> None:
        result = {
            "answerable": True,
            "recommend_cloud": False,
            "answer": "天空呈蓝色主要是因为瑞利散射。",
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            answer = self.bridge.answer("为什么天空是蓝色的")
        self.assertEqual(answer.text, "天空呈蓝色主要是因为瑞利散射。")
        self.assertFalse(answer.recommend_cloud)

    def test_keeps_local_draft_when_cloud_is_recommended(self) -> None:
        result = {
            "answerable": True,
            "recommend_cloud": True,
            "answer": "这是本地模型准备的回答。",
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            answer = self.bridge.answer("比较两个复杂方案")
        self.assertTrue(answer.recommend_cloud)
        self.assertIn("本地模型", answer.text)

    def test_declines_live_information(self) -> None:
        result = {"answerable": False, "recommend_cloud": True, "answer": ""}
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            self.assertIsNone(self.bridge.answer("今天的新闻是什么"))

    def test_answers_from_untrusted_browser_context(self) -> None:
        result = {"answer": "网页中的主要结论是测试通过。"}
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            answer = self.bridge.answer_with_context("结论是什么", "AI 概览：测试通过")
        self.assertIn("测试通过", answer.text)

    def test_selects_candidate_for_speech_recognition_error(self) -> None:
        result = {"selected": "微信"}
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            selected = self.bridge.choose_candidate("威信", ["微信", "Steam"])
        self.assertEqual(selected, "微信")

    def test_resolves_app_abbreviation_before_giving_up(self) -> None:
        result = {
            "canonical_name": "Counter-Strike 2",
            "selected": "Counter-Strike 2",
        }
        candidates = ["Counter-Strike 2", "Steam"]
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            canonical, selected = self.bridge.resolve_app_identity("CS2", candidates)
        self.assertEqual(canonical, "Counter-Strike 2")
        self.assertEqual(selected, "Counter-Strike 2")

    def test_uses_search_context_to_map_localized_game_name(self) -> None:
        result = {
            "canonical_name": "Dead by Daylight",
            "selected": "Dead by Daylight",
        }
        with patch("urllib.request.urlopen", return_value=self._mock_response(result)):
            canonical, selected = self.bridge.resolve_app_identity(
                "黎明杀机",
                ["Dead by Daylight", "Steam"],
                "搜索结果显示：《黎明杀机》的英文名称是 Dead by Daylight。",
            )
        self.assertEqual(canonical, "Dead by Daylight")
        self.assertEqual(selected, "Dead by Daylight")


if __name__ == "__main__":
    unittest.main()
