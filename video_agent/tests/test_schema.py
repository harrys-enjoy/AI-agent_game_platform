import pytest
from pydantic import ValidationError

from video_draft_pipeline.schema import (
    ProjectInput,
    Beat,
    Narrative,
    Storyboard,
    StyleGuide,
    Scene,
    Project,
    Candidate,
)


def test_project_input_valid():
    pi = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=30,
        brief="Halloween Event",
    )
    assert pi.max_duration_sec == 30
    assert pi.max_budget_usd == 5.00


def test_project_input_rejects_duration_over_cap():
    with pytest.raises(ValidationError):
        ProjectInput(
            preset="이벤트",
            scene_type="인게임",
            duration_sec=999,
            brief="too long",
        )


def test_project_input_rejects_invalid_preset():
    with pytest.raises(ValidationError):
        ProjectInput(
            preset="not-a-real-preset",
            scene_type="인게임",
            duration_sec=30,
            brief="bad preset",
        )


def test_scene_requires_positive_duration():
    storyboard = Storyboard(camera="pan", subject="boss", action="appears", setting="castle")
    with pytest.raises(ValidationError):
        Scene(
            scene_id="scene_01",
            beat_id="climax",
            order=1,
            duration_sec=0,
            storyboard=storyboard,
        )


def test_project_assembles_full_tree():
    pi = ProjectInput(preset="공개", scene_type="스튜디오", duration_sec=30, brief="Reveal")
    narrative = Narrative(beats=[Beat(beat_id="setup", description="calm", tone="calm")])
    project = Project(project_id="proj_1", input=pi, narrative=narrative)
    assert project.scenes == []
    assert project.output_video_url is None


def test_project_running_cost_usd_defaults_to_zero():
    pi = ProjectInput(preset="공개", scene_type="스튜디오", duration_sec=30, brief="Reveal")
    project = Project(project_id="proj_1", input=pi)
    assert project.running_cost_usd == 0.0


def _scene() -> Scene:
    return Scene(
        scene_id="scene_01",
        beat_id="climax",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(camera="pan", subject="boss", action="appears", setting="castle"),
    )


def test_scene_rejects_negative_duration_on_assignment():
    scene = _scene()
    with pytest.raises(ValidationError):
        scene.duration_sec = -5
    assert scene.duration_sec == 6


def test_scene_rejects_wrong_type_on_assignment():
    scene = _scene()
    with pytest.raises(ValidationError):
        scene.retry_count = "not-an-int"


def test_scene_needs_manual_fix_defaults_to_false():
    scene = _scene()
    assert scene.needs_manual_fix is False


def test_candidate_rejects_wrong_type_on_assignment():
    candidate = Candidate(candidate_id="cand_1", image_url="stub://x.png", generated_by="m")
    with pytest.raises(ValidationError):
        candidate.consistency_review = "not-a-review"


def test_project_rejects_wrong_type_on_assignment():
    pi = ProjectInput(preset="공개", scene_type="스튜디오", duration_sec=30, brief="Reveal")
    project = Project(project_id="proj_1", input=pi)
    with pytest.raises(ValidationError):
        project.narrative = 5


def test_narrative_style_guide_defaults_to_empty_strings():
    narrative = Narrative(beats=[Beat(beat_id="setup", description="d", tone="calm")])

    assert narrative.style_guide == StyleGuide(visual_style="", color_palette="", subject_blueprint="")


def test_narrative_accepts_explicit_style_guide():
    style_guide = StyleGuide(
        visual_style="3D cinematic render", color_palette="teal and orange", subject_blueprint="a knight"
    )

    narrative = Narrative(
        beats=[Beat(beat_id="setup", description="d", tone="calm")], style_guide=style_guide
    )

    assert narrative.style_guide == style_guide


def test_storyboard_visual_style_and_color_palette_default_to_empty_strings():
    storyboard = Storyboard(camera="pan", subject="boss", action="appears", setting="castle")

    assert storyboard.visual_style == ""
    assert storyboard.color_palette == ""
