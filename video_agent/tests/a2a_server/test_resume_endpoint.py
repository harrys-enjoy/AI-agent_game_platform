from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from PIL import Image

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent
from video_draft_pipeline.image_normalize import TARGET_HEIGHT, TARGET_WIDTH
from video_draft_pipeline.project_store import ProjectStore
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
from video_draft_pipeline.render_backends.veo_backend import VeoBackendError
from video_draft_pipeline.schema import Candidate, Project, ProjectInput, Prompts, RenderResult, Scene, Storyboard


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (150, 60, 30))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _stub_render_agent_fn():
    return VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))


def _project_input() -> ProjectInput:
    return ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="테스트")


def _storyboard() -> Storyboard:
    return Storyboard(camera="c", subject="s", action="a", setting="set")


def _setup_app(tmp_path, scenes):
    media_dir = tmp_path / "media"
    project_store = ProjectStore(media_dir / "a2a_server" / "projects")
    project = Project(project_id="proj_resume_endpoint_test", input=_project_input())
    project.scenes = scenes
    project_store.save(project)

    store = TaskStore()
    record = store.create()
    store.set_project_id(record.task_id, project.project_id)
    store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    app = create_app(
        task_store=store,
        media_dir=str(media_dir),
        project_store=project_store,
        resume_render_agent_fn=_stub_render_agent_fn,
    )
    return TestClient(app), record.task_id, project.project_id, store


