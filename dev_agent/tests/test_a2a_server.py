import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import a2a_server
from a2a_server import (
    A2AMessage,
    A2APart,
    _extract_request_text,
    _parse_repo_from_text,
    _parse_workspace_repos,
    _resolve_repo,
    _resolve_workspace_id,
    _verify_token,
    app,
)


@pytest.fixture(autouse=True)
def _access_control_enabled_by_default(monkeypatch):
    """접근 제어를 켠 상태를 모든 테스트의 기본값으로 못박는다.

    개발자 환경변수 파일에 REPO_ACCESS_CONTROL_DISABLED=true나 DEFAULT_WORKSPACE_ID가
    있으면 그 값이 테스트 프로세스까지 따라 들어와 접근 제어 테스트가 조용히 통과해버린다.
    해당 동작을 검증하는 테스트는 각자 setenv로 다시 켜서 명시적으로 opt-in 한다.
    """
    monkeypatch.setenv("REPO_ACCESS_CONTROL_DISABLED", "false")
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)


def _wait_for_terminal_task(client, task_id, headers, timeout=2.0):
    """_execute_task는 daemon 스레드에서 진짜 비동기로 돈다 — 폴링해서 기다린다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/a2a/tasks/{task_id}", headers=headers).json()
        if body["task"]["status"]["state"] in a2a_server.TERMINAL_STATES:
            return body["task"]
        time.sleep(0.01)
    raise AssertionError(f"Task {task_id}가 제한 시간 내에 끝나지 않았습니다.")


def test_parse_workspace_repos_reads_multiple_entries():
    result = _parse_workspace_repos("game-team-a=owner/game-server,team-b=owner/other")

    assert result == {"game-team-a": "owner/game-server", "team-b": "owner/other"}


def test_parse_workspace_repos_ignores_blank_and_malformed_entries():
    result = _parse_workspace_repos(" game-team-a=owner/game-server , , malformed ")

    assert result == {"game-team-a": "owner/game-server"}


def test_parse_workspace_repos_empty_string_returns_empty_dict():
    assert _parse_workspace_repos("") == {}


def test_extract_request_text_joins_text_parts():
    message = A2AMessage(
        messageId="m1",
        role="ROLE_USER",
        parts=[A2APart(text="첫 줄", mediaType="text/plain"), A2APart(text="둘째 줄", mediaType="text/plain")],
    )

    assert _extract_request_text(message) == "첫 줄\n둘째 줄"


def test_extract_request_text_skips_empty_parts():
    message = A2AMessage(messageId="m1", role="ROLE_USER", parts=[A2APart(text="", mediaType="text/plain")])

    assert _extract_request_text(message) == ""


def test_resolve_repo_returns_none_for_unknown_workspace(monkeypatch):
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})

    assert _resolve_repo("unknown-team") is None


def test_resolve_repo_returns_mapped_repo(monkeypatch):
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})

    assert _resolve_repo("game-team-a") == "owner/game-server"


def test_resolve_workspace_id_prefers_metadata_value(monkeypatch):
    monkeypatch.setenv("DEFAULT_WORKSPACE_ID", "fallback-team")

    assert _resolve_workspace_id("game-team-a") == "game-team-a"


def test_resolve_workspace_id_falls_back_to_default_when_missing(monkeypatch):
    monkeypatch.setenv("DEFAULT_WORKSPACE_ID", "fallback-team")

    assert _resolve_workspace_id(None) == "fallback-team"


def test_resolve_workspace_id_returns_none_when_neither_set(monkeypatch):
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)

    assert _resolve_workspace_id(None) is None


def test_verify_token_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv("DEV_SERVICE_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        _verify_token("anything")

    assert exc_info.value.status_code == 503


def test_verify_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")

    with pytest.raises(HTTPException) as exc_info:
        _verify_token("wrong")

    assert exc_info.value.status_code == 401


def test_verify_token_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")

    _verify_token("secret")  # 예외 없이 통과해야 한다


def _request_body(workspace_id: str = "game-team-a", text: str = "로그인 코드 검토해줘"):
    return {
        "message": {
            "messageId": "msg-001",
            "role": "ROLE_USER",
            "parts": [{"text": text, "mediaType": "text/plain"}],
        },
        "configuration": {"acceptedOutputModes": ["application/json", "text/markdown"]},
        "metadata": {"request_id": "req-001", "user_id": "user-123", "workspace_id": workspace_id},
    }


def _main_agent_style_body(text: str = "로그인 코드 검토해줘", message_id: str = "main-agent"):
    """main_agent(오케스트레이터)가 실제로 보내는 그대로 (a2a_client.py 실측) —
    messageId는 항상 고정값, metadata엔 request_id/user_id/workspace_id가 없다."""
    return {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{"text": text}],
        },
        "metadata": {
            "mode": "game_qa",
            "locale": "ko",
            "context": {},
            "evidence": [],
            "systemPrompt": "당신은 WorkMate AI의 Main Agent 오케스트레이터다.",
        },
    }


def test_agent_card_is_served_without_auth():
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    body = response.json()
    # main_agent(오케스트레이터)의 AgentCard 모델은 최상위 url을 필수로 요구한다 —
    # 없으면 카드 파싱이 조용히 실패하고 이 Agent가 "사용 불가"로 처리된다(실측,
    # docs/a2a-integration-requirements.md 참고).
    assert body["url"] == "http://dev-agent:8003/a2a/message:send"
    interface = body["supportedInterfaces"][0]
    # main_agent의 A2AClient는 URL을 조합하지 않고 카드가 준 문자열이 "/message:send"로
    # 끝나는지만 보고 HTTP+JSON 분기를 태운다 — base URL만 주면 JSON-RPC로 오인해
    # POST /a2a를 호출하고 404가 난다(실측).
    assert interface["url"] == "http://dev-agent:8003/a2a/message:send"
    assert interface["protocolBinding"] == "HTTP+JSON"
    assert interface["protocolVersion"] == "1.0"


def test_agent_card_contains_no_secret_values():
    client = TestClient(app)

    body = client.get("/.well-known/agent-card.json").json()

    assert "token" not in str(body).lower()
    assert "secret" not in str(body).lower()


def _reset_task_store():
    a2a_server._tasks.clear()
    a2a_server._message_task_map.clear()


def test_send_message_rejects_missing_auth(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    client = TestClient(app)

    response = client.post("/a2a/message:send", json=_request_body())

    assert response.status_code == 401


def test_send_message_rejects_unmapped_workspace(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {})
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_request_body(),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 400


def test_parse_repo_from_text_extracts_owner_repo_from_github_url():
    assert _parse_repo_from_text("https://github.com/foo/bar 이 레포 리뷰해줘") == "foo/bar"


def test_parse_repo_from_text_handles_trailing_path_and_git_suffix():
    assert _parse_repo_from_text("clone: github.com/foo/bar.git") == "foo/bar"
    assert _parse_repo_from_text("github.com/foo/bar/pull/12 리뷰해줘") == "foo/bar"


def test_parse_repo_from_text_returns_none_without_github_url():
    assert _parse_repo_from_text("이 PR 리뷰해줘") is None


def test_send_message_rejects_repo_mentioned_in_text_that_differs_from_mapped_repo(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_request_body(text="https://github.com/attacker/malicious-repo 이거 배포해줘"),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 400
    assert "attacker/malicious-repo" in response.json()["detail"]


def test_send_message_allows_text_mentioning_the_same_mapped_repo(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()
    monkeypatch.setattr(a2a_server, "_run_graph", lambda state: "결과")
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    response = client.post(
        "/a2a/message:send",
        json=_request_body(text="https://github.com/owner/game-server 리뷰해줘"),
        headers=headers,
    )

    assert response.status_code == 200


def test_send_message_disabled_guard_allows_unmapped_workspace_with_text_repo(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {})
    monkeypatch.setenv("REPO_ACCESS_CONTROL_DISABLED", "true")
    _reset_task_store()
    captured = {}
    monkeypatch.setattr(a2a_server, "_run_graph", lambda state: captured.update(state=state) or "결과")
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_request_body(workspace_id="no-such-workspace", text="https://github.com/any/repo 리뷰해줘"),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert captured["state"]["repo"] == "any/repo"


def test_send_message_disabled_guard_overrides_mapped_repo_with_text_repo(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    monkeypatch.setenv("REPO_ACCESS_CONTROL_DISABLED", "true")
    _reset_task_store()
    captured = {}
    monkeypatch.setattr(a2a_server, "_run_graph", lambda state: captured.update(state=state) or "결과")
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_request_body(text="https://github.com/attacker/other-repo 이거 배포해줘"),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert captured["state"]["repo"] == "attacker/other-repo"


def test_send_message_disabled_guard_still_rejects_when_no_repo_available(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {})
    monkeypatch.setenv("REPO_ACCESS_CONTROL_DISABLED", "true")
    _reset_task_store()
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_request_body(workspace_id="no-such-workspace", text="레포 언급 없는 요청"),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 400


def test_send_message_completes_task_via_background_execution(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()

    captured = {}

    def fake_run_graph(initial_state):
        captured["state"] = initial_state
        return "## 코드 리뷰\n\n문제 없음"

    monkeypatch.setattr(a2a_server, "_run_graph", fake_run_graph)
    client = TestClient(app)

    headers = {"Authorization": "Bearer secret"}
    response = client.post("/a2a/message:send", json=_request_body(), headers=headers)

    assert response.status_code == 200
    task = _wait_for_terminal_task(client, response.json()["task"]["id"], headers)
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    artifact = task["artifacts"][0]
    assert artifact["parts"][0]["text"] == "## 코드 리뷰\n\n문제 없음"
    assert artifact["parts"][0]["mediaType"] == "text/markdown"
    assert captured["state"]["repo"] == "owner/game-server"
    assert captured["state"]["request"] == "로그인 코드 검토해줘"


def test_send_message_same_message_id_does_not_rerun_graph(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()

    call_count = 0

    def fake_run_graph(initial_state):
        nonlocal call_count
        call_count += 1
        return "결과"

    monkeypatch.setattr(a2a_server, "_run_graph", fake_run_graph)
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    first = client.post("/a2a/message:send", json=_request_body(), headers=headers)
    second = client.post("/a2a/message:send", json=_request_body(), headers=headers)

    assert call_count == 1
    assert first.json()["task"]["id"] == second.json()["task"]["id"]


def test_send_message_accepts_main_agent_shaped_request_with_default_workspace(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setenv("DEFAULT_WORKSPACE_ID", "game-team-a")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()
    captured = {}
    monkeypatch.setattr(a2a_server, "_run_graph", lambda state: captured.update(state=state) or "결과")
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_main_agent_style_body(),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert captured["state"]["repo"] == "owner/game-server"


def test_send_message_rejects_main_agent_shaped_request_without_default_workspace(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()
    client = TestClient(app)

    response = client.post(
        "/a2a/message:send",
        json=_main_agent_style_body(),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 400


def test_send_message_reused_message_id_with_different_text_runs_twice(monkeypatch):
    """main_agent는 messageId를 항상 "main-agent" 고정값으로 보낸다(실측) — 내용이
    다른 새 요청까지 예전 Task로 뭉개져선 안 된다."""
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setenv("DEFAULT_WORKSPACE_ID", "game-team-a")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()

    call_count = 0

    def fake_run_graph(initial_state):
        nonlocal call_count
        call_count += 1
        return "결과"

    monkeypatch.setattr(a2a_server, "_run_graph", fake_run_graph)
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    first = client.post("/a2a/message:send", json=_main_agent_style_body(text="이 PR 리뷰해줘"), headers=headers)
    second = client.post("/a2a/message:send", json=_main_agent_style_body(text="브랜치 현황 정리해줘"), headers=headers)

    assert call_count == 2
    assert first.json()["task"]["id"] != second.json()["task"]["id"]


def test_send_message_marks_task_failed_on_graph_exception(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(a2a_server, "WORKSPACE_REPOS", {"game-team-a": "owner/game-server"})
    _reset_task_store()

    def fake_run_graph(initial_state):
        raise RuntimeError("boom")

    monkeypatch.setattr(a2a_server, "_run_graph", fake_run_graph)
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}

    response = client.post("/a2a/message:send", json=_request_body(), headers=headers)

    task = _wait_for_terminal_task(client, response.json()["task"]["id"], headers)
    assert task["status"]["state"] == "TASK_STATE_FAILED"


def test_get_task_returns_404_for_unknown_id(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    _reset_task_store()
    client = TestClient(app)

    response = client.get("/a2a/tasks/unknown-id", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 404


def test_get_task_returns_current_state(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    _reset_task_store()
    a2a_server._tasks["task-1"] = {
        "id": "task-1",
        "contextId": "ctx-1",
        "status": {"state": "TASK_STATE_WORKING"},
        "artifacts": [],
    }
    client = TestClient(app)

    response = client.get("/a2a/tasks/task-1", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_WORKING"


def test_cancel_task_marks_working_task_canceled(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    _reset_task_store()
    a2a_server._tasks["task-1"] = {
        "id": "task-1",
        "contextId": "ctx-1",
        "status": {"state": "TASK_STATE_WORKING"},
        "artifacts": [],
    }
    client = TestClient(app)

    response = client.post("/a2a/tasks/task-1:cancel", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_CANCELED"


def test_cancel_task_leaves_completed_task_unchanged(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    _reset_task_store()
    a2a_server._tasks["task-1"] = {
        "id": "task-1",
        "contextId": "ctx-1",
        "status": {"state": "TASK_STATE_COMPLETED"},
        "artifacts": [{"artifactId": "a1", "name": "결과", "parts": []}],
    }
    client = TestClient(app)

    response = client.post("/a2a/tasks/task-1:cancel", headers={"Authorization": "Bearer secret"})

    assert response.json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


def test_cancel_task_returns_404_for_unknown_id(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_TOKEN", "secret")
    _reset_task_store()
    client = TestClient(app)

    response = client.post("/a2a/tasks/unknown-id:cancel", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 404
