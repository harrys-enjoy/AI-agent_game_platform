import subprocess
import uuid
from pathlib import Path
from typing import Callable

from . import assembly
from .schema import BeatId, Candidate, DirectorDecision, Project, ProjectInput, Scene
from .project_store import ProjectStore
from .config import ModelConfig
from .guards import duration_guard, budget_guard, DurationExceededError, BudgetExceededError
from .agents.planning_agent import PlanningAgent
from .agents.storyboard_agent import StoryboardAgent
from .agents.prompt_agent import PromptAgent
from .agents.image_agent import ImageAgent
from .agents.image_edit_agent import ImageEditAgent
from .agents.review_agent import ReviewAgent
from .agents.director_agent import DirectorAgent
from .agents.video_render_agent import VideoRenderAgent
from .render_backends.base import RenderBackend
from .render_backends.stub_backend import StubRenderBackend
from .agents.protocols import (
    DirectorAgentProtocol,
    ImageAgentProtocol,
    ImageEditAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    ReviewAgentProtocol,
    StoryboardAgentProtocol,
)


class PipelineError(Exception):
    pass


def format_candidate_diagnostics(candidates: list[Candidate]) -> str:
    lines = []
    for i, c in enumerate(candidates, start=1):
        review = c.consistency_review
        decision = c.director_decision
        issues = ", ".join(review.issues) if review and review.issues else "none"
        review_passed = review.passed if review else None
        director_decision = decision.decision if decision else None
        feedback = decision.feedback if decision else None
        lines.append(
            f"  attempt {i}: review_passed={review_passed}, issues=[{issues}], "
            f"director={director_decision}, feedback={feedback!r}"
        )
    return "\n".join(lines)


def _charge(running_cost: float, cost: float, max_budget_usd: float) -> float:
    try:
        return budget_guard(running_cost, cost, max_budget_usd)
    except BudgetExceededError as exc:
        raise PipelineError(str(exc)) from exc


