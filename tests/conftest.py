"""Never point research tests at the current user's application data."""
import pytest


@pytest.fixture(autouse=True)
def isolated_voice_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYPILOT_DATA_DIR", str(tmp_path / "user-data"))
