from ..schema import BeatId, Scene, RenderResult, Candidate
from ..guards import budget_guard
from ..render_backends.base import RenderBackend


class VideoRenderAgent:
    def __init__(
        self,
        backend: RenderBackend,
        backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    ):
        self.backend = backend
        self.backend_by_beat = backend_by_beat or {}

    def run(self, scene: Scene, current_cost_usd: float, max_budget_usd: float) -> RenderResult:
        backend = self._select_backend(scene)
        estimated_cost = backend.estimate_cost(scene.duration_sec)
        budget_guard(current_cost_usd, estimated_cost, max_budget_usd)

        candidate = self._accepted_candidate(scene)
        motion_prompt = scene.prompts.video_motion_prompt if scene.prompts else ""
        return backend.render(
            candidate=candidate,
            motion_prompt=motion_prompt,
            duration_sec=scene.duration_sec,
        )

    def _select_backend(self, scene: Scene) -> RenderBackend:
        return self.backend_by_beat.get(scene.beat_id, self.backend)

    def _accepted_candidate(self, scene: Scene) -> Candidate:
        if scene.accepted_candidate_id is None:
            raise ValueError(f"Scene {scene.scene_id} has no accepted candidate")
        for candidate in scene.candidates:
            if candidate.candidate_id == scene.accepted_candidate_id:
                return candidate
        raise ValueError(
            f"Accepted candidate {scene.accepted_candidate_id} not found on scene {scene.scene_id}"
        )


def beat_backend_map(paid_backend: RenderBackend, free_backend: RenderBackend) -> dict[BeatId, RenderBackend]:
    return {
        "climax": paid_backend,
        "resolution": paid_backend,
        "setup": free_backend,
        "conflict": free_backend,
    }
