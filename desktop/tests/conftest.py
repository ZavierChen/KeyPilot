"""Isolate GUI settings, caches and histories for each test."""
import pytest


@pytest.fixture(autouse=True)
def isolated_desktop_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYPILOT_DATA_DIR", str(tmp_path / "user-data"))
