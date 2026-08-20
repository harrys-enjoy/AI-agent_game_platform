import os
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .agent_card import build_agent_card
from .auth import A2AAuthError, require_a2a_auth
from .brief_intake import BriefIntakeAgent, BriefIntakeError, IntakeResult
from .errors import error_response
from .protocol import (
    ProtocolError,
    TaskState,
    build_task_response,
    build_unresolved_artifact,
    build_video_artifact,
    extract_text,
    parse_message_send_request,
)
from .render_runner import build_unresolved_scenes, default_resume_render_agent, run_render_task
from .task_repository import task_repository
from .tasks import TaskStore
from ..agents.errors import MissingAPIKeyError
from ..agents.video_render_agent import VideoRenderAgent
from ..image_normalize import ImageNormalizeError, normalize_image_bytes
from ..orchestrator import PipelineError, resume_scene_with_image
from ..project_store import ProjectStore, ProjectStoreError
from ..render_backends.veo_backend import VeoBackendError
from ..schema import Project, ProjectInput

SERVER_MAX_BUDGET_USD = float(os.environ.get("SERVER_MAX_BUDGET_USD", "5.00"))
_TERMINAL_STATES = {
    TaskState.COMPLETED.value,
    TaskState.FAILED.value,
    TaskState.CANCELED.value,
    TaskState.REJECTED.value,
}


def _project_input_from_intake(intake: IntakeResult) -> ProjectInput:
    kwargs = {
        "preset": intake.preset or "이벤트",
        "scene_type": intake.scene_type or "인게임",
        "duration_sec": intake.duration_sec or 10,
        "brief": intake.brief,
    }
    if intake.max_budget_usd is not None:
        kwargs["max_budget_usd"] = min(intake.max_budget_usd, SERVER_MAX_BUDGET_USD)
    return ProjectInput(**kwargs)


def _task_response(record, media_public_base_url: str) -> dict:
    artifacts = None
    if record.state == TaskState.COMPLETED.value and record.output_video_url:
        artifacts = [build_video_artifact(record.artifact_id, record.answer, record.output_video_url)]
    elif record.state == TaskState.INPUT_REQUIRED.value and record.unresolved_scenes:
        artifacts = [build_unresolved_artifact(record.artifact_id, record.unresolved_scenes)]
    return build_task_response(
        record.task_id,
        record.context_id,
        record.state,
        answer=record.answer,
        detail=record.detail,
        unresolved_scenes=record.unresolved_scenes if record.state == TaskState.INPUT_REQUIRED.value else None,
        artifacts=artifacts,
    )


