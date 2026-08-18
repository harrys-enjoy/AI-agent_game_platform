import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.config import ModelConfig
from video_draft_pipeline.orchestrator import run_pipeline, PipelineError, ReviewAgent, resume_scene_with_image
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent, beat_backend_map
from video_draft_pipeline.project_store import ProjectStore
from video_draft_pipeline.schema import (
    Beat,
    Candidate,
    ConsistencyReview,
    DirectorDecision,
    Narrative,
    Project,
    ProjectInput,
    Prompts,
    RenderResult,
    Scene,
    Storyboard,
)


def test_run_pipeline_produces_fully_rendered_project():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.narrative is not None
    assert len(project.narrative.beats) == 4
    assert len(project.scenes) == 4
    assert sum(scene.duration_sec for scene in project.scenes) == 30

    for scene in project.scenes:
        assert scene.accepted_candidate_id is not None
        assert scene.render is not None
        assert scene.render.status == "done"

    total_cost = sum(scene.render.cost_usd for scene in project.scenes)
    assert total_cost <= project_input.max_budget_usd


def test_run_pipeline_works_offline_with_no_api_keys_set(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VEO_API_KEY", raising=False)
    monkeypatch.delenv("LTX_API_KEY", raising=False)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.scenes[0].render.clip_url.startswith("stub://veo/")


def test_run_pipeline_raises_when_duration_exceeds_cap():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=30,
        brief="Halloween Event",
        max_duration_sec=10,
    )

    with pytest.raises(PipelineError):
        run_pipeline(project_input)


def test_run_pipeline_marks_all_scenes_needs_manual_fix_when_review_always_fails(monkeypatch):
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )

    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.ReviewAgent", FailingReviewAgent
    )

    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert len(project.scenes) == 4
    for scene in project.scenes:
        assert scene.needs_manual_fix is True
        assert scene.accepted_candidate_id is None
        assert scene.render is None
        assert scene.candidates[-1].consistency_review.issues == ["forced failure for test"]


class TwoSceneStoryboardAgent:
    def run(self, narrative, project_input):
        storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
        return [
            Scene(scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5, storyboard=storyboard),
            Scene(scene_id="scene_bad", beat_id="conflict", order=2, duration_sec=5, storyboard=storyboard),
        ]

    def estimate_cost(self):
        return 0.0


class SceneTaggingPromptAgent:
    def run(self, scene, feedback=None):
        return Prompts(image_prompt=f"prompt-for-{scene.scene_id}", video_motion_prompt="motion")

    def estimate_cost(self):
        return 0.0


class FailOnlyForBadScenePromptReviewAgent:
    def run(self, candidate, prior_candidates, prompts):
        if "scene_bad" in prompts.image_prompt:
            return ConsistencyReview(reviewed_by="fake", passed=False, issues=["forced failure for test"])
        return ConsistencyReview(reviewed_by="fake", passed=True, issues=[])

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_skips_assembly_when_any_scene_needs_manual_fix(monkeypatch):
    mock_assemble = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        storyboard_agent=TwoSceneStoryboardAgent(),
        prompt_agent=SceneTaggingPromptAgent(),
        review_agent=FailOnlyForBadScenePromptReviewAgent(),
        assemble=True,
    )

    ok_scene = next(s for s in project.scenes if s.scene_id == "scene_ok")
    bad_scene = next(s for s in project.scenes if s.scene_id == "scene_bad")
    assert ok_scene.needs_manual_fix is False
    assert ok_scene.render is not None
    assert bad_scene.needs_manual_fix is True
    assert bad_scene.render is None
    assert project.output_video_url is None
    mock_assemble.assert_not_called()


def test_run_pipeline_persists_running_cost_on_project():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    expected_total = sum(scene.render.cost_usd for scene in project.scenes)
    assert project.running_cost_usd >= expected_total


def test_format_candidate_diagnostics_formats_attempt_lines():
    from video_draft_pipeline.orchestrator import format_candidate_diagnostics

    review = ConsistencyReview(reviewed_by="r", passed=False, issues=["issue-a"])
    decision = DirectorDecision(decision="regenerate", feedback="fix it", decided_by="d")
    candidate = Candidate(
        candidate_id="c1", image_url="u", generated_by="m",
        consistency_review=review, director_decision=decision,
    )

    text = format_candidate_diagnostics([candidate])

    assert "attempt 1" in text
    assert "issue-a" in text
    assert "regenerate" in text


