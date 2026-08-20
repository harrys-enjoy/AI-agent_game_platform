from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.tasks import TaskStore

_AUTH_HEADERS = {"Authorization": "Bearer test-token", "A2A-Version": "1.0"}


def _app_and_client(store, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(task_store=store, media_dir=str(tmp_path))
    return TestClient(app)


def test_list_tasks_requires_auth(tmp_path, monkeypatch):
    client = _app_and_client(TaskStore(), tmp_path, monkeypatch)

    response = client.get("/a2a/tasks?user_id=u1")

    assert response.status_code == 401


def test_list_tasks_returns_flat_task_objects_not_wrapped(tmp_path, monkeypatch):
    """Regression test: the endpoint previously returned each item as
    {"task": {...}} (leaking _task_response()'s single-task wrapper into
    the list), so task.status was undefined client-side and crashed the
    gallery page. Each list entry must be the flat task object itself.
    """

    store = TaskStore()
    record = store.create(user_id="u1", brief="테스트 브리프")
    store.mark_completed(record.task_id, "완료", output_video_url="http://x/p.mp4")
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get("/a2a/tasks?user_id=u1", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert "task" not in body["tasks"][0]
    assert body["tasks"][0]["id"] == record.task_id
    assert body["tasks"][0]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert body["tasks"][0]["brief"] == "테스트 브리프"


def test_list_tasks_only_returns_matching_user(tmp_path, monkeypatch):
    store = TaskStore()
    store.create(user_id="u1")
    store.create(user_id="u2")
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get("/a2a/tasks?user_id=u1", headers=_AUTH_HEADERS)

    body = response.json()
    assert len(body["tasks"]) == 1


def test_list_tasks_paginates_with_has_more(tmp_path, monkeypatch):
    store = TaskStore()
    for _ in range(3):
        store.create(user_id="u1")
    client = _app_and_client(store, tmp_path, monkeypatch)

    first_page = client.get("/a2a/tasks?user_id=u1&limit=2&offset=0", headers=_AUTH_HEADERS).json()
    second_page = client.get("/a2a/tasks?user_id=u1&limit=2&offset=2", headers=_AUTH_HEADERS).json()

    assert len(first_page["tasks"]) == 2
    assert first_page["has_more"] is True
    assert len(second_page["tasks"]) == 1
    assert second_page["has_more"] is False
