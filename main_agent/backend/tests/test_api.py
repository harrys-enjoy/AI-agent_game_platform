from uuid import uuid4

import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient

from app.main import app, task_log_store
from app.main import build_video_handoff_request, game_qna_agent_message, parse_game_qna_command


def test_agents_and_task_api():
    client = TestClient(app)
    agents = client.get("/api/agents")
    assert agents.status_code == 200
    response = client.post("/api/tasks", json={"request": "브리핑해줘"})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert client.get(f"/api/tasks/{task_id}").status_code == 200
    assert client.get(f"/api/tasks/{task_id}/events").status_code == 200
    assert client.post(f"/api/tasks/{task_id}/retry").status_code == 202


def test_game_qna_commands_resolve_to_catalog_modes():
    assert parse_game_qna_command("/planning 전투 시스템을 설계해줘") == {
        "kind": "request",
        "mode": "dev-guide",
        "content": "전투 시스템을 설계해줘",
        "command": "/planning",
    }
    assert parse_game_qna_command("/art") ["mode"] == "dev-guide"
    assert "Video Generation" in parse_game_qna_command("/art")["content"]
    assert parse_game_qna_command("/? video 캐릭터 등장 장면 프롬프트") == {
        "kind": "request",
        "mode": "dev-guide",
        "content": "캐릭터 등장 장면 프롬프트",
        "command": "/art",
    }
    assert parse_game_qna_command("/lore 전우치의 관계") ["mode"] == "lore"
    assert parse_game_qna_command("/catalog 마을") ["mode"] == "catalog"
    assert parse_game_qna_command("/codexbook 루멘") ["mode"] == "codex"
    assert parse_game_qna_command("/codexbook 루멘") ["command"] == "/codexbook"
    assert parse_game_qna_command("/story-review 기억의 문") == {
        "kind": "request",
        "mode": "story-review",
        "content": "기억의 문",
        "command": "/story-review",
    }


def test_game_qna_help_command_is_resolved_without_agent_call():
    result = parse_game_qna_command("/?")
    assert result["kind"] == "help"
    assert "/planning" in result["commands"]


def test_art_command_keeps_its_prompt_guide_marker_for_game_qna_agent():
    command = parse_game_qna_command("/art 홍길동")

    assert game_qna_agent_message(command) == "/art 홍길동"


def test_video_handoff_formats_the_art_prompt_as_a_korean_brief():
    request = build_video_handoff_request({"story": "연화의 선택", "character": "연화"})

    assert request["message"] == (
        "아트 프롬프트 초안\n\n"
        "스토리 맥락: 연화의 선택\n"
        "인물상: 연화\n"
        "역할·갈등: 확인 필요"
    )
    assert request["context"] == {"source": "game-qna"}


def test_video_generation_task_is_saved_to_the_operational_task_log(monkeypatch):
    from app import main

    async def fake_send_message(registry, message):
        return {"task": {"id": "video-log-test"}}

    monkeypatch.setattr(main.video_agent_client, "send_message", fake_send_message)
    task_name = "운영원칙 영상 생성 기록 테스트"

    response = TestClient(app).post(
        "/api/video-agent/tasks",
        json={"message": task_name, "owner": "테스트 담당자"},
    )

    assert response.status_code == 200
    logs = task_log_store.list_logs(
        work_date=datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
        owner="테스트 담당자",
        agent="Video Generation",
        limit=100,
    )
    assert any(log["task_name"] == task_name and log["status"] == "진행 중" for log in logs)