def test_run_pipeline_checkpoints_each_scene_to_project_store(tmp_path):
    from video_draft_pipeline.project_store import ProjectStore

    store = ProjectStore(tmp_path)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )

    project = run_pipeline(project_input, project_store=store)

    reloaded = store.load(project.project_id)
    assert len(reloaded.scenes) == 4
    assert reloaded.scenes[0].render is not None


def test_run_pipeline_threads_model_config_into_agents():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    model_config = ModelConfig(
        image_model="custom-image-model",
        review_model="custom-review-model",
        director_model="custom-director-model",
        render_backend="veo-3.1-standard",
    )

    project = run_pipeline(project_input, model_config=model_config)

    for scene in project.scenes:
        candidate = scene.candidates[-1]
        assert candidate.generated_by == "custom-image-model"
        assert candidate.consistency_review.reviewed_by == "custom-review-model"
        assert candidate.director_decision.decided_by == "custom-director-model"
        assert scene.render.backend == "veo-3.1-standard"


def test_run_pipeline_uses_config_defaults_when_none_given():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    defaults = ModelConfig()

    project = run_pipeline(project_input)

    candidate = project.scenes[0].candidates[-1]
    assert candidate.generated_by == defaults.image_model
    assert candidate.consistency_review.reviewed_by == defaults.review_model
    assert candidate.director_decision.decided_by == defaults.director_model
    assert project.scenes[0].render.backend == defaults.render_backend


def test_run_pipeline_explicit_backend_overrides_model_config():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        render_backend=StubRenderBackend(tier="veo-3.1-lite"),
        model_config=ModelConfig(render_backend="veo-3.1-standard"),
    )

    assert project.scenes[0].render.backend == "veo-3.1-lite"


class FakePlanningAgent:
    def run(self, project_input):
        return Narrative(
            beats=[Beat(beat_id="setup", description="fake-planning-marker", tone="calm")]
        )

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_planning_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, planning_agent=FakePlanningAgent())

    assert len(project.narrative.beats) == 1
    assert project.narrative.beats[0].description == "fake-planning-marker"
    assert len(project.scenes) == 1


class FakeStoryboardAgent:
    def run(self, narrative, project_input):
        return [
            Scene(
                scene_id="fake_scene_injected",
                beat_id="setup",
                order=1,
                duration_sec=project_input.duration_sec,
                storyboard=Storyboard(
                    camera="fake-cam",
                    subject="fake-subj",
                    action="fake-action",
                    setting="fake-setting",
                ),
            )
        ]

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_storyboard_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, storyboard_agent=FakeStoryboardAgent())

    assert len(project.scenes) == 1
    assert project.scenes[0].scene_id == "fake_scene_injected"


class FakePromptAgent:
    def run(self, scene):
        return Prompts(image_prompt="fake-prompt-marker", video_motion_prompt="fake-motion")

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_prompt_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, prompt_agent=FakePromptAgent())

    assert project.scenes[0].prompts.image_prompt == "fake-prompt-marker"


class FakeImageAgent:
    def run(self, prompts, reference_image_urls=None):
        return Candidate(
            candidate_id="fake_cand_injected",
            image_url="fake://url",
            generated_by="fake-image-model",
        )

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_image_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, image_agent=FakeImageAgent())

    candidate = project.scenes[0].candidates[-1]
    assert candidate.candidate_id == "fake_cand_injected"
    assert candidate.generated_by == "fake-image-model"


class ExpensivePlanningAgent:
    def __init__(self):
        self.run_called = False

    def run(self, project_input):
        self.run_called = True
        return Narrative(beats=[Beat(beat_id="setup", description="d", tone="calm")])

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_planning_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensivePlanningAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, planning_agent=expensive_agent)

    assert expensive_agent.run_called is False


class ExpensiveStoryboardAgent:
    def __init__(self):
        self.run_called = False

    def run(self, narrative, project_input):
        self.run_called = True
        return []

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_storyboard_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveStoryboardAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, storyboard_agent=expensive_agent)

    assert expensive_agent.run_called is False


class ExpensivePromptAgent:
    def __init__(self):
        self.run_called = False

    def run(self, scene):
        self.run_called = True
        return Prompts(image_prompt="p", video_motion_prompt="m")

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_prompt_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensivePromptAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, prompt_agent=expensive_agent)

    assert expensive_agent.run_called is False


