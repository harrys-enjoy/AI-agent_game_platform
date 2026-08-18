import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_image_agent import GeminiImageAgent, ImageAgentError
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.schema import Prompts


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiImageAgent(output_dir=tmp_path / "media")


def test_default_model_name_is_gemini_3_1_flash_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "gemini-3.1-flash-image"


def test_custom_model_name_stored(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageAgent(model_name="custom-imager", client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "custom-imager"


def test_estimate_cost_returns_fixed_constant(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.estimate_cost() == 0.039
    assert agent.estimate_cost() == GeminiImageAgent.ESTIMATED_COST_USD


def _fake_interaction(output_image_b64: str) -> SimpleNamespace:
    return SimpleNamespace(output_image=SimpleNamespace(data=output_image_b64))


def test_run_calls_sdk_with_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(prompts)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "gemini-3.1-flash-image"
    assert kwargs["input"][0]["type"] == "text"
    assert kwargs["input"][0]["text"] == "a haunted castle"


def test_run_writes_image_and_returns_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(prompts)

    assert result.generated_by == "gemini-3.1-flash-image"
    assert Path(result.image_url).exists()
    assert Path(result.image_url).read_bytes() == b"generated-image-bytes"


def test_run_wraps_sdk_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)


def test_run_wraps_missing_output_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(output_image=None)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)


def test_run_writes_file_with_extension_matching_mime_type(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = SimpleNamespace(
        output_image=SimpleNamespace(data=image_b64, mime_type="image/jpeg")
    )
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(prompts)

    assert result.image_url.endswith(".jpg")


def test_run_defaults_to_png_extension_when_mime_type_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(prompts)

    assert result.image_url.endswith(".png")


def test_output_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    nested = tmp_path / "nested" / "media"

    GeminiImageAgent(client=MagicMock(), output_dir=nested)

    assert nested.is_dir()


def test_run_logs_candidate_id_and_image_path_when_log_path_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    log_path = tmp_path / "agent_log.jsonl"
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media", log_path=log_path)
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(prompts)

    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["output"]["candidate_id"] == result.candidate_id
    assert entry["output"]["image_path"] == result.image_url


def test_run_without_reference_images_sends_only_text(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(prompts)

    _, kwargs = client.interactions.create.call_args
    assert len(kwargs["input"]) == 1


def test_run_includes_reference_images_in_input_when_given(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")
    reference_path = tmp_path / "scene_01_reference.png"
    reference_path.write_bytes(b"reference-image-bytes")

    agent.run(prompts, reference_image_urls=[str(reference_path)])

    _, kwargs = client.interactions.create.call_args
    assert len(kwargs["input"]) == 2
    reference_block = kwargs["input"][1]
    assert reference_block["type"] == "image"
    assert reference_block["mime_type"] == "image/png"
    assert base64.b64decode(reference_block["data"]) == b"reference-image-bytes"


def test_run_raises_when_reference_image_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    agent = GeminiImageAgent(client=MagicMock(), output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts, reference_image_urls=[str(tmp_path / "does-not-exist.png")])
