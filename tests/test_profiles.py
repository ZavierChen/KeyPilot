from voice_assistant.voice_profiles import VoiceProfile, VoiceProfileStore


def test_profile_round_trip(tmp_path):
    store = VoiceProfileStore(tmp_path)
    saved = store.save(
        VoiceProfile(name="my_voice", speaker_id="S_example", consent_confirmed=True)
    )
    assert saved.exists()
    assert store.load("my_voice").speaker_id == "S_example"
    store.delete("my_voice")
    assert not saved.exists()