class ExpensiveImageAgent:
    def __init__(self):
        self.run_called = False

    def run(self, prompts, reference_image_urls=None):
        self.run_called = True
        return Candidate(candidate_id="c", image_url="u", generated_by="m")

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_image_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveImageAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, image_agent=expensive_agent)

    assert expensive_agent.run_called is False


def test_run_pipeline_blocks_image_agent_partway_through_retries(monkeypatch):
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate, prior_candidates, prompts):
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )

    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.ReviewAgent", FailingReviewAgent
    )

    class CountingImageAgent:
        def __init__(self):
            self.call_count = 0

        def run(self, prompts, reference_image_urls=None):
            self.call_count += 1
            return Candidate(
                candidate_id=f"cand_{self.call_count}",
                image_url="fake://url",
                generated_by="fake-image-model",
            )

        def estimate_cost(self):
            return 0.04

    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=0.10,
    )
    counting_agent = CountingImageAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, image_agent=counting_agent)

    assert counting_agent.call_count == 2


def test_run_pipeline_blocks_image_edit_agent_partway_through_retries(monkeypatch):
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate, prior_candidates, prompts):
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
                defect_category="localized_artifact",
            )

    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.ReviewAgent", FailingReviewAgent
    )

    class ExpensiveImageEditAgent:
        def __init__(self):
            self.run_called = False

        def run(self, candidate, prompts, feedback):
            self.run_called = True
            return Candidate(candidate_id="c", image_url="u", generated_by="m")

        def estimate_cost(self):
            return 0.04

    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=0.01,
    )
    expensive_edit_agent = ExpensiveImageEditAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, image_edit_agent=expensive_edit_agent)

    assert expensive_edit_agent.run_called is False


class FakeReviewAgent:
    def run(self, candidate, prior_candidates, prompts):
        return ConsistencyReview(
            reviewed_by="fake-reviewer", passed=True, issues=["fake-review-marker"]
        )

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_review_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, review_agent=FakeReviewAgent())

    candidate = project.scenes[0].candidates[-1]
    assert candidate.consistency_review.reviewed_by == "fake-reviewer"
    assert candidate.consistency_review.issues == ["fake-review-marker"]


class ExpensiveReviewAgent:
    def __init__(self):
        self.run_called = False

    def run(self, candidate, prior_candidates, prompts):
        self.run_called = True
        return ConsistencyReview(reviewed_by="expensive-reviewer", passed=True, issues=[])

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_review_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveReviewAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, review_agent=expensive_agent)

    assert expensive_agent.run_called is False


def test_run_pipeline_accepts_real_gemini_review_agent(tmp_path):
    from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent

    image_path = tmp_path / "media" / "cand_1.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-image-bytes")

    class FakeImageAgentWithRealFile:
        def run(self, prompts, reference_image_urls=None):
            return Candidate(
                candidate_id="cand_1", image_url=str(image_path), generated_by="fake-model"
            )

        def estimate_cost(self):
            return 0.0

    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_text='{"passed": true, "issues": []}'
    )
    real_review_agent = GeminiReviewAgent(api_key="test-key", client=client)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        image_agent=FakeImageAgentWithRealFile(),
        review_agent=real_review_agent,
    )

    candidate = project.scenes[0].candidates[-1]
    assert candidate.consistency_review.reviewed_by == "gemini-3.6-flash"
    assert candidate.consistency_review.passed is True


def test_run_pipeline_blocks_review_agent_partway_through_retries():
    class CountingReviewAgent:
        def __init__(self):
            self.call_count = 0

        def run(self, candidate, prior_candidates, prompts):
            self.call_count += 1
            return ConsistencyReview(
                reviewed_by="counting-reviewer", passed=False, issues=["forced failure for test"]
            )

        def estimate_cost(self):
            return 0.04

    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=0.10,
    )
    counting_agent = CountingReviewAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, review_agent=counting_agent)

    assert counting_agent.call_count == 2


class FakeDirectorAgent:
    def run(self, scene, review):
        return DirectorDecision(decision="accept", decided_by="fake-director")

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_director_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, director_agent=FakeDirectorAgent())

    candidate = project.scenes[0].candidates[-1]
    assert candidate.director_decision.decided_by == "fake-director"


class ExpensiveDirectorAgent:
    def __init__(self):
        self.run_called = False

    def run(self, scene, review):
        self.run_called = True
        return DirectorDecision(decision="accept", decided_by="expensive-director")

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_director_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveDirectorAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, director_agent=expensive_agent)

    assert expensive_agent.run_called is False


