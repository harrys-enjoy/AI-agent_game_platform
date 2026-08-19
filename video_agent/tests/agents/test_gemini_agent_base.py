import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.agents.gemini_agent_base import BaseGeminiAgent


class _DummyError(Exception):
    pass


class _DummyAgent(BaseGeminiAgent):
    error_cls = _DummyError


class _DummyResult(BaseModel):
    value: str


def _fake_interaction(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=output_text)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        _DummyAgent(model_name="dummy-model")


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.api_key == "env-key"


def test_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.model_name == "dummy-model"


def test_structured_interaction_returns_parsed_result(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"value": "the-result"}')
    agent = _DummyAgent(model_name="dummy-model", client=client)

    result = agent._structured_interaction(input_content=[], response_schema=_DummyResult)

    assert result == _DummyResult(value="the-result")


def test_structured_interaction_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_interaction(input_content=[], response_schema=_DummyResult)


def test_structured_interaction_wraps_malformed_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_interaction(input_content=[], response_schema=_DummyResult)


class _DummyAgentWithBaseUrl(BaseGeminiAgent):
    error_cls = _DummyError


class _CapturingClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_base_url_is_none_by_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = _DummyAgent(model_name="dummy-model")

    assert agent._client.kwargs["http_options"] is None


def test_explicit_base_url_is_used(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = _DummyAgentWithBaseUrl(
        model_name="dummy-model", base_url="https://explicit.example/v1"
    )

    assert agent._client.kwargs["http_options"] == {"base_url": "https://explicit.example/v1"}


def test_structured_interaction_does_not_log_when_log_path_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"value": "the-result"}')
    agent = _DummyAgent(model_name="dummy-model", client=client)

    agent._structured_interaction(input_content=[{"type": "text", "text": "hi"}], response_schema=_DummyResult)

    assert list(tmp_path.iterdir()) == []


def test_structured_interaction_logs_input_and_output(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"value": "the-result"}')
    log_path = tmp_path / "agent_log.jsonl"
    agent = _DummyAgent(model_name="dummy-model", client=client, log_path=log_path)

    agent._structured_interaction(input_content=[{"type": "text", "text": "hi"}], response_schema=_DummyResult)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["agent"] == "_DummyAgent"
    assert entry["model"] == "dummy-model"
    assert entry["input"] == [{"type": "text", "text": "hi"}]
    assert entry["output"] == {"value": "the-result"}
    assert "timestamp" in entry


def test_log_interaction_sanitizes_image_data(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    log_path = tmp_path / "agent_log.jsonl"
    agent = _DummyAgent(model_name="dummy-model", client=MagicMock(), log_path=log_path)

    agent._log_interaction(
        input_content=[{"type": "image", "data": "x" * 100, "mime_type": "image/jpeg"}],
        output={"candidate_id": "cand_1"},
    )

    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["input"] == [
        {"type": "image", "data": "<100 base64 chars omitted>", "mime_type": "image/jpeg"}
    ]


def test_log_interaction_appends_across_multiple_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    log_path = tmp_path / "agent_log.jsonl"
    agent = _DummyAgent(model_name="dummy-model", client=MagicMock(), log_path=log_path)

    agent._log_interaction(input_content=[], output={"n": 1})
    agent._log_interaction(input_content=[], output={"n": 2})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["output"] == {"n": 1}
    assert json.loads(lines[1])["output"] == {"n": 2}


def test_log_interaction_creates_parent_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    log_path = tmp_path / "nested" / "dir" / "agent_log.jsonl"
    agent = _DummyAgent(model_name="dummy-model", client=MagicMock(), log_path=log_path)

    agent._log_interaction(input_content=[], output={})

    assert log_path.exists()
