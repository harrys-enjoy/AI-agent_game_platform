from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.brief_intake import BriefIntakeAgent, BriefIntakeError, IntakeResult
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.schema import Project, ProjectInput

_AUTH_HEADERS = {"Authorization": "Bearer test-token", "A2A-Version": "1.0"}


def _client_with_intake_result(intake_result: IntakeResult, tmp_path, monkeypatch, render_fn=None) -> TestClient:
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    fake_agent = MagicMock(spec=BriefIntakeAgent)
    fake_agent.run.return_value = intake_result
    app = create_app(
        intake_agent=fake_agent,
        render_fn=render_fn or (lambda project_input: Project(project_id="p", input=project_input)),
        task_store=TaskStore(),
        media_dir=str(tmp_path),
        media_public_base_url="http://localhost:8002",
    )
    return TestClient(app)


def _client_with_intake_agent(fake_agent, tmp_path, monkeypatch, render_fn=None) -> TestClient:
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(
        intake_agent=fake_agent,
        render_fn=render_fn or (lambda project_input: Project(project_id="p", input=project_input)),
        task_store=TaskStore(),
        media_dir=str(tmp_path),
        media_public_base_url="http://localhost:8002",
    )
    return TestClient(app)


def _client_with_store(fake_agent, store, tmp_path, monkeypatch, render_fn=None) -> TestClient:
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(
        intake_agent=fake_agent,
        render_fn=render_fn or (lambda project_input: Project(project_id="p", input=project_input)),
        task_store=store,
        media_dir=str(tmp_path),
        media_public_base_url="http://localhost:8002",
    )
    return TestClient(app)


def _message_body(text: str, message_id: str = "main-agent") -> dict:
    return {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{"text": text}],
        },
        "metadata": {"mode": "video_draft", "locale": "ko", "context": {}, "evidence": []},
    }


