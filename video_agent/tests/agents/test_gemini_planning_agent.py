from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_planning_agent import (
    GeminiPlanningAgent,
    PlanningAgentError,
    _build_input,
)
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, StyleGuide


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiPlanningAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gemini_3_1_pro_preview(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.1-pro-preview"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(model_name="custom-planner", client=MagicMock())

    assert agent.model_name == "custom-planner"


def test_build_input_includes_fields():
    project_input = ProjectInput(
        preset="공개",
        scene_type="인게임",
        duration_sec=15,
        brief="신규 캐릭터 공개",
        brand_requirements=["로고 노출"],
    )

    text = _build_input(project_input)

    assert "신규 캐릭터 공개" in text
    assert "공개" in text
    assert "인게임" in text
    assert "로고 노출" in text


def test_build_input_handles_empty_brand_requirements():
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=10, brief="브리프"
    )

    text = _build_input(project_input)

    assert text


def test_build_input_requests_style_guide_fields():
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=10, brief="브리프"
    )

    text = _build_input(project_input)

    assert "visual_style" in text
    assert "color_palette" in text
    assert "subject_blueprint" in text
    assert "verbatim" in text


def test_build_input_forbids_naming_physical_effects_in_color_palette():
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=10, brief="브리프"
    )

    text = _build_input(project_input)

    assert "never name a physical object, prop, or effect" in text
    assert "smoke, fire, sparks" in text


def _narrative():
    return Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )


def _fake_interaction(output_text: str):
    from types import SimpleNamespace

    return SimpleNamespace(output_text=output_text)


def test_run_returns_parsed_narrative(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative()
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(narrative.model_dump_json())
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    result = agent.run(project_input)

    assert result == narrative


def test_run_returns_parsed_style_guide(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative()
    narrative.style_guide = StyleGuide(
        visual_style="3D cinematic render", color_palette="teal and orange", subject_blueprint="a knight"
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(narrative.model_dump_json())
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    result = agent.run(project_input)

    assert result.style_guide == narrative.style_guide


def test_run_calls_sdk_with_expected_model_and_input(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative()
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(narrative.model_dump_json())
    agent = GeminiPlanningAgent(model_name="custom-planner", client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    agent.run(project_input)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "custom-planner"
    input_content = kwargs["input"]
    assert input_content[0]["type"] == "text"
    assert input_content[0]["text"] == _build_input(project_input)


def test_run_wraps_sdk_exception_as_planning_agent_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    with pytest.raises(PlanningAgentError):
        agent.run(project_input)


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    with pytest.raises(PlanningAgentError):
        agent.run(project_input)


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.01
    assert agent.estimate_cost() == GeminiPlanningAgent.ESTIMATED_COST_USD