def _run_assembly(project: Project, assembly_output_path: str | Path | None = None) -> None:
    output_path = str(assembly_output_path) if assembly_output_path else f"media/{project.project_id}.mp4"
    ordered_clip_paths = [
        scene.render.clip_url for scene in sorted(project.scenes, key=lambda s: s.order)
    ]
    try:
        project.output_video_url = assembly.assemble(ordered_clip_paths, output_path)
    except FileNotFoundError as exc:
        raise PipelineError(
            f"Video assembly failed: {exc}. Is ffmpeg installed and on PATH?"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(
            f"Video assembly failed: {exc}. If any scene's render backend is the stub "
            "StubRenderBackend, its stub:// clip URLs are not real files ffmpeg can read "
            "— inject a real render backend (e.g. VeoBackend, LTXBackend) to assemble "
            "real output."
        ) from exc


def first_accepted_image_url(scenes: list[Scene]) -> str | None:
    for scene in scenes:
        if scene.accepted_candidate_id is None:
            continue
        accepted = next((c for c in scene.candidates if c.candidate_id == scene.accepted_candidate_id), None)
        if accepted is not None:
            return accepted.image_url
    return None


def _generate_candidate(
    scene: Scene,
    prompt_agent: PromptAgentProtocol,
    image_agent: ImageAgentProtocol,
    image_edit_agent: ImageEditAgentProtocol,
    running_cost: float,
    max_budget_usd: float,
    reference_image_url: str | None = None,
) -> tuple[Candidate, float]:
    reference_image_urls = [reference_image_url] if reference_image_url else None

    if scene.retry_count == 0:
        running_cost = _charge(running_cost, image_agent.estimate_cost(), max_budget_usd)
        return image_agent.run(scene.prompts, reference_image_urls=reference_image_urls), running_cost

    prior_candidate = scene.candidates[-1]
    feedback = prior_candidate.director_decision.feedback or ""
    prior_review = prior_candidate.consistency_review
    defect_category = prior_review.defect_category if prior_review else "none"

    # Inpainting only makes sense for an isolated, spatially-confined defect. A
    # structural defect (bent geometry, malformed anatomy, POV mixing) comes
    # from how the whole image was composed, so an edit pass can't fix it —
    # skip straight to a full regenerate for those instead of wasting a retry.
    if defect_category == "localized_artifact" and scene.retry_count == 1:
        running_cost = _charge(running_cost, image_edit_agent.estimate_cost(), max_budget_usd)
        return image_edit_agent.run(prior_candidate, scene.prompts, feedback), running_cost

    running_cost = _charge(running_cost, prompt_agent.estimate_cost(), max_budget_usd)
    scene.prompts = prompt_agent.run(scene, feedback=feedback)
    running_cost = _charge(running_cost, image_agent.estimate_cost(), max_budget_usd)
    return image_agent.run(scene.prompts, reference_image_urls=reference_image_urls), running_cost


def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    render_backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    image_edit_agent: ImageEditAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
    director_agent: DirectorAgentProtocol | None = None,
    assemble: bool = False,
    assembly_output_path: str | Path | None = None,
    project_store: ProjectStore | None = None,
    should_cancel: "Callable[[], bool] | None" = None,
) -> Project:
    models = model_config or ModelConfig()
    project = Project(project_id=f"proj_{uuid.uuid4().hex[:8]}", input=project_input)

    planning_agent = planning_agent or PlanningAgent(models.planning_model)
    storyboard_agent = storyboard_agent or StoryboardAgent(models.storyboard_model)
    prompt_agent = prompt_agent or PromptAgent(models.prompt_model)
    image_agent = image_agent or ImageAgent(models.image_model)
    image_edit_agent = image_edit_agent or ImageEditAgent(models.image_edit_model)
    review_agent = review_agent or ReviewAgent(models.review_model)
    director_agent = director_agent or DirectorAgent(models.director_model)
    backend = render_backend or StubRenderBackend(tier=models.render_backend)
    render_agent = VideoRenderAgent(backend=backend, backend_by_beat=render_backend_by_beat)

    running_cost = 0.0

    running_cost = _charge(running_cost, planning_agent.estimate_cost(), project_input.max_budget_usd)
    narrative = planning_agent.run(project_input)
    project.narrative = narrative

    running_cost = _charge(running_cost, storyboard_agent.estimate_cost(), project_input.max_budget_usd)
    scenes = storyboard_agent.run(narrative, project_input)

    try:
        duration_guard(scenes, project_input.max_duration_sec)
    except DurationExceededError as exc:
        error = PipelineError(str(exc))
        error.project_id = project.project_id
        raise error from exc

    canceled = False
    for scene in scenes:
        if should_cancel is not None and should_cancel():
            canceled = True
            break

        running_cost = _charge(running_cost, prompt_agent.estimate_cost(), project_input.max_budget_usd)
        scene.prompts = prompt_agent.run(scene)

        reference_image_url = first_accepted_image_url(project.scenes)

        max_attempts = scene.max_retries + 1
        for _ in range(max_attempts):
            candidate, running_cost = _generate_candidate(
                scene,
                prompt_agent,
                image_agent,
                image_edit_agent,
                running_cost,
                project_input.max_budget_usd,
                reference_image_url=reference_image_url,
            )
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates, scene.prompts)
            running_cost = _charge(running_cost, director_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
            scene.candidates.append(candidate)

            if candidate.director_decision.decision == "accept":
                scene.accepted_candidate_id = candidate.candidate_id
                break
            if candidate.director_decision.decision == "reject":
                break
            scene.retry_count += 1

        if scene.accepted_candidate_id is None:
            # Retries exhausted (or DirectorAgent never reached a terminal
            # accept/reject within max_attempts) without an accepted candidate.
            # This is no longer fatal to the whole run: keep the last
            # candidate's image, skip this scene's video render, and let the
            # rest of the project finish. A human can resume this scene later
            # via resume_scene_with_image with a replacement image.
            scene.needs_manual_fix = True
        else:
            try:
                render_result = render_agent.run(scene, running_cost, project_input.max_budget_usd)
            except BudgetExceededError as exc:
                error = PipelineError(str(exc))
                error.project_id = project.project_id
                raise error from exc
            except Exception as exc:
                # Tag whatever the backend raised (VeoBackendError, LTXBackendError,
                # ...) with the project_id before it escapes run_pipeline() - by
                # this point earlier scenes (narrative/storyboard/prompts/images)
                # are already saved to project_store under this id, so the caller
                # can still link a failed task back to that partial progress
                # instead of losing it (render_runner.py reads exc.project_id).
                exc.project_id = project.project_id
                raise
            scene.render = render_result
            running_cost += render_result.cost_usd

        project.running_cost_usd = running_cost
        project.scenes.append(scene)
        if project_store is not None:
            project_store.save(project)

    if not canceled and assemble and all(not scene.needs_manual_fix for scene in project.scenes):
        _run_assembly(project, assembly_output_path)
        if project_store is not None:
            project_store.save(project)

    return project


def resume_scene_with_image(
    project: Project,
    scene_id: str,
    image_path: str,
    render_agent,
    project_store: ProjectStore | None = None,
    assemble: bool = True,
) -> Project:
    scene = next((s for s in project.scenes if s.scene_id == scene_id), None)
    if scene is None:
        raise PipelineError(f"Scene {scene_id} not found on project {project.project_id}")
    if not scene.needs_manual_fix:
        raise PipelineError(f"Scene {scene_id} does not need a manual fix; nothing to resume")

    candidate = Candidate(
        candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
        image_url=image_path,
        generated_by="manual_upload",
        director_decision=DirectorDecision(decision="accept", decided_by="human_manual_upload"),
    )
    scene.candidates.append(candidate)
    scene.accepted_candidate_id = candidate.candidate_id
    scene.needs_manual_fix = False

    try:
        render_result = render_agent.run(scene, project.running_cost_usd, project.input.max_budget_usd)
    except BudgetExceededError as exc:
        raise PipelineError(str(exc)) from exc
    scene.render = render_result
    project.running_cost_usd += render_result.cost_usd

    if project_store is not None:
        project_store.save(project)

    if assemble and all(not s.needs_manual_fix for s in project.scenes):
        _run_assembly(project)
        if project_store is not None:
            project_store.save(project)

    return project
