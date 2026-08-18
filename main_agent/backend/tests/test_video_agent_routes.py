import httpx
from fastapi.testclient import TestClient

from app.main import app


def test_create_video_agent_task_proxies_message_send(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        assert url == "http://video-agent:8002/a2a/message:send"
        assert headers["A2A-Version"] == "1.0"
        assert json["message"]["parts"] == [{"text": "15초 이벤트 영상 만들어줘"}]
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_SUBMITTED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks", json={"message": "15초 이벤트 영상 만들어줘"})

    assert response.status_code == 200
    assert response.json()["task"]["id"] == "task_1"


def test_create_video_agent_task_returns_clarifying_question_response(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        return httpx.Response(200, json={"message": {"parts": [{"text": "어떤 영상을 원하시나요?"}]}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks", json={"message": "안녕"})

    assert response.status_code == 200
    assert response.json()["message"]["parts"][0]["text"] == "어떤 영상을 원하시나요?"


def test_create_video_agent_task_returns_502_when_unreachable(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks", json={"message": "브리프"})

    assert response.status_code == 502


def test_get_video_agent_task_proxies_and_includes_a2a_version_header(monkeypatch):
    seen = {}

    async def fake_get(self, url, *, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_WORKING"}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = TestClient(app).get("/api/video-agent/tasks/task_1")

    assert response.status_code == 200
    assert seen["url"] == "http://video-agent:8002/a2a/tasks/task_1"
    assert seen["headers"]["A2A-Version"] == "1.0"
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_WORKING"


def test_get_video_agent_task_maps_not_found_error(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(
            404,
            json={"error": {"code": 404, "status": "NOT_FOUND", "message": "Unknown task: task_x"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = TestClient(app).get("/api/video-agent/tasks/task_x")

    assert response.status_code == 404
    assert "Unknown task: task_x" in response.json()["detail"]["message"]


def test_get_video_agent_task_returns_502_on_malformed_response(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(200, text="not json", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = TestClient(app).get("/api/video-agent/tasks/task_1")

    assert response.status_code == 502


def test_cancel_video_agent_task_proxies_to_cancel_endpoint(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        assert url == "http://video-agent:8002/a2a/tasks/task_1:cancel"
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_CANCELED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks/task_1/cancel")

    assert response.status_code == 200
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_CANCELED"


def test_cancel_video_agent_task_forwards_terminal_task_error(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        return httpx.Response(
            400,
            json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "Task already terminal"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks/task_1/cancel")

    assert response.status_code == 400
    assert "already terminal" in response.json()["detail"]["message"]