def test_run_pipeline_blocks_director_agent_partway_through_retries(monkeypatch):
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate, prior_candidates, prompts):
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )

    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.ReviewAgent", FailingReviewAgent
    )

    class CountingDirectorAgent:
        def __init__(self):
            self.call_count = 0

        def run(self, scene, review):
            self.call_count += 1
            return DirectorDecision(decision="regenerate", decided_by="counting-director")

        def estimate_cost(self):
            return 0.04

    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=0.10,
    )
    counting_agent = CountingDirectorAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, director_agent=counting_agent)

    assert counting_agent.call_count == 2


class FakePaidRenderBackend:
    def estimate_cost(self, duration_sec):
        return 0.0

    def render(self, candidate, motion_prompt, duration_sec):
        return RenderResult(backend="veo-3.1-standard", status="done", clip_url="fake://paid", cost_usd=0.0)


class FakeFreeRenderBackend:
    def estimate_cost(self, duration_sec):
        return 0.0

    def render(self, candidate, motion_prompt, duration_sec):
        return RenderResult(backend="ltx-2-3-fast", status="done", clip_url="fake://free", cost_usd=0.0)


def test_run_pipeline_routes_scenes_by_beat_with_render_backend_by_beat():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )
    paid = FakePaidRenderBackend()
    free = FakeFreeRenderBackend()

    project = run_pipeline(
        project_input,
        render_backend_by_beat=beat_backend_map(paid_backend=paid, free_backend=free),
    )

    backend_by_beat_id = {scene.beat_id: scene.render.backend for scene in project.scenes}
    assert backend_by_beat_id["climax"] == "veo-3.1-standard"
    assert backend_by_beat_id["resolution"] == "veo-3.1-standard"
    assert backend_by_beat_id["setup"] == "ltx-2-3-fast"
    assert backend_by_beat_id["conflict"] == "ltx-2-3-fast"


def test_run_pipeline_ignores_render_backend_by_beat_when_not_given():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.scenes[0].render.clip_url.startswith("stub://veo/")


def test_run_pipeline_does_not_assemble_by_default(monkeypatch):
    mock_assemble = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.output_video_url is None
    mock_assemble.assert_not_called()


def test_run_pipeline_assembles_when_requested(monkeypatch):
    mock_assemble = MagicMock(return_value="media/fake-output.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, assemble=True)

    assert project.output_video_url == "media/fake-output.mp4"
    clip_paths_arg, output_path_arg = mock_assemble.call_args[0]
    assert output_path_arg == f"media/{project.project_id}.mp4"
    assert clip_paths_arg == [scene.render.clip_url for scene in project.scenes]


def test_run_pipeline_assembles_to_explicit_output_path(monkeypatch):
    mock_assemble = MagicMock(return_value="custom/path.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, assemble=True, assembly_output_path="custom/path.mp4")

    assert project.output_video_url == "custom/path.mp4"
    _, output_path_arg = mock_assemble.call_args[0]
    assert output_path_arg == "custom/path.mp4"


def test_run_pipeline_wraps_ffmpeg_called_process_error(monkeypatch):
    mock_assemble = MagicMock(side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]))
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    with pytest.raises(PipelineError):
        run_pipeline(project_input, assemble=True)


def test_run_pipeline_wraps_missing_ffmpeg_binary(monkeypatch):
    mock_assemble = MagicMock(side_effect=FileNotFoundError("ffmpeg not found"))
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    with pytest.raises(PipelineError):
        run_pipeline(project_input, assemble=True)


def test_run_pipeline_assemble_invokes_ffmpeg_end_to_end(monkeypatch, tmp_path):
    mock_run = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.assembly.subprocess.run", mock_run)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    output_path = tmp_path / "nested" / "final.mp4"

    project = run_pipeline(project_input, assemble=True, assembly_output_path=output_path)

    assert project.output_video_url == str(output_path)
    command = mock_run.call_args[0][0]
    assert command[0] == "ffmpeg" and command[-1] == str(output_path)
    concat_lines = output_path.with_suffix(".txt").read_text(encoding="utf-8").splitlines()
    assert concat_lines == [
        f"file '{Path(s.render.clip_url).resolve().as_posix()}'" for s in project.scenes
    ]


