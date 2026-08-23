from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_storyboard_agent import (
    GeminiStoryboardAgent,
    SceneDraft,
    StoryboardAgentError,
    StoryboardDraft,
    _build_input,
    _drafts_to_scenes,
)
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, Scene, StyleGuide


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiStoryboardAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(model_name="custom-storyboarder", client=MagicMock())

    assert agent.model_name == "custom-storyboarder"


def test_scene_draft_allows_non_positive_weight_at_construction():
    draft = SceneDraft(
        beat_id="setup", camera="와이드 샷", subject="주인공", action="등장",
        setting="필드", required_elements=[], duration_weight=0,
    )

    assert draft.duration_weight == 0


def test_build_input_includes_beat_and_project_details():
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="평화로운 상황", tone="calm"),
            Beat(beat_id="climax", description="절정", tone="epic"),
        ]
    )
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=20, brief="할로윈 이벤트"
    )

    text = _build_input(narrative, project_input)

    assert "평화로운 상황" in text
    assert "절정" in text
    assert "setup" in text
    assert "climax" in text
    assert "이벤트" in text
    assert "스튜디오" in text
    assert "할로윈 이벤트" in text


def test_build_input_includes_style_guide_when_present():
    narrative = Narrative(
        beats=[Beat(beat_id="setup", description="평화로운 상황", tone="calm")],
        style_guide=StyleGuide(
            visual_style="3D cinematic render",
            color_palette="teal and orange",
            subject_blueprint="a knight",
            secondary_subject_blueprint="a colossal kraken",
        ),
    )
    project_input = ProjectInput(preset="이벤트", scene_type="스튜디오", duration_sec=20, brief="할로윈 이벤트")

    text = _build_input(narrative, project_input)

    assert "3D cinematic render" in text
    assert "teal and orange" in text
    assert "a knight" in text
    assert "a colossal kraken" in text


def test_build_input_shows_none_when_secondary_subject_absent():
    narrative = Narrative(
        beats=[Beat(beat_id="setup", description="평화로운 상황", tone="calm")],
        style_guide=StyleGuide(subject_blueprint="a knight"),
    )
    project_input = ProjectInput(preset="이벤트", scene_type="스튜디오", duration_sec=20, brief="할로윈 이벤트")

    text = _build_input(narrative, project_input)

    assert "Secondary subject: none" in text


def test_build_input_shows_unspecified_when_style_guide_empty():
    narrative = Narrative(beats=[Beat(beat_id="setup", description="평화로운 상황", tone="calm")])
    project_input = ProjectInput(preset="이벤트", scene_type="스튜디오", duration_sec=20, brief="할로윈 이벤트")

    text = _build_input(narrative, project_input)

    assert "unspecified" in text


def _draft(beat_id, weight, required_elements=None):
    return SceneDraft(
        beat_id=beat_id, camera="와이드 샷", subject="주인공", action="등장",
        setting="필드", required_elements=required_elements or [], duration_weight=weight,
    )


def test_drafts_to_scenes_computes_exact_duration_sum_even_division():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("climax", 2), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    assert sum(scene.duration_sec for scene in scenes) == 30
    assert scenes[2].duration_sec == 12.0


def test_drafts_to_scenes_last_scene_absorbs_uneven_remainder():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    assert sum(scene.duration_sec for scene in scenes) == 10
    assert scenes[0].duration_sec == scenes[1].duration_sec
    assert scenes[2].duration_sec != scenes[0].duration_sec


def test_drafts_to_scenes_rounds_durations_without_losing_the_exact_sum():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    for scene in scenes:
        assert scene.duration_sec == round(scene.duration_sec, 2)
    assert sum(scene.duration_sec for scene in scenes) == 10


