import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_image_edit_agent import GeminiImageEditAgent, ImageEditAgentError
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.schema import Candidate, Prompts


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiImageEditAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(api_key="explicit-key", client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.api_key == "env-key"


def test_default_model_name_is_gemini_3_pro_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "gemini-3-pro-image"


def test_custom_model_name_stored(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(model_name="custom-editor", client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "custom-editor"


def test_estimate_cost_returns_fixed_constant(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.estimate_cost() == 0.134
    assert agent.estimate_cost() == GeminiImageEditAgent.ESTIMATED_COST_USD


def _fake_interaction(output_image_b64: str) -> SimpleNamespace:
    return SimpleNamespace(output_image=SimpleNamespace(data=output_image_b64))


def test_run_calls_sdk_with_feedback_and_prior_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(edited_b64)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prompts, feedback="fix the lighting")

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "gemini-3-pro-image"
    input_content = kwargs["input"]
    assert input_content[0]["type"] == "text"
    assert "fix the lighting" in input_content[0]["text"]
    assert "a haunted castle" in input_content[0]["text"]
    assert input_content[1]["type"] == "image"
    assert input_content[1]["mime_type"] == "image/png"
    assert base64.b64decode(input_content[1]["data"]) == b"prior-image-bytes"


def test_run_writes_edited_image_and_returns_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(edited_b64)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(candidate, prompts, feedback="fix the lighting")

    assert result.generated_by == "gemini-3-pro-image"
    assert result.candidate_id != candidate.candidate_id
    assert Path(result.image_url).exists()
    assert Path(result.image_url).read_bytes() == b"edited-image-bytes"


def test_run_sends_mime_type_matching_source_image_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.jpg"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(edited_b64)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prompts, feedback="fix the lighting")

    _, kwargs = client.interactions.create.call_args
    assert kwargs["input"][1]["mime_type"] == "image/jpeg"


def test_run_writes_file_with_extension_matching_output_mime_type(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = SimpleNamespace(
        output_image=SimpleNamespace(data=edited_b64, mime_type="image/jpeg")
    )
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(candidate, prompts, feedback="fix the lighting")

    assert result.image_url.endswith(".jpg")


def test_run_wraps_sdk_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageEditAgentError):
        agent.run(candidate, prompts, feedback="fix it")


def test_run_wraps_unreadable_image_path(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")
    candidate = Candidate(
        candidate_id="c1", image_url=str(tmp_path / "does-not-exist.png"), generated_by="gpt-image-2"
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageEditAgentError):
        agent.run(candidate, prompts, feedback="fix it")


def test_run_logs_candidate_id_and_image_path_when_log_path_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(edited_b64)
    log_path = tmp_path / "agent_log.jsonl"
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media", log_path=log_path)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(candidate, prompts, feedback="fix the lighting")

    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["output"]["candidate_id"] == result.candidate_id
    assert entry["output"]["image_path"] == result.image_url


def test_run_wraps_missing_output_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(output_image=None)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageEditAgentError):
        agent.run(candidate, prompts, feedback="fix it")


