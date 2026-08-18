from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.tasks import TaskStore

_AUTH_HEADERS = {"Authorization": "Bearer test-token", "A2A-Version": "1.0"}


def _app_and_client(store, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(task_store=store, media_dir=str(tmp_path))
    return TestClient(app)


def test_get_task_requires_auth(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get(f"/a2a/tasks/{record.task_id}")

    assert response.status_code == 401


def test_get_task_returns_submitted_state_before_working(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["id"] == record.task_id
    assert body["task"]["contextId"] == record.context_id
    assert body["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert "message" not in body["task"]["status"]


def test_get_task_returns_completed_state_with_answer_message_and_artifact(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_completed(
        record.task_id, "영상이 완성되었습니다.\nhttp://localhost:8002/media/proj_x.mp4",
        output_video_url="http://localhost:8002/media/proj_x.mp4",
    )
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    body = response.json()
    assert body["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert body["task"]["status"]["message"]["parts"] == [
        {"text": "영상이 완성되었습니다.\nhttp://localhost:8002/media/proj_x.mp4"}
    ]
    assert body["task"]["artifacts"][0]["parts"][1]["data"]["output_video_url"] == "http://localhost:8002/media/proj_x.mp4"


def test_get_task_returns_404_for_unknown_task_id(tmp_path, monkeypatch):
    client = _app_and_client(TaskStore(), tmp_path, monkeypatch)

    response = client.get("/a2a/tasks/does-not-exist", headers=_AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


def test_get_task_includes_unresolved_scenes_and_artifact_when_input_required(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")
    store.set_unresolved_scenes(
        record.task_id,
        [{"sceneId": "scene_04", "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png", "issues": ["too wide"]}],
    )
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    body = response.json()
    assert body["task"]["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert body["task"]["status"]["unresolvedScenes"] == [
        {"sceneId": "scene_04", "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png", "issues": ["too wide"]}
    ]
    assert body["task"]["artifacts"][0]["parts"][0]["data"]["unresolvedScenes"] == body["task"]["status"]["unresolvedScenes"]


def test_get_task_omits_artifacts_key_when_still_working(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_working(record.task_id)
    client = _app_and_client(store, tmp_path, monkeypatch)

    response = client.get(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    body = response.json()
    assert "artifacts" not in body["task"]


def test_get_task_returns_stable_artifact_id_across_polls(tmp_path, monkeypatch):
    store = TaskStore()
    record = store.create()
    store.mark_completed(record.task_id, "완료", output_video_url="http://x/p.mp4")
    client = _app_and_client(store, tmp_path, monkeypatch)

    first = client.get(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)
    second = client.get(f"/a2a/tasks/{record.task_id}", headers=_AUTH_HEADERS)

    first_id = first.json()["task"]["artifacts"][0]["artifactId"]
    second_id = second.json()["task"]["artifacts"][0]["artifactId"]
    assert first_id == second_id
