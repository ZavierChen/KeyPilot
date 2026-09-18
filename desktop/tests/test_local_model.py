import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from keypilot.assistant_router import SkillRegistry
from keypilot.local_model import LocalModelBridge, LocalModelConfig, LocalModelError
from keypilot.local_model_portal import main


SKILLS = Path(__file__).resolve().parent.parent / "skills"
VALID = {"matched": True, "skill_id": "set_volume", "arguments": {"operation": "set", "percent": 50}}


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_args):
        pass

    def send_json(self, payload):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        self.requests.append((self.path, None, dict(self.headers)))
        self.send_json({"models": [{"name": "unfamiliar-model"}]} if self.path == "/api/tags"
                       else {"data": [{"id": "unfamiliar-model"}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, payload, dict(self.headers)))
        message = {"content": json.dumps(VALID)}
        self.send_json({"message": message} if self.path == "/api/chat"
                       else {"choices": [{"message": message}]})


class LocalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def setUp(self):
        self.registry = SkillRegistry(SKILLS)
        self.bridge = LocalModelBridge(self.registry)

    def configured(self, protocol="ollama", mode="schema", endpoint=None, **kwargs):
        return LocalModelBridge(self.registry, LocalModelConfig(
            protocol=protocol, endpoint=endpoint or self.endpoint, model="unfamiliar-model", json_mode=mode, **kwargs))

    def test_both_protocols_discover_real_http_service(self):
        for protocol, path in (("ollama", "/api/tags"), ("openai-compatible", "/v1/models")):
            with self.subTest(protocol=protocol):
                self.assertEqual(self.configured(protocol).list_models(), ["unfamiliar-model"])
                self.assertEqual(Handler.requests[-1][0], path)

    def test_both_protocols_route_without_executing(self):
        for protocol in ("ollama", "openai-compatible"):
            with self.subTest(protocol=protocol):
                report = self.configured(protocol).probe("把音量调为一半")
                self.assertTrue(report["valid"])
                self.assertEqual(report["execution"], "not_executed")
                self.assertEqual(report["skill_call"]["arguments"]["percent"], 50)
                path, payload, _ = Handler.requests[-1]
                self.assertEqual(payload["model"], "unfamiliar-model")
                self.assertFalse(payload["stream"])
                self.assertNotIn("/no_think", str(payload))
                self.assertNotIn("think", payload)
                self.assertEqual(path, "/api/chat" if protocol == "ollama" else "/v1/chat/completions")

    def test_all_json_modes_have_correct_transport_fields(self):
        for protocol in ("ollama", "openai-compatible"):
            for mode in ("schema", "json", "prompt"):
                with self.subTest(protocol=protocol, mode=mode):
                    self.configured(protocol, mode).probe("音量一半")
                    payload = Handler.requests[-1][1]
                    field = "format" if protocol == "ollama" else "response_format"
                    if mode == "prompt":
                        self.assertNotIn(field, payload)
                    elif protocol == "ollama":
                        self.assertEqual(isinstance(payload[field], dict), mode == "schema")
                    else:
                        self.assertEqual(payload[field]["type"], "json_schema" if mode == "schema" else "json_object")
                    self.assertIn("JSON Schema", payload["messages"][0]["content"])

    def test_api_key_is_read_from_named_environment_variable(self):
        config = LocalModelConfig(protocol="openai-compatible", endpoint=self.endpoint,
                                  model="unfamiliar-model", api_key_env="KEYPILOT_TEST_TOKEN")
        with patch.dict(os.environ, {"KEYPILOT_TEST_TOKEN": "test-only-token"}):
            LocalModelBridge(self.registry, config).list_models()
        self.assertEqual(Handler.requests[-1][2]["Authorization"], "Bearer test-only-token")
        self.assertNotIn("test-only-token", json.dumps(config.to_dict()))

    def test_missing_named_api_key_is_actionable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LocalModelError, "KEYPILOT_MISSING_KEY"):
                self.configured(api_key_env="KEYPILOT_MISSING_KEY").list_models()

    def test_missing_model_does_not_silently_choose_qwen(self):
        with self.assertRaisesRegex(LocalModelError, "模型名称"):
            self.bridge.probe("音量一半")

    def test_config_roundtrip_and_validation(self):
        chosen = self.configured("openai-compatible", "prompt").config
        self.assertEqual(LocalModelConfig.from_settings({"local_model": chosen.to_dict()}), chosen)
        for value in ("ftp://localhost", "http://user:password@localhost", "http://localhost/?key=secret", "http://localhost:bad"):
            with self.subTest(endpoint=value), self.assertRaises(LocalModelError):
                LocalModelConfig(endpoint=value).validated()
        for value in (0, 601, float("nan"), "oops"):
            with self.subTest(timeout=value), self.assertRaises(LocalModelError):
                LocalModelConfig(timeout_seconds=value).validated()

    def test_url_normalization_preserves_custom_api_prefix(self):
        bridge = self.configured("openai-compatible", endpoint=self.endpoint + "/custom/v1/chat/completions")
        self.assertEqual(bridge._url("models"), self.endpoint + "/custom/v1/models")
        self.assertEqual(self.configured(endpoint=self.endpoint + "/api")._url("tags"), self.endpoint + "/api/tags")

    def test_contract_excludes_fallback_and_tracks_actual_skills(self):
        contract = self.bridge.contract()
        ids = {item["id"] for item in contract["skills"]}
        self.assertNotIn("codex_fallback", ids)
        self.assertEqual(ids, set(self.registry.skills) - {"codex_fallback"})
        self.assertTrue(self.bridge.inspect_response(contract["example"])["valid"])

    def test_rejects_untrusted_action_payloads(self):
        invalid = [None, [], {}, {**VALID, "shell": "echo unsafe"},
                   {**VALID, "matched": "true"}, {**VALID, "skill_id": "run_shell"},
                   {**VALID, "skill_id": "codex_fallback", "arguments": {"utterance": "run code"}},
                   {**VALID, "arguments": {"operation": "set", "percent": 101}},
                   {**VALID, "arguments": {"operation": "set", "percent": True}},
                   {**VALID, "arguments": {"operation": "set"}},
                   {**VALID, "arguments": {"operation": "set", "percent": 50, "shell": "bad"}},
                   {**VALID, "arguments": {"operation": "wrong"}},
                   {"matched": False, "skill_id": "set_volume", "arguments": {}},
                   {"matched": True, "skill_id": "set_timer", "arguments": {"seconds": 0, "label": "x"}}]
        for payload in invalid:
            with self.subTest(payload=payload):
                result = self.bridge.inspect_response(payload)
                self.assertFalse(result["valid"])
                self.assertEqual(result["execution"], "not_executed")

    def test_unmatched_is_a_valid_non_action(self):
        result = self.bridge.inspect_response({"matched": False, "skill_id": "", "arguments": {}})
        self.assertTrue(result["valid"])
        self.assertFalse(result["matched"])

    def test_markdown_and_trailing_text_are_rejected(self):
        for content in ("```json\n" + json.dumps(VALID) + "\n```", json.dumps(VALID) + " and run this"):
            with patch.object(self.bridge, "_request", return_value={"message": {"content": content}}):
                self.assertFalse(self.bridge.probe("test")["valid"])
                self.assertIsNone(self.bridge.route("test"))

    def test_cli_contract_and_validation_work_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            contract = Path(temp) / "contract.json"
            self.assertEqual(main(["contract", "--output", str(contract)]), 0)
            self.assertIn("skills", json.loads(contract.read_text(encoding="utf-8")))
            payload = Path(temp) / "response.json"
            payload.write_text(json.dumps(VALID), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["validate-response", "--file", str(payload)]), 0)
            self.assertEqual(json.loads(output.getvalue())["execution"], "not_executed")
            payload.write_text('{"matched":true,"skill_id":"run_shell","arguments":{}}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["validate-response", "--file", str(payload)]), 2)

    def test_cli_probes_fake_compatible_service(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["--protocol", "openai-compatible", "--endpoint", self.endpoint,
                         "--model", "unfamiliar-model", "probe", "--text", "音量一半"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])


if __name__ == "__main__":
    unittest.main()