def test_message_send_requires_auth(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="어떤 영상을 만들고 싶으신가요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post("/a2a/message:send", json=_message_body("안녕"))

    assert response.status_code == 401


def test_message_send_returns_clarifying_question_synchronously(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="어떤 영상을 만들고 싶으신가요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post("/a2a/message:send", json=_message_body("안녕"), headers=_AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["message"]["parts"] == [{"text": "어떤 영상을 만들고 싶으신가요?"}]
    assert "task" not in body


def test_message_send_creates_task_with_working_state_and_context_id(tmp_path, monkeypatch):
    intake_result = IntakeResult(
        brief="할로윈 신규 캐릭터 공개 이벤트", preset="이벤트", scene_type="인게임", duration_sec=15
    )
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send", json=_message_body("할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"), headers=_AUTH_HEADERS
    )

    assert response.status_code == 200
    body = response.json()
    assert "task" in body
    assert body["task"]["status"]["state"] == "TASK_STATE_WORKING"
    assert body["task"]["id"]
    assert body["task"]["contextId"]


def test_message_send_returns_400_when_message_has_no_text(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="무엇을 도와드릴까요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send",
        json={"message": {"messageId": "m", "role": "ROLE_USER", "parts": []}, "metadata": {}},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_message_send_returns_400_when_duration_exceeds_max(tmp_path, monkeypatch):
    intake_result = IntakeResult(
        brief="60초짜리 홍보 영상", preset="이벤트", scene_type="인게임", duration_sec=60
    )
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post("/a2a/message:send", json=_message_body("60초로 만들어줘"), headers=_AUTH_HEADERS)

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_message_send_returns_503_when_intake_agent_raises_brief_intake_error(tmp_path, monkeypatch):
    fake_agent = MagicMock(spec=BriefIntakeAgent)
    fake_agent.run.side_effect = BriefIntakeError("boom")
    client = _client_with_intake_agent(fake_agent, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send", json=_message_body("할로윈 신규 캐릭터 공개 이벤트"), headers=_AUTH_HEADERS
    )

    assert response.status_code == 503
    assert response.json()["error"]["status"] == "UNAVAILABLE"


def test_message_send_task_becomes_gettable_and_completes_via_background_render(tmp_path, monkeypatch):
    intake_result = IntakeResult(
        brief="할로윈 신규 캐릭터 공개 이벤트", preset="이벤트", scene_type="인게임", duration_sec=15
    )

    def fake_render(project_input: ProjectInput) -> Project:
        return Project(project_id="proj_xyz", input=project_input, output_video_url="media/proj_xyz.mp4")

    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch, render_fn=fake_render)

    send_response = client.post(
        "/a2a/message:send", json=_message_body("할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"), headers=_AUTH_HEADERS
    )
    task_id = send_response.json()["task"]["id"]

    task_response = client.get(f"/a2a/tasks/{task_id}", headers=_AUTH_HEADERS)

    body = task_response.json()
    assert body["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "media/proj_xyz.mp4" in body["task"]["status"]["message"]["parts"][0]["text"]
    assert "media/proj_xyz.mp4" in body["task"]["artifacts"][0]["parts"][1]["data"]["output_video_url"]


def test_message_send_repeated_message_id_returns_same_task_without_re_rendering(tmp_path, monkeypatch):
    intake_result = IntakeResult(
        brief="할로윈 신규 캐릭터 공개 이벤트", preset="이벤트", scene_type="인게임", duration_sec=15
    )
    render_calls = []

    def counting_render(project_input: ProjectInput) -> Project:
        render_calls.append(1)
        return Project(project_id="proj_xyz", input=project_input, output_video_url="media/proj_xyz.mp4")

    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch, render_fn=counting_render)
    body = _message_body("할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘", message_id="retry-msg")

    first = client.post("/a2a/message:send", json=body, headers=_AUTH_HEADERS)
    second = client.post("/a2a/message:send", json=body, headers=_AUTH_HEADERS)

    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert len(render_calls) == 1


def test_message_send_returns_503_when_message_id_already_claimed_by_concurrent_request(tmp_path, monkeypatch):
    fake_agent = MagicMock(spec=BriefIntakeAgent)
    store = TaskStore()
    store.claim_message_id("in-flight")
    client = _client_with_store(fake_agent, store, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send", json=_message_body("할로윈 이벤트", message_id="in-flight"), headers=_AUTH_HEADERS
    )

    assert response.status_code == 503
    assert response.json()["error"]["status"] == "UNAVAILABLE"
    fake_agent.run.assert_not_called()


def test_message_send_releases_message_id_claim_when_text_is_empty(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="무엇을 도와드릴까요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)
    # parts is non-empty (passes envelope parsing in protocol.py) but has no
    # text part, so extract_text(message) == "" and the `if not text:` branch
    # in app.py is the one that actually runs (and must release the claim).
    empty_body = {
        "message": {"messageId": "retry-me", "role": "ROLE_USER", "parts": [{"data": {"x": 1}}]},
        "metadata": {},
    }

    first = client.post("/a2a/message:send", json=empty_body, headers=_AUTH_HEADERS)
    second = client.post(
        "/a2a/message:send", json=_message_body("정상 텍스트", message_id="retry-me"), headers=_AUTH_HEADERS
    )

    assert first.status_code == 400
    assert second.status_code == 200


def test_message_send_returns_400_for_part_with_wrong_field_type(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="무엇을 도와드릴까요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send",
        json={"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": 123}]}, "metadata": {}},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_message_send_returns_400_for_json_list_body(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="무엇을 도와드릴까요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send",
        content=b"[1, 2, 3]",
        headers={**_AUTH_HEADERS, "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_message_send_returns_400_for_json_string_body(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="무엇을 도와드릴까요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send",
        content=b'"just a string"',
        headers={**_AUTH_HEADERS, "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_message_send_returns_400_for_non_json_body(tmp_path, monkeypatch):
    intake_result = IntakeResult(clarifying_question="무엇을 도와드릴까요?")
    client = _client_with_intake_result(intake_result, tmp_path, monkeypatch)

    response = client.post(
        "/a2a/message:send",
        content=b"not json at all {{{",
        headers={**_AUTH_HEADERS, "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_message_send_releases_message_id_claim_on_unexpected_error_and_allows_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    fake_agent = MagicMock(spec=BriefIntakeAgent)
    fake_agent.run.side_effect = [RuntimeError("boom"), IntakeResult(clarifying_question="다시 말씀해주세요")]
    store = TaskStore()
    app = create_app(
        intake_agent=fake_agent,
        render_fn=lambda project_input: Project(project_id="p", input=project_input),
        task_store=store,
        media_dir=str(tmp_path),
        media_public_base_url="http://localhost:8002",
    )
    client = TestClient(app, raise_server_exceptions=False)
    body = _message_body("할로윈 이벤트", message_id="retry-after-unexpected-error")

    first = client.post("/a2a/message:send", json=body, headers=_AUTH_HEADERS)
    second = client.post("/a2a/message:send", json=body, headers=_AUTH_HEADERS)

    assert first.status_code == 500
    assert second.status_code == 200
    assert second.json()["message"]["parts"] == [{"text": "다시 말씀해주세요"}]


def test_message_send_releases_message_id_claim_when_intake_agent_raises(tmp_path, monkeypatch):
    fake_agent = MagicMock(spec=BriefIntakeAgent)
    fake_agent.run.side_effect = [BriefIntakeError("boom"), IntakeResult(clarifying_question="다시 말씀해주세요")]
    store = TaskStore()
    client = _client_with_store(fake_agent, store, tmp_path, monkeypatch)
    body = _message_body("할로윈 이벤트", message_id="retry-after-error")

    first = client.post("/a2a/message:send", json=body, headers=_AUTH_HEADERS)
    second = client.post("/a2a/message:send", json=body, headers=_AUTH_HEADERS)

    assert first.status_code == 503
    assert second.status_code == 200
    assert second.json()["message"]["parts"] == [{"text": "다시 말씀해주세요"}]
