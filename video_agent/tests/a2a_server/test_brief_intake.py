from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.a2a_server.brief_intake import (
    BriefIntakeAgent,
    BriefIntakeError,
    extract_hints,
)
from video_draft_pipeline.agents.errors import MissingAPIKeyError


def test_extract_hints_finds_duration_in_seconds():
    hints = extract_hints("할로윈 이벤트 홍보 영상, 15초 분량으로 만들어줘")

    assert hints["duration_sec"] == 15


def test_extract_hints_finds_budget_amount():
    hints = extract_hints("예산은 3달러 정도로 부탁해")

    assert hints["max_budget_usd"] == 3.0


def test_extract_hints_finds_preset_keyword():
    hints = extract_hints("신규 캐릭터 공개 이벤트 영상")

    assert hints["preset"] == "이벤트"


def test_extract_hints_finds_scene_type_keyword():
    hints = extract_hints("인게임 화면으로 촬영된 느낌으로")

    assert hints["scene_type"] == "인게임"


def test_extract_hints_returns_empty_dict_when_nothing_matches():
    assert extract_hints("안녕하세요") == {}


def _fake_interaction(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=output_text)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        BriefIntakeAgent()


def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = BriefIntakeAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = BriefIntakeAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.02
    assert agent.estimate_cost() == BriefIntakeAgent.ESTIMATED_COST_USD


def test_run_passes_raw_text_and_hints_to_the_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(
        '{"brief": "할로윈 신규 캐릭터 공개 이벤트", "preset": "이벤트", '
        '"scene_type": "인게임", "duration_sec": 15, "max_budget_usd": null, '
        '"clarifying_question": null}'
    )
    agent = BriefIntakeAgent(client=client)

    agent.run("할로윈 신규 캐릭터 공개 이벤트, 15초 분량으로 만들어줘")

    _, kwargs = client.interactions.create.call_args
    text = kwargs["input"][0]["text"]
    assert "할로윈 신규 캐릭터 공개 이벤트" in text
    assert "duration_sec: 15" in text


def test_run_returns_filled_intake_result_when_confident(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(
        '{"brief": "할로윈 신규 캐릭터 공개 이벤트", "preset": "이벤트", '
        '"scene_type": "인게임", "duration_sec": 15, "max_budget_usd": null, '
        '"clarifying_question": null}'
    )
    agent = BriefIntakeAgent(client=client)

    result = agent.run("할로윈 신규 캐릭터 공개 이벤트, 15초 분량으로 만들어줘")

    assert result.brief == "할로윈 신규 캐릭터 공개 이벤트"
    assert result.preset == "이벤트"
    assert result.scene_type == "인게임"
    assert result.duration_sec == 15
    assert result.clarifying_question is None


def test_run_returns_clarifying_question_when_vague(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(
        '{"brief": null, "preset": null, "scene_type": null, "duration_sec": null, '
        '"max_budget_usd": null, "clarifying_question": "어떤 영상을 만들고 싶으신가요?"}'
    )
    agent = BriefIntakeAgent(client=client)

    result = agent.run("안녕")

    assert result.brief is None
    assert result.clarifying_question == "어떤 영상을 만들고 싶으신가요?"


def test_run_falls_back_to_default_question_when_model_sets_neither(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(
        '{"brief": null, "preset": null, "scene_type": null, "duration_sec": null, '
        '"max_budget_usd": null, "clarifying_question": null}'
    )
    agent = BriefIntakeAgent(client=client)

    result = agent.run("음...")

    assert result.brief is None
    assert result.clarifying_question is not None


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = BriefIntakeAgent(client=client)

    with pytest.raises(BriefIntakeError):
        agent.run("할로윈 이벤트 영상")


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = BriefIntakeAgent(client=client)

    with pytest.raises(BriefIntakeError):
        agent.run("할로윈 이벤트 영상")
