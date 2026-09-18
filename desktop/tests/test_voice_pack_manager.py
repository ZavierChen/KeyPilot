import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from keypilot.voice_pack_manager import (
    VoicePackError, _inside, _probe_runtime, create_voice_pack_template,
    import_voice_pack, validate_voice_pack, voice_pack_template,
)


class VoicePackManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.destination = self.root / "installed"
        self.source.mkdir()
        self.config = voice_pack_template("demo", "Demo voice")
        self.write_manifest()
        (self.source / "model" / "espeak-ng-data").mkdir(parents=True)
        for name in ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt", "lexicon.txt"):
            (self.source / "model" / name).write_bytes(b"test fixture, not a real model")
        (self.source / "model/espeak-ng-data/phontab").write_bytes(b"phoneme fixture")
        (self.source / "reference.wav").write_bytes(b"audio checked by runtime probe")
        (self.source / "vocos_24khz.onnx").write_bytes(b"vocoder fixture")
        self.runtime = {"python": sys.executable, "site_packages": str(self.root),
                        "runtime_versions": {"sherpa_onnx": "fixture"}}

    def write_manifest(self):
        (self.source / "voice.json").write_text(json.dumps(self.config), encoding="utf-8")

    def test_template_has_no_runtime_or_ready_claim_and_never_overwrites(self):
        manifest = create_voice_pack_template(self.root / "new")
        content = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertFalse(content["ready"])
        self.assertNotIn("python", content)
        with self.assertRaises(VoicePackError):
            create_voice_pack_template(self.root / "new")

    def test_files_only_validation_does_not_claim_model_loaded(self):
        self.config["ready"] = True
        self.write_manifest()
        report = validate_voice_pack(self.source)
        self.assertEqual(report["validation"], "files_only")
        self.assertFalse(report["ready"])

    def test_missing_asset_never_invokes_runtime(self):
        (self.source / "vocos_24khz.onnx").unlink()
        with patch("keypilot.voice_pack_manager._probe_runtime") as probe:
            with self.assertRaisesRegex(VoicePackError, "缺少"):
                import_voice_pack(self.source, python=Path(sys.executable), destination=self.destination)
            probe.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_import_copies_only_needed_assets_and_resolves_local_paths(self):
        (self.source / "consent-private.txt").write_text("not for redistribution")
        (self.source / "worker.log").write_text("private diagnostic")
        (self.source / "model" / "private.wav").write_bytes(b"unrelated recording")
        with patch("keypilot.voice_pack_manager._probe_runtime", return_value=self.runtime) as probe:
            manifest = import_voice_pack(self.source, python=Path(sys.executable), destination=self.destination)
        installed = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertTrue(installed["ready"])
        self.assertEqual(Path(installed["model"]), manifest.parent / "model")
        self.assertTrue(Path(installed["reference_audio"]).is_file())
        self.assertEqual(installed["python"], sys.executable)
        self.assertFalse((manifest.parent / "consent-private.txt").exists())
        self.assertFalse((manifest.parent / "worker.log").exists())
        self.assertFalse((manifest.parent / "model/private.wav").exists())
        self.assertFalse(json.loads((manifest.parent / "portable-voice.json").read_text(encoding="utf-8"))["ready"])
        self.assertEqual(probe.call_count, 1)
        self.assertFalse(Path(probe.call_args.args[1]["model"]).exists())  # staging was removed

    def test_duplicate_id_cannot_overwrite_existing_pack(self):
        (self.destination / "demo").mkdir(parents=True)
        sentinel = self.destination / "demo/voice.json"
        sentinel.write_text("do not modify")
        with patch("keypilot.voice_pack_manager._probe_runtime") as probe:
            with self.assertRaisesRegex(VoicePackError, "不会覆盖"):
                import_voice_pack(self.source, python=Path(sys.executable), destination=self.destination)
            probe.assert_not_called()
        self.assertEqual(sentinel.read_text(), "do not modify")

    def test_runtime_failure_cleans_staging_and_publishes_no_ready_pack(self):
        with patch("keypilot.voice_pack_manager._probe_runtime", side_effect=VoicePackError("bad weights")):
            with self.assertRaisesRegex(VoicePackError, "bad weights"):
                import_voice_pack(self.source, python=Path(sys.executable), destination=self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertFalse(json.loads((self.source / "voice.json").read_text())["ready"])

    def test_executable_and_unknown_manifest_fields_are_rejected(self):
        for field in ("python", "site_packages", "ffmpeg", "command", "quality_presets", "api_key"):
            with self.subTest(field=field):
                self.config[field] = "untrusted"
                self.write_manifest()
                with self.assertRaisesRegex(VoicePackError, "不接受"):
                    validate_voice_pack(self.source)
                self.config.pop(field)

    def test_parent_absolute_drive_and_ads_paths_are_rejected(self):
        for value in ("../outside.wav", "/outside.wav", "C:/outside.wav", "C:outside.wav",
                      "\\\\server\\share\\voice.wav", "voice.wav:payload", "model/../reference.wav", "aux.wav"):
            with self.subTest(value=value):
                self.config["reference_audio"] = value
                self.write_manifest()
                with self.assertRaises(VoicePackError):
                    validate_voice_pack(self.source)

    def test_symlink_asset_is_rejected(self):
        audio = self.source / "reference.wav"
        audio.unlink()
        outside = self.root / "outside.wav"
        outside.write_bytes(b"private")
        try:
            audio.symlink_to(outside)
        except OSError:
            self.skipTest("symbolic links unavailable on this Windows account")
        with self.assertRaisesRegex(VoicePackError, "符号链接"):
            validate_voice_pack(self.source)

    def test_windows_reparse_point_is_rejected_without_link_privileges(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info):
            with self.assertRaisesRegex(VoicePackError, "目录联接"):
                _inside(self.source.resolve(), Path("reference.wav"))

    def test_concurrent_same_id_import_does_not_overwrite(self):
        def raced_import(*args):
            folder = self.destination / "demo"
            folder.mkdir()
            (folder / "other-import.txt").write_text("keep")
            return self.runtime
        with patch("keypilot.voice_pack_manager._probe_runtime", side_effect=raced_import):
            with self.assertRaisesRegex(VoicePackError, "不会覆盖"):
                import_voice_pack(self.source, python=Path(sys.executable), destination=self.destination)
        self.assertEqual((self.destination / "demo/other-import.txt").read_text(), "keep")
        self.assertEqual([p.name for p in self.destination.iterdir()], ["demo"])

    def test_bad_types_and_unsupported_engine_are_rejected(self):
        for field, value in (("schema_version", True), ("num_steps", 0), ("num_threads", "2"),
                             ("ready", "true"), ("reference_text", ""), ("id", "../evil"),
                             ("engine", "qwen3-tts-zero-shot")):
            with self.subTest(field=field):
                old = self.config[field]
                self.config[field] = value
                self.write_manifest()
                with self.assertRaises(VoicePackError):
                    validate_voice_pack(self.source)
                self.config[field] = old

    def test_runtime_inside_pack_is_rejected_even_if_explicitly_selected(self):
        executable = self.source / "python.exe"
        executable.write_bytes(b"not a trusted runtime")
        with self.assertRaisesRegex(VoicePackError, "包以外"):
            import_voice_pack(self.source, python=executable, destination=self.destination)

    def test_probe_uses_isolated_python_fixed_code_and_json_input(self):
        response = subprocess.CompletedProcess([], 0, json.dumps(self.runtime), "")
        with patch("keypilot.voice_pack_manager.subprocess.run", return_value=response) as run:
            result = _probe_runtime(Path(sys.executable), {"reference_text": "$(untrusted)`text"}, self.source)
        args, kwargs = run.call_args
        self.assertEqual(args[0][1:3], ["-I", "-c"])
        self.assertEqual(json.loads(kwargs["input"])["reference_text"], "$(untrusted)`text")
        self.assertNotIn("shell", kwargs)
        self.assertNotEqual(Path(kwargs["cwd"]), self.source)
        self.assertEqual(result["runtime_versions"], self.runtime["runtime_versions"])


if __name__ == "__main__":
    unittest.main()