class CountingScratchImageAgent:
    def __init__(self):
        self.calls = []
        self.reference_image_urls_calls = []

    def run(self, prompts, reference_image_urls=None):
        self.calls.append(prompts)
        self.reference_image_urls_calls.append(reference_image_urls)
        return Candidate(
            candidate_id=f"cand_scratch_{len(self.calls)}", image_url="fake://scratch", generated_by="fake-image-model"
        )

    def estimate_cost(self):
        return 0.0


class CountingImageEditAgent:
    def __init__(self):
        self.calls = []

    def run(self, candidate, prompts, feedback):
        self.calls.append((candidate, prompts, feedback))
        return Candidate(candidate_id="cand_edit_1", image_url="fake://edit", generated_by="fake-edit-model")

    def estimate_cost(self):
        return 0.0


class FeedbackRevisingPromptAgent:
    def __init__(self):
        self.calls = []

    def run(self, scene, feedback=None):
        self.calls.append(feedback)
        return Prompts(image_prompt=f"revised-for:{feedback}", video_motion_prompt="revised-motion")

    def estimate_cost(self):
        return 0.0


class ScriptedReviewAgent:
    def __init__(self, reviews):
        self.reviews = list(reviews)
        self.call_count = 0

    def run(self, candidate, prior_candidates, prompts):
        index = min(self.call_count, len(self.reviews) - 1)
        review = self.reviews[index]
        self.call_count += 1
        return review

    def estimate_cost(self):
        return 0.0


class ScriptedDirectorAgent:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.call_count = 0

    def run(self, scene, review):
        index = min(self.call_count, len(self.decisions) - 1)
        decision = self.decisions[index]
        self.call_count += 1
        return decision

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_edits_on_first_retry_when_defect_is_localized_then_regenerates_on_second():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    image_agent = CountingScratchImageAgent()
    image_edit_agent = CountingImageEditAgent()
    prompt_agent = FeedbackRevisingPromptAgent()
    review_agent = ScriptedReviewAgent(
        [
            ConsistencyReview(
                reviewed_by="fake", passed=False, issues=["small artifact"],
                defect_category="localized_artifact",
            ),
            ConsistencyReview(
                reviewed_by="fake", passed=False, issues=["still off"],
                defect_category="localized_artifact",
            ),
            ConsistencyReview(reviewed_by="fake", passed=True, issues=[]),
        ]
    )
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix the lighting", decided_by="fake-director"),
            DirectorDecision(decision="regenerate", feedback="still too dark", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(
        project_input,
        planning_agent=FakePlanningAgent(),
        prompt_agent=prompt_agent,
        image_agent=image_agent,
        image_edit_agent=image_edit_agent,
        review_agent=review_agent,
        director_agent=director_agent,
    )

    scene = project.scenes[0]
    assert len(image_agent.calls) == 2  # attempt 1 (fresh) + attempt 3 (regenerate-from-scratch)
    assert len(image_edit_agent.calls) == 1  # attempt 2 only, since defect was localized
    edited_candidate, _, edited_feedback = image_edit_agent.calls[0]
    assert edited_candidate.candidate_id == scene.candidates[0].candidate_id
    assert edited_feedback == "fix the lighting"
    assert prompt_agent.calls == [None, "still too dark"]  # initial call (no feedback) + fallback revision
    assert scene.prompts.image_prompt == "revised-for:still too dark"
    assert scene.retry_count == 2
    assert scene.accepted_candidate_id == scene.candidates[-1].candidate_id


def test_run_pipeline_skips_edit_and_regenerates_immediately_when_defect_is_structural():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    image_agent = CountingScratchImageAgent()
    image_edit_agent = CountingImageEditAgent()
    prompt_agent = FeedbackRevisingPromptAgent()
    review_agent = ScriptedReviewAgent(
        [
            ConsistencyReview(
                reviewed_by="fake", passed=False, issues=["bent rifle"],
                defect_category="structural_geometry",
            ),
            ConsistencyReview(reviewed_by="fake", passed=True, issues=[]),
        ]
    )
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix the bent rifle", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(
        project_input,
        planning_agent=FakePlanningAgent(),
        prompt_agent=prompt_agent,
        image_agent=image_agent,
        image_edit_agent=image_edit_agent,
        review_agent=review_agent,
        director_agent=director_agent,
    )

    scene = project.scenes[0]
    assert len(image_agent.calls) == 2  # attempt 1 (fresh) + attempt 2 (regenerate, edit skipped)
    assert len(image_edit_agent.calls) == 0
    assert prompt_agent.calls == [None, "fix the bent rifle"]
    assert scene.retry_count == 1
    assert scene.accepted_candidate_id == scene.candidates[-1].candidate_id


