import pytest

from video_draft_pipeline.schema import BeatId, RenderResult, Scene, Storyboard, Candidate
from video_draft_pipeline.guards import BudgetExceededError
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent, beat_backend_map


def _scene_with_accepted_candidate(duration_sec: float = 6.0, beat_id: BeatId = "conflict") -> Scene:
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    scene = Scene(
        scene_id="scene_01",
        beat_id=beat_id,
        order=1,
        duration_sec=duration_sec,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        candidates=[candidate],
        accepted_candidate_id="c1",
    )
    scene.prompts = None
    return scene


def test_video_render_agent_renders_under_budget():
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    result = agent.run(_scene_with_accepted_candidate(6.0), current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.status == "done"
    assert result.cost_usd == 0.60


def test_video_render_agent_raises_when_over_budget():
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(BudgetExceededError):
        agent.run(_scene_with_accepted_candidate(6.0), current_cost_usd=4.5, max_budget_usd=5.0)


def test_video_render_agent_raises_without_accepted_candidate():
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6.0,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
    )
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(ValueError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)


def test_video_render_agent_raises_when_accepted_candidate_not_in_list():
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6.0,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        candidates=[candidate],
        accepted_candidate_id="does-not-exist",
    )
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(ValueError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)


class _MappedBackend:
    def __init__(self, cost: float = 0.0):
        self.cost = cost
        self.render_called = False

    def estimate_cost(self, duration_sec):
        return self.cost

    def render(self, candidate, motion_prompt, duration_sec):
        self.render_called = True
        return RenderResult(backend="veo-3.1-lite", status="done", clip_url="fake://mapped", cost_usd=self.cost)


class _DefaultBackend:
    def __init__(self, cost: float = 0.0):
        self.cost = cost
        self.render_called = False

    def estimate_cost(self, duration_sec):
        return self.cost

    def render(self, candidate, motion_prompt, duration_sec):
        self.render_called = True
        return RenderResult(backend="veo-3.1-standard", status="done", clip_url="fake://default", cost_usd=self.cost)


def test_run_routes_to_mapped_backend_for_beat_in_map():
    mapped = _MappedBackend()
    default = _DefaultBackend()
    agent = VideoRenderAgent(backend=default, backend_by_beat={"climax": mapped})
    scene = _scene_with_accepted_candidate(6.0, beat_id="climax")

    result = agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.backend == "veo-3.1-lite"
    assert mapped.render_called is True
    assert default.render_called is False


def test_run_falls_back_to_default_backend_when_beat_not_in_map():
    mapped = _MappedBackend()
    default = _DefaultBackend()
    agent = VideoRenderAgent(backend=default, backend_by_beat={"climax": mapped})
    scene = _scene_with_accepted_candidate(6.0, beat_id="setup")

    result = agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.backend == "veo-3.1-standard"
    assert default.render_called is True
    assert mapped.render_called is False


def test_run_falls_back_to_default_backend_when_backend_by_beat_not_given():
    default = _DefaultBackend()
    agent = VideoRenderAgent(backend=default)
    scene = _scene_with_accepted_candidate(6.0, beat_id="climax")

    result = agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.backend == "veo-3.1-standard"
    assert default.render_called is True


def test_run_charges_budget_guard_against_the_selected_backend_not_the_default():
    expensive_mapped = _MappedBackend(cost=100.0)
    cheap_default = _DefaultBackend(cost=0.0)
    agent = VideoRenderAgent(backend=cheap_default, backend_by_beat={"climax": expensive_mapped})
    scene = _scene_with_accepted_candidate(6.0, beat_id="climax")

    with pytest.raises(BudgetExceededError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=1.0)

    assert expensive_mapped.render_called is False
    assert cheap_default.render_called is False


def test_beat_backend_map_maps_climax_and_resolution_to_paid_setup_and_conflict_to_free():
    paid = _MappedBackend()
    free = _DefaultBackend()

    mapping = beat_backend_map(paid_backend=paid, free_backend=free)

    assert mapping == {
        "climax": paid,
        "resolution": paid,
        "setup": free,
        "conflict": free,
    }