def test_drafts_to_scenes_sets_scene_id_and_order_sequentially():
    drafts = [_draft("setup", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    assert [s.scene_id for s in scenes] == ["scene_01", "scene_02"]
    assert isinstance(scenes[0], Scene)


def test_drafts_to_scenes_uses_subject_blueprint_verbatim_on_every_scene():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")
    style_guide = StyleGuide(subject_blueprint="the exact same knight in every scene")

    scenes = _drafts_to_scenes(drafts, project_input, style_guide)

    assert all(s.storyboard.subject == "the exact same knight in every scene" for s in scenes)


def test_drafts_to_scenes_uses_secondary_subject_blueprint_verbatim_on_every_scene():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")
    style_guide = StyleGuide(secondary_subject_blueprint="a colossal kraken with teardrop-shaped red eyes")

    scenes = _drafts_to_scenes(drafts, project_input, style_guide)

    assert all(
        s.storyboard.secondary_subject == "a colossal kraken with teardrop-shaped red eyes" for s in scenes
    )


def test_drafts_to_scenes_defaults_secondary_subject_to_empty_when_absent():
    drafts = [_draft("setup", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input, StyleGuide())

    assert scenes[0].storyboard.secondary_subject == ""


def test_drafts_to_scenes_falls_back_to_draft_subject_when_blueprint_empty():
    drafts = [_draft("setup", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input, StyleGuide())

    assert scenes[0].storyboard.subject == "주인공"


def test_drafts_to_scenes_defaults_style_guide_when_omitted():
    drafts = [_draft("setup", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    assert scenes[0].storyboard.subject == "주인공"
    assert scenes[0].storyboard.visual_style == ""


def test_drafts_to_scenes_copies_visual_style_and_color_palette_to_every_scene():
    drafts = [_draft("setup", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")
    style_guide = StyleGuide(visual_style="3D cinematic render", color_palette="teal and orange")

    scenes = _drafts_to_scenes(drafts, project_input, style_guide)

    assert all(s.storyboard.visual_style == "3D cinematic render" for s in scenes)
    assert all(s.storyboard.color_palette == "teal and orange" for s in scenes)


def test_drafts_to_scenes_forces_required_elements_only_on_resolution():
    drafts = [
        _draft("setup", 1, required_elements=["모델이 제안한 요소"]),
        _draft("resolution", 1, required_elements=[]),
    ]
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=10, brief="브리프",
        brand_requirements=["로고 노출"],
    )

    scenes = _drafts_to_scenes(drafts, project_input)

    assert scenes[0].storyboard.required_elements == []
    assert scenes[1].storyboard.required_elements == ["로고 노출"]


def _narrative_four_beats():
    return Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )


def _fake_interaction(output_text: str):
    return SimpleNamespace(output_text=output_text)


def test_run_returns_scenes_from_valid_draft(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 2), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    scenes = agent.run(narrative, project_input)

    assert [s.beat_id for s in scenes] == ["setup", "conflict", "climax", "resolution"]
    assert sum(s.duration_sec for s in scenes) == 30


def test_run_threads_style_guide_subject_onto_every_scene(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    narrative.style_guide = StyleGuide(subject_blueprint="the exact same knight in every scene")
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    scenes = agent.run(narrative, project_input)

    assert all(s.storyboard.subject == "the exact same knight in every scene" for s in scenes)


def test_run_threads_secondary_subject_blueprint_onto_every_scene(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    narrative.style_guide = StyleGuide(secondary_subject_blueprint="the exact same kraken in every scene")
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    scenes = agent.run(narrative, project_input)

    assert all(s.storyboard.secondary_subject == "the exact same kraken in every scene" for s in scenes)


def test_run_calls_sdk_with_expected_model_and_input(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(model_name="custom-storyboarder", client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    agent.run(narrative, project_input)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "custom-storyboarder"
    assert kwargs["input"][0]["text"] == _build_input(narrative, project_input)


def test_run_raises_on_beat_mismatch(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1)])
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_run_raises_on_non_positive_duration_weight(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 0), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_run_raises_on_empty_beats(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = Narrative(beats=[])
    client = MagicMock()
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)

    client.interactions.create.assert_not_called()


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.01
    assert agent.estimate_cost() == GeminiStoryboardAgent.ESTIMATED_COST_USD