def test_run_pipeline_defaults_to_regenerate_on_first_retry_when_defect_category_is_none():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix it", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(project_input, director_agent=director_agent)

    # default stub ReviewAgent always passes, so a director-forced regenerate
    # carries no defect_category signal (defaults to "none") — routing should
    # not assume it's safe for a localized edit and should regenerate instead.
    regenerated_candidate = project.scenes[0].candidates[1]
    assert regenerated_candidate.image_url.startswith("stub://gemini-3.1-flash-image/")


class FakeImageEditAgent:
    def run(self, candidate, prompts, feedback):
        return Candidate(candidate_id="fake_cand_edited", image_url="fake://edited", generated_by="fake-edit-model")

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_image_edit_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    review_agent = ScriptedReviewAgent(
        [
            ConsistencyReview(
                reviewed_by="fake", passed=False, issues=["small artifact"],
                defect_category="localized_artifact",
            ),
            ConsistencyReview(reviewed_by="fake", passed=True, issues=[]),
        ]
    )
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix it", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(
        project_input,
        review_agent=review_agent,
        director_agent=director_agent,
        image_edit_agent=FakeImageEditAgent(),
    )

    edited_candidate = project.scenes[0].candidates[1]
    assert edited_candidate.candidate_id == "fake_cand_edited"
    assert edited_candidate.generated_by == "fake-edit-model"


def _project_with_two_scenes(*, bad_needs_fix=True) -> Project:
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event")
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        accepted_candidate_id="cand_ok",
        candidates=[Candidate(candidate_id="cand_ok", image_url="stub://ok.png", generated_by="m")],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url="stub://veo/cand_ok.mp4", cost_usd=0.5),
    )
    bad_scene = Scene(
        scene_id="scene_bad", beat_id="conflict", order=2, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=bad_needs_fix,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    project = Project(project_id="proj_resume_test", input=project_input, running_cost_usd=0.5)
    project.scenes = [ok_scene, bad_scene]
    return project


def test_resume_scene_with_image_resolves_target_scene_only(monkeypatch):
    # _project_with_two_scenes has exactly one needs_manual_fix scene, so
    # resuming it fully resolves the project and would trigger a real
    # assembly.assemble() (real ffmpeg subprocess) against fake stub://
    # clip URLs, which would fail — mock it out; this test isn't about
    # assembly.
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", MagicMock(return_value="media/proj_resume_test.mp4"))
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    updated = resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent)

    bad_scene = next(s for s in updated.scenes if s.scene_id == "scene_bad")
    ok_scene = next(s for s in updated.scenes if s.scene_id == "scene_ok")
    assert bad_scene.needs_manual_fix is False
    assert bad_scene.render is not None
    assert bad_scene.render.status == "done"
    assert bad_scene.candidates[-1].image_url == "stub://fixed.png"
    assert bad_scene.candidates[-1].generated_by == "manual_upload"
    assert len(ok_scene.candidates) == 1


def test_resume_scene_with_image_triggers_assembly_when_last_unresolved_scene(monkeypatch):
    mock_assemble = MagicMock(return_value="media/proj_resume_test.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    updated = resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent)

    assert updated.output_video_url == "media/proj_resume_test.mp4"
    clip_paths_arg, output_path_arg = mock_assemble.call_args[0]
    assert output_path_arg == "media/proj_resume_test.mp4"
    assert clip_paths_arg == [updated.scenes[0].render.clip_url, updated.scenes[1].render.clip_url]


def test_resume_scene_with_image_raises_when_scene_not_found():
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(PipelineError):
        resume_scene_with_image(project, "scene_missing", "stub://fixed.png", render_agent)


def test_resume_scene_with_image_raises_when_scene_does_not_need_fix():
    project = _project_with_two_scenes(bad_needs_fix=False)
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(PipelineError):
        resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent)


def test_resume_scene_with_image_checkpoints_render_before_assembly_failure(tmp_path, monkeypatch):
    mock_assemble = MagicMock(side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]))
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))
    store = ProjectStore(tmp_path)

    with pytest.raises(PipelineError):
        resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent, project_store=store)

    reloaded = store.load(project.project_id)
    bad_scene = next(s for s in reloaded.scenes if s.scene_id == "scene_bad")
    assert bad_scene.needs_manual_fix is False
    assert bad_scene.render is not None
    assert bad_scene.render.status == "done"


