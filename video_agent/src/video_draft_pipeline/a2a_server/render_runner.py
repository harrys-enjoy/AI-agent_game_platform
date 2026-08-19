import logging
import traceback
from typing import Callable

from ..agents.errors import MissingAPIKeyError
from ..agents.factory import build_real_agents
from ..agents.video_render_agent import VideoRenderAgent
from ..orchestrator import PipelineError, first_accepted_image_url, format_candidate_diagnostics, run_pipeline
from ..project_store import ProjectStore
from ..render_backends.veo_backend import VeoBackend, VeoBackendError
from ..schema import Project, ProjectInput

OUTPUT_DIR = "media/a2a_server"
PROJECT_STORE_DIR = f"{OUTPUT_DIR}/projects"

logger = logging.getLogger(__name__)


def default_render(project_input: ProjectInput, should_cancel: Callable[[], bool] | None = None) -> Project:
    agents = build_real_agents(output_dir=OUTPUT_DIR, log_path=f"{OUTPUT_DIR}/agent_log.jsonl")
    backend = VeoBackend(tier="veo-3.1-fast", output_dir=OUTPUT_DIR)
    project_store = ProjectStore(PROJECT_STORE_DIR)
    return run_pipeline(
        project_input, render_backend=backend, assemble=True, project_store=project_store,
        should_cancel=should_cancel, **agents
    )


def default_resume_render_agent() -> VideoRenderAgent:
    return VideoRenderAgent(backend=VeoBackend(tier="veo-3.1-fast", output_dir=OUTPUT_DIR))


def _unresolved_scenes_message(project: Project, media_public_base_url: str, task_id: str) -> str:
    lines = ["일부 장면에 수동 수정이 필요합니다:"]
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_image_url = f"{media_public_base_url}/{scene.candidates[-1].image_url}"
        lines.append(f"- {scene.scene_id}: {last_image_url}")
        lines.append(format_candidate_diagnostics(scene.candidates))
    lines.append(
        f"수정한 이미지를 POST /tasks/{task_id}/scenes/{{scene_id}}/resume 로 업로드해 주세요."
    )
    return "\n".join(lines)


def build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]:
    anchor_image_url = first_accepted_image_url(project.scenes)
    reference_image_url = f"{media_public_base_url}/{anchor_image_url}" if anchor_image_url else None
    entries = []
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_candidate = scene.candidates[-1]
        review = last_candidate.consistency_review
        entries.append({
            "sceneId": scene.scene_id,
            "imageUrl": f"{media_public_base_url}/{last_candidate.image_url}",
            "issues": review.issues if review else [],
            "referenceImageUrl": reference_image_url,
        })
    return entries


def run_render_task(
    task_store,
    task_id: str,
    project_input: ProjectInput,
    media_public_base_url: str,
    render_fn: Callable[[ProjectInput], Project] | None = None,
) -> None:
    def should_cancel() -> bool:
        record = task_store.get(task_id)
        return record is not None and record.cancel_requested

    actual_render_fn = render_fn or (lambda pi: default_render(pi, should_cancel=should_cancel))

    try:
        project = actual_render_fn(project_input)
    except (PipelineError, VeoBackendError, MissingAPIKeyError) as exc:
        if not should_cancel():
            task_store.mark_failed(task_id, f"영상 생성에 실패했습니다: {exc}", detail=traceback.format_exc())
        return
    except Exception:
        logger.exception("render_runner: unexpected error during render")
        if not should_cancel():
            task_store.mark_failed(
                task_id, "영상 생성 중 알 수 없는 오류가 발생했습니다.", detail=traceback.format_exc()
            )
        return

    if should_cancel():
        return

    task_store.set_project_id(task_id, project.project_id)

    if any(scene.needs_manual_fix for scene in project.scenes):
        unresolved = build_unresolved_scenes(project, media_public_base_url)
        task_store.set_unresolved_scenes(task_id, unresolved)
        task_store.mark_input_required(task_id, _unresolved_scenes_message(project, media_public_base_url, task_id))
        return

    url = f"{media_public_base_url}/{project.output_video_url}"
    task_store.mark_completed(task_id, f"영상 초안이 완성되었습니다.\n{url}", output_video_url=url)
