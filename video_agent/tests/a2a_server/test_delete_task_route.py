from pathlib import Path

from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.project_store import ProjectStore
from video_draft_pipeline.schema import Project, ProjectInput

_AUTH_HEADERS = {"Authorization": "Bearer test-token", "A2A-Version": "1.0"}


def _app_and_client(store, tmp_path, monkeypatch, project_store=None):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(task_store=store, media_dir=str(tmp_path), project_store=project_store)
    return TestClient(app)


def test_delete_task_requires_auth(tmp_path, monkeypatch):
    client = _app_and_client(TaskStore(), tmp_path, monkeypatch)

    response = client.delete("/a2a/tasks/does-not-exist")

    assert response.status_code == 401


def test_delete_task_returns_404_for_unknown_task(tmp_path, monkeypatch):
    client = _app_and_client(TaskStore(), tmp_path, monkeypatch)

    response = client.delete("/a2a/tasks/does-not-exist", headers=_AUTH_HEADERS)

    assert response.status_code == 404


def test_delete_task_refuses_in_progress_task(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_working(record.task_id)
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.delete(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    assert response.status_code == 400
    assert store.get(record.task_id) is not None


def test_delete_task_removes_record_video_file_and_project_json(tmp_path, monkeypatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    video_path = media_dir / "a2a_server" / "proj_x.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"fake video bytes")

    project_store = ProjectStore(str(media_dir / "a2a_server" / "projects"))
    project_store.save(
        Project(project_id="proj_x", input=ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="브리프"))
    )

    store = TaskStore()
    record = store.create(brief="브리프")
    store.set_project_id(record.task_id, "proj_x")
    store.mark_completed(
        record.task_id, "완료", output_video_url="http://localhost:8002/media/a2a_server/proj_x.mp4"
    )
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(task_store=store, media_dir=str(media_dir), project_store=project_store)
    client = TestClient(app)

    response = client.delete(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"deleted": record.task_id}
    assert store.get(record.task_id) is None
    assert not video_path.exists()
    assert not (media_dir / "a2a_server" / "projects" / "proj_x.json").exists()


def test_delete_task_with_no_video_or_project_still_succeeds(tmp_path, monkeypatch):
    """A failed-before-rendering task has no output video or project_id -
    deletion must not crash trying to unlink files that never existed."""

    store = TaskStore()
    record = store.create()
    store.mark_failed(record.task_id, "실패")
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.delete(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert store.get(record.task_id) is None