def _project_with_one_scene_needing_fix() -> Project:
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=5, brief="Halloween Event")
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    bad_scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    project = Project(project_id="proj_resume_single_scene_test", input=project_input)
    project.scenes = [bad_scene]
    return project


def test_resume_scene_with_image_assemble_false_skips_assembly_even_when_fully_resolved(monkeypatch):
    mock_assemble = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project = _project_with_one_scene_needing_fix()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    updated = resume_scene_with_image(
        project, "scene_bad", "stub://fixed.png", render_agent, assemble=False
    )

    bad_scene = next(s for s in updated.scenes if s.scene_id == "scene_bad")
    assert bad_scene.needs_manual_fix is False
    assert bad_scene.render is not None
    assert updated.output_video_url is None
    mock_assemble.assert_not_called()


def test_resume_scene_with_image_persists_via_project_store_when_given(tmp_path, monkeypatch):
    # Same reasoning as test_resume_scene_with_image_resolves_target_scene_only:
    # this fully resolves the project, so mock assembly to avoid a real
    # ffmpeg call against fake stub:// clip URLs.
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", MagicMock(return_value="media/proj_resume_test.mp4"))
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))
    store = ProjectStore(tmp_path)

    resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent, project_store=store)

    reloaded = store.load(project.project_id)
    assert reloaded.scenes[1].needs_manual_fix is False


class TwoBeatPlanningAgent:
    def run(self, project_input):
        return Narrative(
            beats=[
                Beat(beat_id="setup", description="beat one", tone="calm"),
                Beat(beat_id="conflict", description="beat two", tone="tense"),
            ]
        )

    def estimate_cost(self):
        return 0.0


class RegenerateNTimesThenAcceptDirectorAgent:
    def __init__(self, regenerate_count):
        self.calls = 0
        self.regenerate_count = regenerate_count

    def run(self, scene, review):
        self.calls += 1
        if self.calls <= self.regenerate_count:
            return DirectorDecision(decision="regenerate", feedback="try again", decided_by="fake-director")
        return DirectorDecision(decision="accept", decided_by="fake-director")

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_passes_first_accepted_scene_image_as_reference_to_later_scenes():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    image_agent = CountingScratchImageAgent()

    project = run_pipeline(
        project_input,
        planning_agent=TwoBeatPlanningAgent(),
        prompt_agent=FakePromptAgent(),
        image_agent=image_agent,
        review_agent=FakeReviewAgent(),
        director_agent=FakeDirectorAgent(),
    )

    assert len(project.scenes) == 2
    assert len(image_agent.calls) == 2
    first_scene_image_url = project.scenes[0].candidates[0].image_url
    assert image_agent.reference_image_urls_calls[0] is None
    assert image_agent.reference_image_urls_calls[1] == [first_scene_image_url]


def test_run_pipeline_uses_no_reference_when_earlier_scenes_never_resolved():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    image_agent = CountingScratchImageAgent()
    # Scene 1 has max_retries=3 (4 attempts total) and never gets accepted;
    # scene 2's first attempt does.
    director_agent = RegenerateNTimesThenAcceptDirectorAgent(regenerate_count=4)

    project = run_pipeline(
        project_input,
        planning_agent=TwoBeatPlanningAgent(),
        prompt_agent=FeedbackRevisingPromptAgent(),
        image_agent=image_agent,
        review_agent=FakeReviewAgent(),
        director_agent=director_agent,
    )

    assert project.scenes[0].needs_manual_fix is True
    assert project.scenes[0].accepted_candidate_id is None
    assert project.scenes[1].accepted_candidate_id is not None
    assert image_agent.reference_image_urls_calls[:4] == [None, None, None, None]
    assert image_agent.reference_image_urls_calls[4] is None


def test_run_pipeline_stops_early_when_should_cancel_returns_true():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=20, brief="Halloween Event"
    )
    call_count = {"n": 0}

    def should_cancel():
        call_count["n"] += 1
        return call_count["n"] > 1

    project = run_pipeline(project_input, assemble=True, should_cancel=should_cancel)

    assert len(project.scenes) == 1
    assert project.output_video_url is None


def test_run_pipeline_runs_all_scenes_when_should_cancel_is_none():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=20, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert len(project.scenes) == 4
