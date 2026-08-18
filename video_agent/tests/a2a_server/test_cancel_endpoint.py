from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.tasks import TaskStore

_AUTH_HEADERS = {"Authorization": "Bearer test-token", "A2A-Version": "1.0"}


def _client(store, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    return TestClient(create_app(task_store=store, media_dir=str(tmp_path)))


def test_cancel_task_requires_auth(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    client = _client(store, tmp_path, monkeypatch)

    response = client.post(f"/a2a/tasks/{record.task_id}:cancel")

    assert response.status_code == 401


def test_cancel_task_marks_working_task_as_canceled(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_working(record.task_id)
    client = _client(store, tmp_path, monkeypatch)

    response = client.post(f"/a2a/tasks/{record.task_id}:cancel", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_CANCELED"
    assert store.get(record.task_id).cancel_requested is True


def test_cancel_task_returns_404_for_unknown_task(tmp_path, monkeypatch):
    client = _client(TaskStore(), tmp_path, monkeypatch)

    response = client.post("/a2a/tasks/does-not-exist:cancel", headers=_AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


def test_cancel_task_on_already_completed_task_leaves_it_completed(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_completed(record.task_id, "완료", output_video_url="http://x/p.mp4")
    client = _client(store, tmp_path, monkeypatch)

    response = client.post(f"/a2a/tasks/{record.task_id}:cancel", headers=_AUTH_HEADERS)

    assert response.json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
