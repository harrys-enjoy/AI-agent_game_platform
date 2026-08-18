from video_draft_pipeline import config
from video_draft_pipeline.config import ModelConfig, load_api_keys


def test_model_config_defaults():
    cfg = ModelConfig()
    assert cfg.planning_model == "gemini-3.1-pro-preview"
    assert cfg.storyboard_model == "gemini-3.6-flash"
    assert cfg.prompt_model == "gemini-3.5-flash-lite"
    assert cfg.image_model == "gemini-3.1-flash-image"
    assert cfg.image_edit_model == "gemini-3-pro-image"
    assert cfg.review_model == "gemini-3.6-flash"
    assert cfg.director_model == "gemini-3.6-flash"
    assert cfg.render_backend == "veo-3.1-fast"


def test_load_api_keys_reads_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("VEO_API_KEY", raising=False)
    monkeypatch.delenv("LTX_API_KEY", raising=False)

    keys = load_api_keys()

    assert keys.gemini_api_key == "test-gemini-key"
    assert keys.veo_api_key is None
    assert keys.ltx_api_key is None


def test_load_api_keys_reads_veo_api_key(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "test-veo-key")

    keys = load_api_keys()

    assert keys.veo_api_key == "test-veo-key"


def test_load_api_keys_reads_ltx_api_key(monkeypatch):
    monkeypatch.setenv("LTX_API_KEY", "test-ltx-key")

    keys = load_api_keys()

    assert keys.ltx_api_key == "test-ltx-key"


def test_load_api_keys_falls_back_to_key_file_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key_file = tmp_path / "gemini-key-file"
    key_file.write_text("file-gemini-key\n")
    monkeypatch.setattr(config, "GEMINI_API_KEY_FILE", key_file)

    keys = load_api_keys()

    assert keys.gemini_api_key == "file-gemini-key"


def test_load_api_keys_prefers_env_over_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    key_file = tmp_path / "gemini-key-file"
    key_file.write_text("file-gemini-key\n")
    monkeypatch.setattr(config, "GEMINI_API_KEY_FILE", key_file)

    keys = load_api_keys()

    assert keys.gemini_api_key == "env-gemini-key"


def test_load_api_keys_returns_none_when_env_unset_and_no_key_file(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    keys = load_api_keys()

    assert keys.gemini_api_key is None