def test_frontend_origin_can_call_api():
    response = TestClient(app).options(
        "/api/tasks",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_vite_localhost_ip_origin_can_call_api():
    response = TestClient(app).options(
        "/api/tasks",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_vite_preview_origin_can_call_api():
    response = TestClient(app).options(
        "/api/tasks",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"


def test_chat_messages_are_saved_and_scoped_to_agent():
    client = TestClient(app)
    suffix = uuid4().hex
    workmate = f"Workmate AI API test {suffix}"
    game = f"Game Q&A API test {suffix}"

    saved = client.post(f"/api/chats/{workmate}/messages", json={"role": "user", "content": "업무 브리핑"})
    assert saved.status_code == 201
    assert client.post(f"/api/chats/{game}/messages", json={"role": "user", "content": "게임 질문"}).status_code == 201

    workmate_messages = client.get(f"/api/chats/{workmate}/messages")
    assert workmate_messages.status_code == 200
    assert [item["content"] for item in workmate_messages.json()] == ["업무 브리핑"]


def test_chat_reset_starts_a_new_db_session_and_preserves_old_messages():
    client = TestClient(app)
    chat = f"Video Generation reset test {uuid4().hex}"
    client.post(f"/api/chats/{chat}/messages", json={"role": "user", "content": "old message"})
    old_session = client.get(f"/api/chats/{chat}/session").json()["session_id"]
    reset = client.post(f"/api/chats/{chat}/reset")
    new_session = reset.json()["session_id"]
    assert new_session != old_session
    client.post(f"/api/chats/{chat}/messages", json={"role": "user", "content": "new message", "session_id": new_session})
    current = client.get(f"/api/chats/{chat}/session").json()
    old = client.get(f"/api/chats/{chat}/messages", params={"session_id": old_session})
    assert [item["content"] for item in current["messages"]] == ["new message"]
    assert [item["content"] for item in old.json()] == ["old message"]


def test_chat_reply_returns_an_agent_answer_without_creating_a_task():
    client = TestClient(app)
    response = client.post("/api/chats/Game Q&A/reply", json={"content": "홍길동"})
    assert response.status_code == 200
    assert response.json()["answer"]
    assert response.json()["agent"] == "game-qna-agent"


def test_codexbook_chat_reply_exposes_codex_routing():
    client = TestClient(app)
    response = client.post("/api/chats/Game Q&A/reply", json={"content": "/codexbook 루멘"})
    assert response.status_code == 200
    assert response.json()["mode"] == "codex"
    assert response.json()["command"] == "/codexbook"
    assert response.json()["answer"].startswith("[Source: Codex (characters / monsters / items)]")


def test_main_chat_routes_lore_question_to_game_qna_agent():
    client = TestClient(app)
    response = client.post("/api/chats/Workmate AI/reply", json={"content": "홍길동"})
    assert response.status_code == 200
    assert response.json()["agent"] == "game-qna-agent"


def test_all_chat_inputs_can_be_routed_by_router_llm(monkeypatch):
    from app import main

    class FakeRouter:
        async def select(self, request):
            assert "사용자 요청" in request
            return {"selected_agents": ["dev-agent"], "confidence": 0.97}

    monkeypatch.setattr(main, "router", FakeRouter())
    response = TestClient(app).post(
        "/api/chats/Video Generation/reply",
        json={"content": "이 코드의 오류를 찾아줘"},
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "dev-agent"


def test_story_review_proxy_calls_catalog_review_endpoint(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"reviewId": "review-main", "verdict": "review_required", "approvalRequired": True}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers=None):
            assert url.endswith("/api/story-review")
            assert json["name"] == "새 이야기"
            return FakeResponse()

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda timeout: FakeClient())
    response = TestClient(app).post(
        "/api/stories/review",
        json={"name": "새 이야기", "keywords": ["새 이야기"], "answer": "본문"},
    )
    assert response.status_code == 200
    assert response.json()["reviewId"] == "review-main"


def test_story_review_waits_longer_than_the_default_http_timeout(monkeypatch):
    from app import main

    captured: dict[str, float] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"reviewId": "review-timeout", "verdict": "review_required", "approvalRequired": True}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers=None):
            return FakeResponse()

    def create_client(timeout):
        captured["timeout"] = timeout
        return FakeClient()

    monkeypatch.delenv("CATALOG_API_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(main.httpx, "AsyncClient", create_client)

    response = TestClient(app).post(
        "/api/stories/review",
        json={"name": "시간 제한 테스트", "keywords": ["테스트"], "answer": "본문"},
    )

    assert response.status_code == 200
    assert captured["timeout"] == 45.0


def test_story_approve_proxy_calls_catalog_approve_endpoint(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "saved", "entry": {"id": "new-story"}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers=None):
            assert url.endswith("/api/story-approve")
            assert json["reviewId"] == "review-main"
            return FakeResponse()

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda timeout: FakeClient())
    response = TestClient(app).post(
        "/api/stories/approve",
        json={"reviewId": "review-main", "draft": {"name": "새 이야기", "keywords": ["새 이야기"], "answer": "본문"}},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "saved"


def test_chat_reply_passes_through_unresolved_scenes_when_present(monkeypatch):
    from app.main import LocalClient

    async def fake_send_message(self, agent_url, request, headers=None):
        return {
            "status": "succeeded",
            "answer": "일부 장면에 수동 수정이 필요합니다",
            "task": {
                "id": "task_abc123",
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "unresolvedScenes": [
                        {"sceneId": "scene_04", "imageUrl": "http://localhost:8002/media/cand_1.png", "issues": ["too wide"]}
                    ],
                },
            },
        }

    monkeypatch.setenv("LIVE_AGENT_DISCOVERY", "false")
    monkeypatch.setattr(LocalClient, "send_message", fake_send_message)
    response = TestClient(app).post("/api/chats/Video Generation/reply", json={"content": "할로윈 이벤트 영상 만들어줘"})

    assert response.status_code == 200
    body = response.json()
    assert body["taskId"] == "task_abc123"
    assert body["unresolvedScenes"] == [
        {"sceneId": "scene_04", "imageUrl": "http://localhost:8002/media/cand_1.png", "issues": ["too wide"]}
    ]


def test_chat_reply_omits_unresolved_scenes_key_when_absent():
    body = TestClient(app).post("/api/chats/Game Q&A/reply", json={"content": "홍길동"}).json()

    assert "unresolvedScenes" not in body
    assert "taskId" not in body


def test_resume_video_scene_proxies_upload_and_returns_video_agent_response(monkeypatch):
    async def fake_post(self, url, *, files=None, headers=None):
        assert url == "http://video-agent:8002/tasks/task_abc123/scenes/scene_04/resume"
        assert "file" in files
        return httpx.Response(
            200,
            json={
                "scene_id": "scene_04",
                "resolved": True,
                "remaining_unresolved": [],
                "output_video_url": "http://localhost:8002/media/proj_x.mp4",
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post(
        "/api/video-agent/tasks/task_abc123/scenes/scene_04/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["output_video_url"] == "http://localhost:8002/media/proj_x.mp4"


def test_resume_video_scene_maps_video_agent_error_response(monkeypatch):
    async def fake_post(self, url, *, files=None, headers=None):
        return httpx.Response(
            404,
            json={"error": {"code": 404, "status": "NOT_FOUND", "message": "Unknown task: task_bad"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post(
        "/api/video-agent/tasks/task_bad/scenes/scene_04/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 404
    assert "Unknown task: task_bad" in response.json()["detail"]["message"]


def test_resume_video_scene_returns_502_when_video_agent_unreachable(monkeypatch):
    async def fake_post(self, url, *, files=None, headers=None):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post(
        "/api/video-agent/tasks/task_x/scenes/scene_04/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 502
