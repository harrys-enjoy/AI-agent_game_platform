import pytest

from video_draft_pipeline import config


@pytest.fixture(autouse=True)
def isolate_api_key_files(monkeypatch, tmp_path):
    """Redirect the ~/.gemini_api_key etc. fallback files to a nonexistent
    tmp_path location for every test, so the suite's behavior doesn't depend
    on whether a developer happens to have real key files on their machine."""
    monkeypatch.setattr(config, "GEMINI_API_KEY_FILE", tmp_path / "no-gemini-key")
    monkeypatch.setattr(config, "VEO_API_KEY_FILE", tmp_path / "no-veo-key")
    monkeypatch.setattr(config, "LTX_API_KEY_FILE", tmp_path / "no-ltx-key")
