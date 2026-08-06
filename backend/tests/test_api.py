from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.main import parse_game_qna_command


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
    assert parse_game_qna_command("/lore 전우치의 관계") ["mode"] == "lore"
    assert parse_game_qna_command("/catalog 마을") ["mode"] == "catalog"
    assert parse_game_qna_command("/codexbook 루멘") ["mode"] == "codex"
    assert parse_game_qna_command("/codexbook 루멘") ["command"] == "/codexbook"


def test_game_qna_help_command_is_resolved_without_agent_call():
    result = parse_game_qna_command("/?")
    assert result["kind"] == "help"
    assert "/planning" in result["commands"]


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