def create_app(
    self_internal_url: str | None = None,
    media_public_base_url: str | None = None,
    media_dir: str = "media",
    task_store: TaskStore | None = None,
    intake_agent: BriefIntakeAgent | None = None,
    render_fn: Callable[[ProjectInput], Project] | None = None,
    project_store: ProjectStore | None = None,
    resume_render_agent_fn: Callable[[], VideoRenderAgent] = default_resume_render_agent,
) -> FastAPI:
    internal_url = self_internal_url or os.environ.get("SELF_INTERNAL_URL", "http://video-agent:8002")
    # NOTE: this default is plain in-memory on purpose - test_app_scaffold.py calls
    # create_app() with no task_store override, and shouldn't touch a real SQLite
    # file on disk. The real server wires persistence explicitly at the bottom of
    # this module (`app = create_app(task_store=TaskStore(repository=task_repository()))`).
    store = task_store or TaskStore()
    media_url = media_public_base_url or os.environ.get("MEDIA_PUBLIC_BASE_URL", "http://localhost:8002")
    store_for_projects = project_store or ProjectStore(str(Path(media_dir) / "a2a_server" / "projects"))

    app = FastAPI()
    app.state.media_public_base_url = media_url
    app.state.task_store = store

    @app.exception_handler(A2AAuthError)
    def _handle_auth_error(request: Request, exc: A2AAuthError):
        return error_response("UNAUTHENTICATED", exc.message)

    Path(media_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict:
        return build_agent_card(internal_url)

    @app.get("/a2a/tasks/{task_id}", dependencies=[Depends(require_a2a_auth)])
    def get_task(task_id: str):
        record = store.get(task_id)
        if record is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")
        return _task_response(record, media_url)

    @app.get("/a2a/tasks", dependencies=[Depends(require_a2a_auth)])
    def list_tasks(user_id: str):
        return {"tasks": [_task_response(record, media_url) for record in store.list_for_user(user_id)]}

    @app.post("/a2a/message:send", dependencies=[Depends(require_a2a_auth)])
    async def message_send(
        request: Request,
        background_tasks: BackgroundTasks,
        x_video_agent_user: str | None = Header(default=None, alias="X-Video-Agent-User"),
    ):
        try:
            body = await request.json()
        except ValueError:
            return error_response("INVALID_ARGUMENT", "Request body must be valid JSON")
        if not isinstance(body, dict):
            return error_response("INVALID_ARGUMENT", "Request body must be a JSON object")

        try:
            message = parse_message_send_request(body)
        except ProtocolError as exc:
            return error_response(exc.status, exc.message)

        is_first_claim, existing_task_id = store.claim_message_id(message.messageId)
        if not is_first_claim:
            if existing_task_id is not None:
                return _task_response(store.get(existing_task_id), media_url)
            return error_response("UNAVAILABLE", "A request with this messageId is already being processed")

        registered = False
        try:
            text = extract_text(message)
            if not text:
                return error_response("INVALID_ARGUMENT", "message.parts must include non-empty text")

            try:
                agent = intake_agent or BriefIntakeAgent()
                intake = await run_in_threadpool(agent.run, text)
            except MissingAPIKeyError as exc:
                return error_response("UNAVAILABLE", str(exc))
            except BriefIntakeError as exc:
                return error_response("UNAVAILABLE", str(exc))

            if intake.clarifying_question:
                return {"message": {"parts": [{"text": intake.clarifying_question}]}}

            try:
                project_input = _project_input_from_intake(intake)
            except ValidationError as exc:
                return error_response("INVALID_ARGUMENT", str(exc))

            user_id = unquote(x_video_agent_user) if x_video_agent_user else None
            record = store.create(user_id=user_id)
            store.register_message_id(message.messageId, record.task_id)
            registered = True
            store.mark_working(record.task_id)
            background_tasks.add_task(run_render_task, store, record.task_id, project_input, media_url, render_fn)
            return _task_response(store.get(record.task_id), media_url)
        finally:
            if not registered:
                store.release_message_id(message.messageId)

    @app.post("/a2a/tasks/{task_id}:cancel", dependencies=[Depends(require_a2a_auth)])
    def cancel_task(task_id: str):
        record = store.get(task_id)
        if record is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")
        if record.state not in _TERMINAL_STATES:
            store.request_cancel(task_id)
            record = store.get(task_id)
        return _task_response(record, media_url)

    @app.post("/tasks/{task_id}/scenes/{scene_id}/resume")
    async def resume_scene(task_id: str, scene_id: str, file: UploadFile = File(...)):
        record = store.get(task_id)
        if record is not None and record.project_id is not None:
            project_id = record.project_id
        else:
            # Fallback: the in-memory TaskStore is empty after a server
            # restart, but ProjectStore is durable on disk. Accept task_id
            # doubling as a project_id (task_/proj_ prefixes never collide)
            # so a human can still resume using the project's own id.
            project_id = task_id

        try:
            project = store_for_projects.load(project_id)
        except ProjectStoreError as exc:
            return error_response("NOT_FOUND", str(exc))

        scene = next((s for s in project.scenes if s.scene_id == scene_id), None)
        if scene is None:
            return error_response("NOT_FOUND", f"Unknown scene: {scene_id}")
        if not scene.needs_manual_fix:
            return error_response("INVALID_ARGUMENT", f"Scene {scene_id} does not need a manual fix")

        contents = await file.read()
        try:
            contents = normalize_image_bytes(contents)
        except ImageNormalizeError as exc:
            return error_response("INVALID_ARGUMENT", str(exc))

        upload_dir = Path(media_dir) / "manual_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        # normalize_image_bytes always re-encodes as PNG, so the saved file
        # is always .png regardless of the uploaded filename's extension.
        image_path = upload_dir / f"{project.project_id}_{scene_id}_{uuid.uuid4().hex[:8]}.png"
        image_path.write_bytes(contents)

        try:
            project = await run_in_threadpool(
                resume_scene_with_image,
                project,
                scene_id,
                str(image_path),
                resume_render_agent_fn(),
                store_for_projects,
            )
        except (PipelineError, VeoBackendError, MissingAPIKeyError) as exc:
            return error_response("UNAVAILABLE", str(exc))

        remaining = build_unresolved_scenes(project, media_url)
        output_video_url = f"{media_url}/{project.output_video_url}" if project.output_video_url else None

        if record is not None:
            if remaining:
                store.set_unresolved_scenes(record.task_id, remaining)
                store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")
            else:
                answer = f"영상 초안이 완성되었습니다.\n{output_video_url}" if output_video_url else "영상 초안이 완성되었습니다."
                store.mark_completed(record.task_id, answer, output_video_url=output_video_url)

        return {
            "scene_id": scene_id,
            "resolved": True,
            "remaining_unresolved": remaining,
            "output_video_url": output_video_url,
        }

    return app


app = create_app(task_store=TaskStore(repository=task_repository()))