def test_resume_endpoint_fully_resolves_and_assembles(tmp_path, monkeypatch):
    mock_assemble = MagicMock(return_value="media/proj_resume_endpoint_test.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        accepted_candidate_id="cand_ok",
        candidates=[Candidate(candidate_id="cand_ok", image_url="stub://ok.png", generated_by="m")],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url="stub://veo/cand_ok.mp4", cost_usd=0.5),
    )
    bad_scene = Scene(
        scene_id="scene_bad", beat_id="conflict", order=2, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, _, _ = _setup_app(tmp_path, [ok_scene, bad_scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_bad/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scene_id"] == "scene_bad"
    assert body["resolved"] is True
    assert body["remaining_unresolved"] == []
    assert body["output_video_url"] == "http://localhost:8002/media/proj_resume_endpoint_test.mp4"


def test_resume_endpoint_leaves_other_unresolved_scenes_pending(tmp_path):
    target_scene = Scene(
        scene_id="scene_target", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://bad.png", generated_by="m")],
    )
    other_scene = Scene(
        scene_id="scene_other", beat_id="conflict", order=2, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_2", image_url="stub://bad2.png", generated_by="m")],
    )
    client, task_id, _, _ = _setup_app(tmp_path, [target_scene, other_scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_target/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert len(body["remaining_unresolved"]) == 1
    remaining = body["remaining_unresolved"][0]
    assert remaining["sceneId"] == "scene_other"
    assert remaining["imageUrl"] == "http://localhost:8002/stub://bad2.png"
    assert remaining["issues"] == []
    assert "referenceImageUrl" in remaining
    assert remaining["referenceImageUrl"].startswith("http://localhost:8002/")
    assert body["output_video_url"] is None


def test_resume_endpoint_404_for_unknown_task(tmp_path):
    media_dir = tmp_path / "media"
    app = create_app(
        task_store=TaskStore(),
        media_dir=str(media_dir),
        project_store=ProjectStore(media_dir / "a2a_server" / "projects"),
        resume_render_agent_fn=_stub_render_agent_fn,
    )
    client = TestClient(app)

    response = client.post(
        "/tasks/does-not-exist/scenes/scene_x/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


def test_resume_endpoint_404_for_unknown_scene(tmp_path):
    scene = Scene(
        scene_id="scene_real", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, _, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_missing/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


class _RaisingBackend:
    def __init__(self, exc):
        self._exc = exc

    def estimate_cost(self, duration_sec):
        return 0.0

    def render(self, candidate, motion_prompt, duration_sec):
        raise self._exc


def test_resume_endpoint_503_when_veo_backend_raises(tmp_path):
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    media_dir = tmp_path / "media"
    project_store = ProjectStore(media_dir / "a2a_server" / "projects")
    project = Project(project_id="proj_veo_error_test", input=_project_input())
    project.scenes = [scene]
    project_store.save(project)

    store = TaskStore()
    record = store.create()
    store.set_project_id(record.task_id, project.project_id)
    store.mark_completed(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    app = create_app(
        task_store=store,
        media_dir=str(media_dir),
        project_store=project_store,
        resume_render_agent_fn=lambda: VideoRenderAgent(backend=_RaisingBackend(VeoBackendError("boom"))),
    )
    client = TestClient(app)

    response = client.post(
        f"/tasks/{record.task_id}/scenes/scene_bad/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["status"] == "UNAVAILABLE"


def test_resume_endpoint_503_when_resume_render_agent_fn_raises_missing_api_key(tmp_path):
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    media_dir = tmp_path / "media"
    project_store = ProjectStore(media_dir / "a2a_server" / "projects")
    project = Project(project_id="proj_missing_key_test", input=_project_input())
    project.scenes = [scene]
    project_store.save(project)

    store = TaskStore()
    record = store.create()
    store.set_project_id(record.task_id, project.project_id)
    store.mark_completed(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    def _raise_missing_key():
        raise MissingAPIKeyError("no VEO_API_KEY")

    app = create_app(
        task_store=store,
        media_dir=str(media_dir),
        project_store=project_store,
        resume_render_agent_fn=_raise_missing_key,
    )
    client = TestClient(app)

    response = client.post(
        f"/tasks/{record.task_id}/scenes/scene_bad/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["status"] == "UNAVAILABLE"


def test_resume_endpoint_works_via_project_id_when_task_store_has_no_record(tmp_path, monkeypatch):
    # Simulates a server restart: the in-memory TaskStore is empty (no
    # record for this project's original task_id at all), but the
    # ProjectStore is durable on disk. The caller substitutes the
    # project_id for the task_id path segment.
    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.assembly.assemble",
        MagicMock(return_value="media/proj_after_restart_test.mp4"),
    )
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    media_dir = tmp_path / "media"
    project_store = ProjectStore(media_dir / "a2a_server" / "projects")
    project = Project(project_id="proj_after_restart_test", input=_project_input())
    project.scenes = [scene]
    project_store.save(project)

    app = create_app(
        task_store=TaskStore(),
        media_dir=str(media_dir),
        project_store=project_store,
        resume_render_agent_fn=_stub_render_agent_fn,
    )
    client = TestClient(app)

    response = client.post(
        f"/tasks/{project.project_id}/scenes/scene_bad/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True


def test_resume_endpoint_400_for_scene_not_needing_fix(tmp_path):
    scene = Scene(
        scene_id="scene_fine", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        accepted_candidate_id="cand_1",
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://ok.png", generated_by="m")],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url="stub://veo/cand_1.mp4", cost_usd=0.5),
    )
    client, task_id, _, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_fine/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_resume_endpoint_rejects_unreadable_upload_content(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.assembly.assemble",
        MagicMock(return_value="media/proj_resume_endpoint_test.mp4"),
    )
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, project_id, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_bad/resume",
        files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"

    upload_dir = tmp_path / "media" / "manual_uploads"
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == []


def test_resume_endpoint_accepts_real_image_regardless_of_filename_extension(tmp_path, monkeypatch):
    # Content is validated by actually decoding it as an image, not by
    # trusting the uploaded filename's extension -- a real image uploaded
    # under a misleading filename should still succeed.
    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.assembly.assemble",
        MagicMock(return_value="media/proj_resume_endpoint_test.mp4"),
    )
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, project_id, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_bad/resume",
        files={"file": ("photo.html", _png_bytes(4000, 3000), "text/html")},
    )

    assert response.status_code == 200

    upload_dir = tmp_path / "media" / "manual_uploads"
    uploaded_files = list(upload_dir.iterdir())
    assert len(uploaded_files) == 1
    assert uploaded_files[0].suffix == ".png"


def test_resume_endpoint_normalizes_uploaded_image_to_target_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.assembly.assemble",
        MagicMock(return_value="media/proj_resume_endpoint_test.mp4"),
    )
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, project_id, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_bad/resume",
        files={"file": ("huge.png", _png_bytes(4000, 3000), "image/png")},
    )

    assert response.status_code == 200

    upload_dir = tmp_path / "media" / "manual_uploads"
    uploaded_files = list(upload_dir.iterdir())
    assert len(uploaded_files) == 1
    with Image.open(uploaded_files[0]) as saved_image:
        assert saved_image.size == (TARGET_WIDTH, TARGET_HEIGHT)


def test_resume_endpoint_moves_task_to_input_required_when_scenes_remain(tmp_path):
    target_scene = Scene(
        scene_id="scene_target", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://bad.png", generated_by="m")],
    )
    other_scene = Scene(
        scene_id="scene_other", beat_id="conflict", order=2, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_2", image_url="stub://bad2.png", generated_by="m")],
    )
    client, task_id, _, store = _setup_app(tmp_path, [target_scene, other_scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_target/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 200
    updated = store.get(task_id)
    assert updated.state == "TASK_STATE_INPUT_REQUIRED"
    assert updated.unresolved_scenes is not None
    assert len(updated.unresolved_scenes) == 1
    assert updated.unresolved_scenes[0]["sceneId"] == "scene_other"


def test_resume_endpoint_marks_task_completed_when_last_scene_resolved(tmp_path, monkeypatch):
    mock_assemble = MagicMock(return_value="media/proj_resume_endpoint_test.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, _, store = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_bad/resume",
        files={"file": ("fixed.png", _png_bytes(1920, 1080), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["resolved"] is True
    updated = store.get(task_id)
    assert updated.state == "TASK_STATE_COMPLETED"
    assert updated.output_video_url is not None
    assert "완성" in updated.answer
