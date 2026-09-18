import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from keypilot.custom_voice import speech_chunk_limit
from keypilot.reply_length import speech_chunks
from keypilot.rvc_voice import conversion_options
from keypilot.speech import SpeechEngine, DEFAULT_VOICE
from keypilot.voice_cache import audio_cache_path


class RvcVoiceTests(unittest.TestCase):
    def test_accepted_pronunciation_options_and_validation(self):
        self.assertEqual(conversion_options({}), (.25, .1, .5))
        for key, value in [('index_rate', 1.1), ('protect', .6),
                           ('rms_mix_rate', -1), ('protect', float('nan'))]:
            with self.assertRaises(ValueError):
                conversion_options({key: value})

    def test_cache_needs_no_reference_and_changes_with_voice_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, index = root / 'sister.pth', root / 'sister.index'
            model.write_bytes(b'model')
            index.write_bytes(b'index')
            config = dict(engine='edge-rvc', model=str(model), index=str(index),
                          index_rate=.25, protect=.1, source_voice='voice-a')
            pack = root / 'voice.json'
            original = audio_cache_path(pack, config, '测试')
            self.assertEqual(original, audio_cache_path(pack, config, '测试'))
            for key, value in [('index_rate', .6), ('protect', .33),
                               ('source_voice', 'voice-b'), ('speech_rate', .95), ('loudness_lufs', -16)]:
                self.assertNotEqual(original, audio_cache_path(pack, {**config, key: value}, '测试'))
            model.write_bytes(b'new-model')
            self.assertNotEqual(original, audio_cache_path(pack, config, '测试'))

    def test_short_chunks_preserve_long_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / 'voice.json'
            pack.write_text(json.dumps({'engine': 'edge-rvc'}))
            self.assertEqual(speech_chunk_limit(pack), 60)
            text = '喝点水，慢慢来就好。' * 40
            chunks = speech_chunks(text, speech_chunk_limit(pack))
            self.assertEqual(''.join(chunks), text)
            self.assertLessEqual(max(map(len, chunks)), 60)
            self.assertEqual(speech_chunk_limit(None), 180)
            self.assertEqual(speech_chunk_limit(Path('missing-voice.json')), 180)

    def test_online_pack_failure_goes_offline_without_second_network_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / 'voice.json'
            pack.write_text(json.dumps({'engine': 'edge-rvc'}))
            engine = SpeechEngine(Path('.'), enabled=False)
            engine._local_voice.synthesize = Mock(side_effect=RuntimeError('network'))
            engine._speak_offline = Mock()
            engine._speak_edge = Mock()
            engine.on_voice_error = Mock()
            engine._speak_part('测试', DEFAULT_VOICE, 0, pack)
            engine._speak_offline.assert_called_once_with('测试', 'Huihui', 0, 1)
            engine._speak_edge.assert_not_called()
            engine.on_voice_error.assert_called_once()

    def test_cancelled_pack_failure_does_not_start_fallback_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / 'voice.json'
            pack.write_text(json.dumps({'engine': 'edge-rvc'}))
            engine = SpeechEngine(Path('.'), enabled=False)
            engine._local_voice.synthesize = Mock(side_effect=RuntimeError('cancelled'))
            engine._speak_offline = Mock()
            engine._generation = 1
            engine._speak_part('旧回答', DEFAULT_VOICE, 0, pack)
            engine._speak_offline.assert_not_called()

    def test_loudness_disabled_leaves_old_voices_unchanged(self):
        from keypilot.voice_tone import normalize_voice_loudness
        with patch('keypilot.voice_tone.subprocess.run') as run:
            normalize_voice_loudness(Path('unused.wav'), {})
        run.assert_not_called()

    def test_loudness_rejects_unsafe_or_invalid_targets(self):
        from keypilot.voice_tone import normalize_voice_loudness
        for value in (-40, 0, -10, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                normalize_voice_loudness(Path('unused.wav'), {'loudness_lufs': value})

    def test_loudness_has_peak_limit_and_atomic_output(self):
        from keypilot.voice_tone import normalize_voice_loudness
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / 'ffmpeg.exe'
            executable.touch()
            wav = root / 'voice.wav'
            wav.write_bytes(b'old')
            def fake_run(args, **kwargs):
                self.assertIn('loudnorm=I=-16:TP=-1.5:LRA=11', args)
                self.assertEqual(kwargs['timeout'], 15)
                Path(args[-1]).write_bytes(b'normalized')
            with patch('keypilot.voice_tone.subprocess.run', side_effect=fake_run):
                normalize_voice_loudness(wav, {'ffmpeg': str(executable), 'loudness_lufs': -16})
            self.assertEqual(wav.read_bytes(), b'normalized')
            self.assertFalse(wav.with_suffix('.loud.wav').exists())


if __name__ == '__main__':
    unittest.main()
