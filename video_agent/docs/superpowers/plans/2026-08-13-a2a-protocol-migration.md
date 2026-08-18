# A2A 1.0 Protocol Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make video-agent's A2A surface comply with the team's Notion-documented A2A 1.0 protocol — route prefix, 8-state task model, message envelope, artifact-shaped responses, Bearer+`A2A-Version` auth, `messageId` idempotency, and a coarse cancel endpoint.

**Architecture:** A new `protocol.py` owns A2A wire shapes (parsing the `Message` envelope, building `Task`/`Artifact` responses) and a new `auth.py` owns Bearer/`A2A-Version` validation, both consumed by thin route handlers in `app.py`. `tasks.py` gains the full 8-state model, `messageId` idempotency, and a `contextId`. The render pipeline (`orchestrator.py`, `render_runner.py`) gets one minimal addition — an optional cancellation checkpoint — everything else about scene processing is untouched.

**Tech Stack:** Python 3.11+, FastAPI, pydantic v2, pytest (existing stack — no new dependencies).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-13-a2a-protocol-migration-design.md` — every task below implements a section of it.
- Scope: `video_draft_pipeline` (video-agent) only. Never touch `AI-agent_game_platform` — that's a teammate's responsibility.
- Cutover: hard cutover, no dual-format transition period. Old unprefixed `/message:send` and `/tasks/{id}` routes are replaced, not kept alongside the new `/a2a/*` ones.
- Route boundary: only `POST /a2a/message:send`, `GET /a2a/tasks/{id}`, `POST /a2a/tasks/{id}:cancel` move under `/a2a`. `GET /.well-known/agent-card.json`, `POST /tasks/{id}/scenes/{id}/resume`, and the `/media` static mount stay unprefixed.
- All 8 task states from the doc: `TASK_STATE_SUBMITTED/WORKING/INPUT_REQUIRED/AUTH_REQUIRED/COMPLETED/FAILED/CANCELED/REJECTED`.
- Auth (`Authorization: Bearer {VIDEO_SERVICE_TOKEN}` + `A2A-Version: 1.0`) applies only to the 3 `/a2a/*` routes — never to `/tasks/{id}/scenes/{id}/resume` or the agent card.
- Run tests with `pytest -v` from the repo root (`C:\Users\golgi\edu\proj`); `pyproject.toml` already sets `pythonpath = ["src"]` and `testpaths = ["tests"]`.
- No change to `orchestrator.py`'s scene-processing logic beyond the one `should_cancel` checkpoint in Task 6.

---

### Task 1: TaskStore — 8-state model, `contextId`, `messageId` idempotency, cancel flag

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/tasks.py`
- Test: `tests/a2a_server/test_tasks.py`

**Interfaces:**
- Produces: `TaskRecord` (`task_id`, `context_id: str`, `state: str`, `answer: str | None`, `project_id: str | None`, `unresolved_scenes: list[dict] | None`, `output_video_url: str | None`, `cancel_requested: bool`). `TaskStore.create() -> TaskRecord` (state defaults to `TASK_STATE_SUBMITTED`). `TaskStore.mark_working(task_id)`, `.mark_completed(task_id, answer, output_video_url=None)`, `.mark_failed(task_id, answer)`, `.mark_input_required(task_id, answer)`, `.request_cancel(task_id)` (sets `cancel_requested=True` and state to `TASK_STATE_CANCELED`), `.set_project_id(task_id, project_id)`, `.set_unresolved_scenes(task_id, scenes)`, `.register_message_id(message_id, task_id)`, `.task_id_for_message(message_id) -> str | None`.

This task doesn't depend on `protocol.py` — state strings are hardcoded here as plain string literals (matching the existing style) rather than importing an enum, to avoid a circular-looking dependency between `tasks.py` and `protocol.py`. Task 4 will layer `protocol.TaskState` as an enum whose `.value`s match these exact strings.

- [ ] **Step 1: Write the failing tests**

Replace `tests/a2a_server/test_tasks.py` entirely with:

```python
from video_draft_pipeline.a2a_server.tasks import TaskStore


def test_create_returns_submitted_record_with_unique_ids_and_context_id():
    store = TaskStore()

    first = store.create()
    second = store.create()

    assert first.state == "TASK_STATE_SUBMITTED"
    assert first.answer is None
    assert first.task_id != second.task_id
    assert first.context_id
    assert first.context_id != second.context_id


def test_mark_working_updates_state():
    store = TaskStore()
    record = store.create()

    store.mark_working(record.task_id)

    assert store.get(record.task_id).state == "TASK_STATE_WORKING"


def test_get_returns_none_for_unknown_task_id():
    store = TaskStore()

    assert store.get("does-not-exist") is None


def test_get_returns_the_stored_record():
    store = TaskStore()
    record = store.create()

    assert store.get(record.task_id) is record


def test_mark_completed_updates_state_answer_and_output_video_url():
    store = TaskStore()
    record = store.create()

    store.mark_completed(record.task_id, "영상이 완성되었습니다.", output_video_url="http://x/media/p.mp4")

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_COMPLETED"
    assert updated.answer == "영상이 완성되었습니다."
    assert updated.output_video_url == "http://x/media/p.mp4"


def test_mark_completed_output_video_url_defaults_to_none():
    store = TaskStore()
    record = store.create()

    store.mark_completed(record.task_id, "완료")

    assert store.get(record.task_id).output_video_url is None


def test_mark_failed_updates_state_and_answer():
    store = TaskStore()
    record = store.create()

    store.mark_failed(record.task_id, "실패했습니다.")

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert updated.answer == "실패했습니다."


def test_mark_input_required_updates_state_and_answer():
    store = TaskStore()
    record = store.create()

    store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_INPUT_REQUIRED"
    assert updated.answer == "일부 장면에 수동 수정이 필요합니다"


def test_request_cancel_sets_flag_and_canceled_state():
    store = TaskStore()
    record = store.create()

    store.request_cancel(record.task_id)

    updated = store.get(record.task_id)
    assert updated.cancel_requested is True
    assert updated.state == "TASK_STATE_CANCELED"


def test_create_returns_record_with_cancel_requested_false():
    store = TaskStore()

    record = store.create()

    assert record.cancel_requested is False


def test_set_project_id_updates_record():
    store = TaskStore()
    record = store.create()

    store.set_project_id(record.task_id, "proj_abc123")

    assert store.get(record.task_id).project_id == "proj_abc123"


def test_set_unresolved_scenes_updates_record():
    store = TaskStore()
    record = store.create()
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand_1.png", "issues": ["too wide"]}]

    store.set_unresolved_scenes(record.task_id, scenes)

    assert store.get(record.task_id).unresolved_scenes == scenes


def test_register_message_id_and_lookup():
    store = TaskStore()
    record = store.create()

    store.register_message_id("msg-001", record.task_id)

    assert store.task_id_for_message("msg-001") == record.task_id


def test_task_id_for_message_returns_none_when_unseen():
    store = TaskStore()

    assert store.task_id_for_message("never-sent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_tasks.py -v`
Expected: several FAIL — `TaskRecord`/`TaskStore` don't yet have `context_id`, `mark_working`, `mark_input_required`, `request_cancel`, `output_video_url`, `register_message_id`, `task_id_for_message`; `create()` still defaults to `TASK_STATE_WORKING` not `TASK_STATE_SUBMITTED`.

- [ ] **Step 3: Implement**

Replace `src/video_draft_pipeline/a2a_server/tasks.py` entirely with:

```python
import uuid
from dataclasses import dataclass


@dataclass
class TaskRecord:
    task_id: str
    context_id: str = ""
    state: str = "TASK_STATE_SUBMITTED"
    answer: str | None = None
    project_id: str | None = None
    unresolved_scenes: list[dict] | None = None
    output_video_url: str | None = None
    cancel_requested: bool = False


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._message_ids: dict[str, str] = {}

    def create(self) -> TaskRecord:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        record = TaskRecord(task_id=task_id, context_id=f"ctx_{uuid.uuid4().hex[:8]}")
        self._tasks[task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def mark_working(self, task_id: str) -> None:
        self._tasks[task_id].state = "TASK_STATE_WORKING"

    def mark_completed(self, task_id: str, answer: str, output_video_url: str | None = None) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_COMPLETED"
        record.answer = answer
        record.output_video_url = output_video_url

    def mark_failed(self, task_id: str, answer: str) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_FAILED"
        record.answer = answer

    def mark_input_required(self, task_id: str, answer: str) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_INPUT_REQUIRED"
        record.answer = answer

    def request_cancel(self, task_id: str) -> None:
        record = self._tasks[task_id]
        record.cancel_requested = True
        record.state = "TASK_STATE_CANCELED"

    def set_project_id(self, task_id: str, project_id: str) -> None:
        self._tasks[task_id].project_id = project_id

    def set_unresolved_scenes(self, task_id: str, scenes: list[dict]) -> None:
        self._tasks[task_id].unresolved_scenes = scenes

    def register_message_id(self, message_id: str, task_id: str) -> None:
        self._message_ids[message_id] = task_id

    def task_id_for_message(self, message_id: str) -> str | None:
        return self._message_ids.get(message_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/test_tasks.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/tasks.py tests/a2a_server/test_tasks.py
git commit -m "feat: add full 8-state task model, contextId, and messageId idempotency to TaskStore"
```

---

### Task 2: `errors.py` — add `UNAUTHENTICATED` → 401

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/errors.py`
- Test: `tests/a2a_server/test_errors.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `error_response("UNAUTHENTICATED", message)` now returns HTTP 401. Used by Task 5's `auth.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/a2a_server/test_errors.py`:

```python
def test_error_response_unauthenticated_maps_to_401():
    response = error_response("UNAUTHENTICATED", "Invalid or missing Authorization Bearer token")

    assert response.status_code == 401
    body = json.loads(response.body)
    assert body["error"]["status"] == "UNAUTHENTICATED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/a2a_server/test_errors.py -v`
Expected: FAIL with `KeyError: 'UNAUTHENTICATED'`.

- [ ] **Step 3: Implement**

In `src/video_draft_pipeline/a2a_server/errors.py`, update `STATUS_HTTP_CODES`:

```python
STATUS_HTTP_CODES = {
    "INVALID_ARGUMENT": 400,
    "UNAUTHENTICATED": 401,
    "NOT_FOUND": 404,
    "UNAVAILABLE": 503,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/test_errors.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/errors.py tests/a2a_server/test_errors.py
git commit -m "feat: add UNAUTHENTICATED status mapping to 401"
```

---

### Task 3: `agent_card.py` — fix `url`/`supportedInterfaces` mismatch

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/agent_card.py`
- Test: `tests/a2a_server/test_agent_card.py`

**Interfaces:**
- Produces: `build_agent_card(internal_url) -> dict` where both `card["url"]` and `card["supportedInterfaces"][0]["url"]` equal `f"{internal_url}/a2a"` (doc §8's exact shape).

- [ ] **Step 1: Write the failing tests**

Replace `tests/a2a_server/test_agent_card.py` entirely with:

```python
from video_draft_pipeline.a2a_server.agent_card import build_agent_card


def test_build_agent_card_has_video_agent_identity():
    card = build_agent_card("http://video-agent:8002")

    assert card["name"] == "video-agent"
    assert card["url"] == "http://video-agent:8002/a2a"
    assert card["skills"] == [{"id": "video_draft", "name": "영상 초안"}]


def test_build_agent_card_supported_interfaces_url_matches_base_url():
    card = build_agent_card("http://video-agent:8002")

    assert card["supportedInterfaces"] == [
        {
            "url": "http://video-agent:8002/a2a",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }
    ]
    assert card["capabilities"] == {"streaming": False}
    assert card["securitySchemes"] == {}


def test_build_agent_card_url_and_supported_interfaces_url_are_identical():
    card = build_agent_card("http://video-agent:8002")

    assert card["url"] == card["supportedInterfaces"][0]["url"]


def test_build_agent_card_respects_a_different_internal_url():
    card = build_agent_card("http://localhost:9000")

    assert card["url"] == "http://localhost:9000/a2a"
    assert card["supportedInterfaces"][0]["url"] == "http://localhost:9000/a2a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_agent_card.py -v`
Expected: `test_build_agent_card_supported_interfaces_url_matches_base_url`, `test_build_agent_card_url_and_supported_interfaces_url_are_identical`, and the last test FAIL (current code has `supportedInterfaces[0].url` ending in `/message:send`, not `/a2a`).

- [ ] **Step 3: Implement**

Replace `src/video_draft_pipeline/a2a_server/agent_card.py` entirely with:

```python
def build_agent_card(internal_url: str) -> dict:
    base_url = f"{internal_url}/a2a"
    return {
        "name": "video-agent",
        "description": "게임 마케팅 영상 초안 생성 Agent",
        "url": base_url,
        "skills": [{"id": "video_draft", "name": "영상 초안"}],
        "capabilities": {"streaming": False},
        "supportedInterfaces": [
            {
                "url": base_url,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ],
        "securitySchemes": {},
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/test_agent_card.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/agent_card.py tests/a2a_server/test_agent_card.py
git commit -m "fix: agent card url and supportedInterfaces now both point at the real /a2a base URL"
```

---

### Task 4: `protocol.py` — Message envelope parsing and Task/Artifact response building

**Files:**
- Create: `src/video_draft_pipeline/a2a_server/protocol.py`
- Test: `tests/a2a_server/test_protocol.py`

**Interfaces:**
- Produces: `TaskState` (str enum with `.SUBMITTED/.WORKING/.INPUT_REQUIRED/.AUTH_REQUIRED/.COMPLETED/.FAILED/.CANCELED/.REJECTED`, each `.value` matching the exact strings used in `tasks.py`). `ProtocolError(status: str, message: str)` (has `.status`, `.message`). `Part` (pydantic: `text: str | None`, `data: dict | None`, `mediaType: str | None`). `Message` (pydantic: `messageId: str`, `role: str`, `parts: list[Part]`). `parse_message_send_request(body: dict) -> Message` (raises `ProtocolError("INVALID_ARGUMENT", ...)` on a malformed envelope). `extract_text(message: Message) -> str`. `build_artifact(artifact_id, name, parts: list[dict]) -> dict`. `build_video_artifact(answer: str, output_video_url: str | None) -> dict`. `build_unresolved_artifact(unresolved_scenes: list[dict]) -> dict`. `build_task_response(task_id, context_id, state, answer=None, unresolved_scenes=None, artifacts=None) -> dict` (the full `{"task": {...}}` envelope).
- Consumed by: Task 5 (`auth.py` doesn't need this), Task 7 (`render_runner.py`), Task 8 (`app.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/a2a_server/test_protocol.py`:

```python
import pytest

from video_draft_pipeline.a2a_server.protocol import (
    ProtocolError,
    TaskState,
    build_artifact,
    build_task_response,
    build_unresolved_artifact,
    build_video_artifact,
    extract_text,
    parse_message_send_request,
)


def test_task_state_values_match_the_doc_exactly():
    assert TaskState.SUBMITTED.value == "TASK_STATE_SUBMITTED"
    assert TaskState.WORKING.value == "TASK_STATE_WORKING"
    assert TaskState.INPUT_REQUIRED.value == "TASK_STATE_INPUT_REQUIRED"
    assert TaskState.AUTH_REQUIRED.value == "TASK_STATE_AUTH_REQUIRED"
    assert TaskState.COMPLETED.value == "TASK_STATE_COMPLETED"
    assert TaskState.FAILED.value == "TASK_STATE_FAILED"
    assert TaskState.CANCELED.value == "TASK_STATE_CANCELED"
    assert TaskState.REJECTED.value == "TASK_STATE_REJECTED"


def test_parse_message_send_request_extracts_valid_envelope():
    body = {
        "message": {
            "messageId": "msg-001",
            "role": "ROLE_USER",
            "parts": [{"text": "할로윈 이벤트 영상 만들어줘", "mediaType": "text/plain"}],
        },
        "metadata": {"request_id": "req-001"},
    }

    message = parse_message_send_request(body)

    assert message.messageId == "msg-001"
    assert message.role == "ROLE_USER"
    assert message.parts[0].text == "할로윈 이벤트 영상 만들어줘"


def test_parse_message_send_request_rejects_missing_message():
    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request({})

    assert exc_info.value.status == "INVALID_ARGUMENT"


def test_parse_message_send_request_rejects_missing_message_id():
    body = {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}}

    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request(body)

    assert exc_info.value.status == "INVALID_ARGUMENT"
    assert "messageId" in exc_info.value.message


def test_parse_message_send_request_rejects_wrong_role():
    body = {"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "hi"}]}}

    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request(body)

    assert exc_info.value.status == "INVALID_ARGUMENT"


def test_parse_message_send_request_rejects_empty_parts():
    body = {"message": {"messageId": "m", "role": "ROLE_USER", "parts": []}}

    with pytest.raises(ProtocolError):
        parse_message_send_request(body)


def test_extract_text_joins_text_parts_and_skips_data_only_parts():
    body = {
        "message": {
            "messageId": "m",
            "role": "ROLE_USER",
            "parts": [{"text": "안녕"}, {"data": {"foo": "bar"}}, {"text": "만들어줘"}],
        }
    }
    message = parse_message_send_request(body)

    assert extract_text(message) == "안녕\n만들어줘"


def test_build_artifact_shape():
    artifact = build_artifact("artifact-1", "결과", [{"text": "hi", "mediaType": "text/plain"}])

    assert artifact == {
        "artifactId": "artifact-1",
        "name": "결과",
        "parts": [{"text": "hi", "mediaType": "text/plain"}],
    }


def test_build_video_artifact_includes_markdown_and_json_parts():
    artifact = build_video_artifact("영상이 완성되었습니다.", "http://x/media/p.mp4")

    assert artifact["name"] == "영상 초안 결과"
    assert artifact["parts"][0] == {"text": "영상이 완성되었습니다.", "mediaType": "text/markdown"}
    assert artifact["parts"][1] == {
        "data": {"output_video_url": "http://x/media/p.mp4"},
        "mediaType": "application/json",
    }


def test_build_video_artifact_omits_json_part_when_no_url():
    artifact = build_video_artifact("실패했습니다.", None)

    assert len(artifact["parts"]) == 1


def test_build_unresolved_artifact_shape():
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand.png", "issues": ["too wide"]}]

    artifact = build_unresolved_artifact(scenes)

    assert artifact["parts"] == [{"data": {"unresolvedScenes": scenes}, "mediaType": "application/json"}]


def test_build_task_response_minimal():
    response = build_task_response("task-1", "ctx-1", TaskState.WORKING.value)

    assert response == {
        "task": {"id": "task-1", "contextId": "ctx-1", "status": {"state": "TASK_STATE_WORKING"}}
    }


def test_build_task_response_includes_answer_message():
    response = build_task_response("task-1", "ctx-1", TaskState.COMPLETED.value, answer="완료")

    assert response["task"]["status"]["message"] == {"parts": [{"text": "완료"}]}


def test_build_task_response_includes_unresolved_scenes_and_artifacts():
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand.png", "issues": []}]
    artifacts = [build_unresolved_artifact(scenes)]

    response = build_task_response(
        "task-1", "ctx-1", TaskState.INPUT_REQUIRED.value,
        answer="일부 장면에 수동 수정이 필요합니다", unresolved_scenes=scenes, artifacts=artifacts,
    )

    assert response["task"]["status"]["unresolvedScenes"] == scenes
    assert response["task"]["artifacts"] == artifacts


def test_build_task_response_omits_artifacts_key_when_none():
    response = build_task_response("task-1", "ctx-1", TaskState.WORKING.value)

    assert "artifacts" not in response["task"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_protocol.py -v`
Expected: FAIL — `video_draft_pipeline.a2a_server.protocol` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `src/video_draft_pipeline/a2a_server/protocol.py`:

```python
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskState(str, Enum):
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    REJECTED = "TASK_STATE_REJECTED"


class ProtocolError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class Part(BaseModel):
    text: str | None = None
    data: dict[str, Any] | None = None
    mediaType: str | None = None


class Message(BaseModel):
    messageId: str
    role: str
    parts: list[Part] = Field(default_factory=list)


def parse_message_send_request(body: dict) -> Message:
    raw_message = body.get("message")
    if not isinstance(raw_message, dict):
        raise ProtocolError("INVALID_ARGUMENT", "message must be an object")

    message_id = raw_message.get("messageId")
    if not isinstance(message_id, str) or not message_id:
        raise ProtocolError("INVALID_ARGUMENT", "message.messageId is required")

    role = raw_message.get("role")
    if role != "ROLE_USER":
        raise ProtocolError("INVALID_ARGUMENT", "message.role must be ROLE_USER")

    raw_parts = raw_message.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ProtocolError("INVALID_ARGUMENT", "message.parts must be a non-empty list")

    parts = [Part(**p) for p in raw_parts if isinstance(p, dict)]
    return Message(messageId=message_id, role=role, parts=parts)


def extract_text(message: Message) -> str:
    return "\n".join(part.text for part in message.parts if part.text)


def build_artifact(artifact_id: str, name: str, parts: list[dict]) -> dict:
    return {"artifactId": artifact_id, "name": name, "parts": parts}


def build_video_artifact(answer: str, output_video_url: str | None) -> dict:
    parts = [{"text": answer, "mediaType": "text/markdown"}]
    if output_video_url:
        parts.append({"data": {"output_video_url": output_video_url}, "mediaType": "application/json"})
    return build_artifact(f"artifact_{uuid.uuid4().hex[:8]}", "영상 초안 결과", parts)


def build_unresolved_artifact(unresolved_scenes: list[dict]) -> dict:
    parts = [{"data": {"unresolvedScenes": unresolved_scenes}, "mediaType": "application/json"}]
    return build_artifact(f"artifact_{uuid.uuid4().hex[:8]}", "수동 수정 필요 장면", parts)


def build_task_response(
    task_id: str,
    context_id: str,
    state: str,
    answer: str | None = None,
    unresolved_scenes: list[dict] | None = None,
    artifacts: list[dict] | None = None,
) -> dict:
    status: dict = {"state": state}
    if answer is not None:
        status["message"] = {"parts": [{"text": answer}]}
    if unresolved_scenes:
        status["unresolvedScenes"] = unresolved_scenes
    task: dict = {"id": task_id, "contextId": context_id, "status": status}
    if artifacts:
        task["artifacts"] = artifacts
    return {"task": task}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/test_protocol.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/protocol.py tests/a2a_server/test_protocol.py
git commit -m "feat: add A2A protocol module for message envelope parsing and artifact-shaped responses"
```

---

### Task 5: `auth.py` — Bearer + `A2A-Version` dependency

**Files:**
- Create: `src/video_draft_pipeline/a2a_server/auth.py`
- Test: `tests/a2a_server/test_auth.py`

**Interfaces:**
- Consumes: `error_response` from `errors.py` (Task 2's `UNAUTHENTICATED` mapping).
- Produces: `A2AAuthError(message: str)` (has `.message`). `require_a2a_auth(authorization: str | None, a2a_version: str | None) -> None` — a FastAPI dependency function, raises `A2AAuthError` on any auth failure. Consumed by Task 8's `app.py`, which must also register an `@app.exception_handler(A2AAuthError)` that returns `error_response("UNAUTHENTICATED", exc.message)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/a2a_server/test_auth.py`:

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.auth import A2AAuthError, require_a2a_auth
from video_draft_pipeline.a2a_server.errors import error_response


def _test_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(A2AAuthError)
    def _handle_auth_error(request, exc):
        return error_response("UNAUTHENTICATED", exc.message)

    @app.get("/protected", dependencies=[Depends(require_a2a_auth)])
    def protected():
        return {"ok": True}

    return app


def test_require_a2a_auth_accepts_valid_bearer_and_version(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get(
        "/protected", headers={"Authorization": "Bearer secret-token", "A2A-Version": "1.0"}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_require_a2a_auth_rejects_missing_authorization(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get("/protected", headers={"A2A-Version": "1.0"})

    assert response.status_code == 401
    assert response.json()["error"]["status"] == "UNAUTHENTICATED"


def test_require_a2a_auth_rejects_wrong_bearer_token(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get(
        "/protected", headers={"Authorization": "Bearer wrong-token", "A2A-Version": "1.0"}
    )

    assert response.status_code == 401


def test_require_a2a_auth_rejects_missing_a2a_version_header(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get("/protected", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 401


def test_require_a2a_auth_rejects_when_token_not_configured(monkeypatch):
    monkeypatch.delenv("VIDEO_SERVICE_TOKEN", raising=False)
    client = TestClient(_test_app())

    response = client.get(
        "/protected", headers={"Authorization": "Bearer anything", "A2A-Version": "1.0"}
    )

    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_auth.py -v`
Expected: FAIL — `video_draft_pipeline.a2a_server.auth` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `src/video_draft_pipeline/a2a_server/auth.py`:

```python
import os

from fastapi import Header


class A2AAuthError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def require_a2a_auth(
    authorization: str | None = Header(default=None),
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
) -> None:
    expected_token = os.environ.get("VIDEO_SERVICE_TOKEN")
    if not expected_token or authorization != f"Bearer {expected_token}":
        raise A2AAuthError("Invalid or missing Authorization Bearer token")
    if a2a_version != "1.0":
        raise A2AAuthError("Missing or unsupported A2A-Version header")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/test_auth.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/auth.py tests/a2a_server/test_auth.py
git commit -m "feat: add Bearer Service Token + A2A-Version auth dependency for /a2a routes"
```

---

### Task 6: `orchestrator.py` — optional cancellation checkpoint in `run_pipeline`

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py:122-221` (the `run_pipeline` function)
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Produces: `run_pipeline(..., should_cancel: Callable[[], bool] | None = None) -> Project`. When `should_cancel` is provided and returns `True` at the top of a scene iteration, `run_pipeline` stops dispatching further scenes, skips assembly, and returns the `Project` with only the scenes processed so far.
- No change to any other parameter or to per-scene processing logic.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_run_pipeline_stops_early_when_should_cancel_returns_true():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=20, brief="Halloween Event"
    )
    call_count = {"n": 0}

    def should_cancel():
        call_count["n"] += 1
        return call_count["n"] > 1

    project = run_pipeline(project_input, assemble=True, should_cancel=should_cancel)

    assert len(project.scenes) == 1
    assert project.output_video_url is None


def test_run_pipeline_runs_all_scenes_when_should_cancel_is_none():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=20, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert len(project.scenes) == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k should_cancel`
Expected: `test_run_pipeline_stops_early_when_should_cancel_returns_true` FAILs with `TypeError: run_pipeline() got an unexpected keyword argument 'should_cancel'`.

- [ ] **Step 3: Implement**

In `src/video_draft_pipeline/orchestrator.py`, add the parameter to `run_pipeline`'s signature (around line 122-137):

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    render_backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    image_edit_agent: ImageEditAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
    director_agent: DirectorAgentProtocol | None = None,
    assemble: bool = False,
    assembly_output_path: str | Path | None = None,
    project_store: ProjectStore | None = None,
    should_cancel: "Callable[[], bool] | None" = None,
) -> Project:
```

Add `from typing import Callable` to the existing imports at the top of the file (alongside the other stdlib imports).

Inside the `for scene in scenes:` loop (around line 165), add the checkpoint as the very first line of the loop body, and track whether it fired:

```python
    canceled = False
    for scene in scenes:
        if should_cancel is not None and should_cancel():
            canceled = True
            break

        running_cost = _charge(running_cost, prompt_agent.estimate_cost(), project_input.max_budget_usd)
        scene.prompts = prompt_agent.run(scene)
        # ... rest of the existing loop body is unchanged ...
```

Change the assembly guard (around line 216) from:

```python
    if assemble and all(not scene.needs_manual_fix for scene in project.scenes):
```

to:

```python
    if not canceled and assemble and all(not scene.needs_manual_fix for scene in project.scenes):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: all PASS, including the full pre-existing suite (confirms no regression to unrelated scene logic).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add optional should_cancel checkpoint to run_pipeline for coarse task cancellation"
```

---

### Task 7: `render_runner.py` — wire cancellation, fix manual-fix state, pass `output_video_url`

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/render_runner.py`
- Test: `tests/a2a_server/test_render_runner.py`

**Interfaces:**
- Consumes: `run_pipeline(..., should_cancel=...)` from Task 6; `TaskStore.mark_working/.mark_input_required/.mark_completed(..., output_video_url=...)` from Task 1.
- Produces: `default_render(project_input: ProjectInput, should_cancel: Callable[[], bool] | None = None) -> Project`. `run_render_task(task_store, task_id, project_input, media_public_base_url, render_fn: Callable[[ProjectInput], Project] | None = None) -> None` — on success with no manual fixes, calls `task_store.mark_completed(task_id, answer, output_video_url=url)`; on manual-fix-needed, calls `task_store.mark_input_required(task_id, answer)` instead of `mark_completed` (the bug fix from the spec); if `task_store.get(task_id).cancel_requested` is true after the render call, returns without overwriting the already-`CANCELED` state. `build_unresolved_scenes` is unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/a2a_server/test_render_runner.py`, update the existing `test_run_render_task_marks_completed_with_unresolved_scenes_message` test's assertion and add new tests. Replace the whole file's content with:

```python
from video_draft_pipeline.a2a_server.render_runner import build_unresolved_scenes, run_render_task
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.orchestrator import PipelineError
from video_draft_pipeline.schema import Candidate, ConsistencyReview, Project, ProjectInput, Prompts, Scene, Storyboard


def _project_input() -> ProjectInput:
    return ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="할로윈 이벤트")


def test_run_render_task_marks_completed_with_media_url_on_success():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        return Project(
            project_id="proj_abc123",
            input=project_input,
            output_video_url="media/proj_abc123.mp4",
        )

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_COMPLETED"
    assert "http://localhost:8002/media/proj_abc123.mp4" in updated.answer
    assert updated.output_video_url == "http://localhost:8002/media/proj_abc123.mp4"


def test_run_render_task_marks_failed_on_pipeline_error():
    store = TaskStore()
    record = store.create()

    def failing_render(project_input: ProjectInput) -> Project:
        raise PipelineError("Scene scene_01 was rejected after 3 retries")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=failing_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert "Scene scene_01 was rejected after 3 retries" in updated.answer


def test_run_render_task_marks_failed_on_unexpected_exception():
    store = TaskStore()
    record = store.create()

    def crashing_render(project_input: ProjectInput) -> Project:
        raise RuntimeError("boom")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=crashing_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert updated.answer == "영상 생성 중 알 수 없는 오류가 발생했습니다."


def test_run_render_task_sets_project_id_on_success():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        return Project(project_id="proj_abc123", input=project_input, output_video_url="media/proj_abc123.mp4")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    assert store.get(record.task_id).project_id == "proj_abc123"


def test_run_render_task_marks_input_required_with_unresolved_scenes_message():
    store = TaskStore()
    record = store.create()
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")

    def fake_render(project_input: ProjectInput) -> Project:
        scene = Scene(
            scene_id="scene_04", beat_id="resolution", order=4, duration_sec=5,
            storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
            needs_manual_fix=True,
            candidates=[Candidate(candidate_id="cand_1", image_url="media/a2a_server/cand_1.png", generated_by="m")],
        )
        project = Project(project_id="proj_partial", input=project_input)
        project.scenes = [scene]
        return project

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_INPUT_REQUIRED"
    assert updated.project_id == "proj_partial"
    assert "scene_04" in updated.answer
    assert "http://localhost:8002/media/a2a_server/cand_1.png" in updated.answer
    assert f"/tasks/{record.task_id}/scenes/" in updated.answer
    assert updated.unresolved_scenes == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": [],
            "referenceImageUrl": None,
        }
    ]


def test_run_render_task_does_not_overwrite_state_when_already_canceled():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        store.request_cancel(record.task_id)
        return Project(project_id="proj_abc123", input=project_input, output_video_url="media/p.mp4")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_CANCELED"


def test_run_render_task_does_not_mark_failed_when_canceled_during_pipeline_error():
    store = TaskStore()
    record = store.create()

    def failing_render(project_input: ProjectInput) -> Project:
        store.request_cancel(record.task_id)
        raise PipelineError("stopped")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=failing_render)

    assert store.get(record.task_id).state == "TASK_STATE_CANCELED"


def test_build_unresolved_scenes_returns_only_unresolved_with_issues():
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    resolved_review = ConsistencyReview(reviewed_by="r", passed=True, issues=[])
    unresolved_review = ConsistencyReview(reviewed_by="r", passed=False, issues=["shot too wide", "prop diagonal"])
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard,
        accepted_candidate_id="cand_ok",
        candidates=[
            Candidate(
                candidate_id="cand_ok", image_url="media/cand_ok.png", generated_by="m",
                consistency_review=resolved_review,
            )
        ],
    )
    bad_scene = Scene(
        scene_id="scene_04", beat_id="resolution", order=4, duration_sec=5,
        storyboard=storyboard,
        needs_manual_fix=True,
        candidates=[
            Candidate(
                candidate_id="cand_1", image_url="media/a2a_server/cand_1.png", generated_by="m",
                consistency_review=unresolved_review,
            )
        ],
    )
    project = Project(project_id="proj_partial", input=_project_input())
    project.scenes = [ok_scene, bad_scene]

    result = build_unresolved_scenes(project, "http://localhost:8002")

    assert result == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": ["shot too wide", "prop diagonal"],
            "referenceImageUrl": "http://localhost:8002/media/cand_ok.png",
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_render_runner.py -v`
Expected: `test_run_render_task_marks_input_required_with_unresolved_scenes_message` and the two cancellation tests FAIL — current code always calls `mark_completed` for the manual-fix path and has no cancellation awareness.

- [ ] **Step 3: Implement**

Replace `src/video_draft_pipeline/a2a_server/render_runner.py` entirely with:

```python
import logging
from typing import Callable

from ..agents.factory import build_real_agents
from ..agents.video_render_agent import VideoRenderAgent
from ..orchestrator import PipelineError, first_accepted_image_url, format_candidate_diagnostics, run_pipeline
from ..project_store import ProjectStore
from ..render_backends.veo_backend import VeoBackend
from ..schema import Project, ProjectInput

OUTPUT_DIR = "media/a2a_server"
PROJECT_STORE_DIR = f"{OUTPUT_DIR}/projects"

logger = logging.getLogger(__name__)


def default_render(project_input: ProjectInput, should_cancel: Callable[[], bool] | None = None) -> Project:
    agents = build_real_agents(output_dir=OUTPUT_DIR, log_path=f"{OUTPUT_DIR}/agent_log.jsonl")
    backend = VeoBackend(tier="veo-3.1-fast", output_dir=OUTPUT_DIR)
    project_store = ProjectStore(PROJECT_STORE_DIR)
    return run_pipeline(
        project_input, render_backend=backend, assemble=True, project_store=project_store,
        should_cancel=should_cancel, **agents
    )


def default_resume_render_agent() -> VideoRenderAgent:
    return VideoRenderAgent(backend=VeoBackend(tier="veo-3.1-fast", output_dir=OUTPUT_DIR))


def _unresolved_scenes_message(project: Project, media_public_base_url: str, task_id: str) -> str:
    lines = ["일부 장면에 수동 수정이 필요합니다:"]
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_image_url = f"{media_public_base_url}/{scene.candidates[-1].image_url}"
        lines.append(f"- {scene.scene_id}: {last_image_url}")
        lines.append(format_candidate_diagnostics(scene.candidates))
    lines.append(
        f"수정한 이미지를 POST /tasks/{task_id}/scenes/{{scene_id}}/resume 로 업로드해 주세요."
    )
    return "\n".join(lines)


def build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]:
    anchor_image_url = first_accepted_image_url(project.scenes)
    reference_image_url = f"{media_public_base_url}/{anchor_image_url}" if anchor_image_url else None
    entries = []
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_candidate = scene.candidates[-1]
        review = last_candidate.consistency_review
        entries.append({
            "sceneId": scene.scene_id,
            "imageUrl": f"{media_public_base_url}/{last_candidate.image_url}",
            "issues": review.issues if review else [],
            "referenceImageUrl": reference_image_url,
        })
    return entries


def run_render_task(
    task_store,
    task_id: str,
    project_input: ProjectInput,
    media_public_base_url: str,
    render_fn: Callable[[ProjectInput], Project] | None = None,
) -> None:
    def should_cancel() -> bool:
        record = task_store.get(task_id)
        return record is not None and record.cancel_requested

    actual_render_fn = render_fn or (lambda pi: default_render(pi, should_cancel=should_cancel))

    try:
        project = actual_render_fn(project_input)
    except PipelineError as exc:
        if not should_cancel():
            task_store.mark_failed(task_id, f"영상 생성에 실패했습니다: {exc}")
        return
    except Exception:
        logger.exception("render_runner: unexpected error during render")
        if not should_cancel():
            task_store.mark_failed(task_id, "영상 생성 중 알 수 없는 오류가 발생했습니다.")
        return

    if should_cancel():
        return

    task_store.set_project_id(task_id, project.project_id)

    if any(scene.needs_manual_fix for scene in project.scenes):
        unresolved = build_unresolved_scenes(project, media_public_base_url)
        task_store.set_unresolved_scenes(task_id, unresolved)
        task_store.mark_input_required(task_id, _unresolved_scenes_message(project, media_public_base_url, task_id))
        return

    url = f"{media_public_base_url}/{project.output_video_url}"
    task_store.mark_completed(task_id, f"영상 초안이 완성되었습니다.\n{url}", output_video_url=url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/test_render_runner.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/render_runner.py tests/a2a_server/test_render_runner.py
git commit -m "fix: manual-fix flow now reports TASK_STATE_INPUT_REQUIRED, wire cancellation through render_runner"
```

---

### Task 8: `app.py` — route reorg under `/a2a`, auth wiring, cancel endpoint, resume state transitions

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/app.py`
- Test: `tests/a2a_server/test_message_send.py`, `tests/a2a_server/test_get_task_route.py`, `tests/a2a_server/test_app_scaffold.py`, `tests/a2a_server/test_resume_endpoint.py` (additions only), new `tests/a2a_server/test_cancel_endpoint.py`

**Interfaces:**
- Consumes: `protocol.parse_message_send_request/extract_text/build_task_response/build_video_artifact/build_unresolved_artifact/TaskState/ProtocolError` (Task 4), `auth.require_a2a_auth/A2AAuthError` (Task 5), `tasks.TaskStore` (Task 1), `render_runner.run_render_task/build_unresolved_scenes/default_resume_render_agent` (Task 7).
- Produces: `create_app(...) -> FastAPI` with routes `POST /a2a/message:send`, `GET /a2a/tasks/{task_id}`, `POST /a2a/tasks/{task_id}:cancel` (all behind `require_a2a_auth`), `GET /.well-known/agent-card.json`, `POST /tasks/{task_id}/scenes/{scene_id}/resume` (both unauthenticated, unprefixed), `/media` static mount.

- [ ] **Step 1: Write the failing tests**

Replace `tests/a2a_server/test_message_send.py` entirely with:

```python
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
```

Replace `tests/a2a_server/test_get_task_route.py` entirely with:

```python
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
```

Update `tests/a2a_server/test_app_scaffold.py`: change the interface-url assertions from `/message:send` to `/a2a`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app


def test_agent_card_route_uses_configured_internal_url():
    app = create_app(self_internal_url="http://video-agent:8002")
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "video-agent"
    assert body["supportedInterfaces"][0]["url"] == "http://video-agent:8002/a2a"


def test_agent_card_route_does_not_require_auth():
    app = create_app(self_internal_url="http://video-agent:8002")
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200


def test_media_mount_serves_files_from_configured_media_dir(tmp_path):
    (tmp_path / "proj_test.mp4").write_bytes(b"fake-mp4-bytes")
    app = create_app(media_dir=str(tmp_path))
    client = TestClient(app)

    response = client.get("/media/proj_test.mp4")

    assert response.status_code == 200
    assert response.content == b"fake-mp4-bytes"


def test_default_internal_and_media_urls_come_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_INTERNAL_URL", "http://video-agent:9999")
    app = create_app(media_dir=str(tmp_path))
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.json()["supportedInterfaces"][0]["url"] == "http://video-agent:9999/a2a"
```

Create `tests/a2a_server/test_cancel_endpoint.py`:

```python
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
```

First, change `_setup_app`'s return statement in `tests/a2a_server/test_resume_endpoint.py` so tests can assert against the `TaskStore` directly (the old unprefixed `GET /tasks/{id}` route this file's tests might otherwise reach for no longer exists — task state is now only readable via the authenticated `/a2a/tasks/{id}` route, which is irrelevant to what these tests are checking):

```python
def _setup_app(tmp_path, scenes):
    media_dir = tmp_path / "media"
    project_store = ProjectStore(media_dir / "a2a_server" / "projects")
    project = Project(project_id="proj_resume_endpoint_test", input=_project_input())
    project.scenes = scenes
    project_store.save(project)

    store = TaskStore()
    record = store.create()
    store.set_project_id(record.task_id, project.project_id)
    store.mark_completed(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    app = create_app(
        task_store=store,
        media_dir=str(media_dir),
        project_store=project_store,
        resume_render_agent_fn=_stub_render_agent_fn,
    )
    return TestClient(app), record.task_id, project.project_id, store
```

Then update every existing call site in the file that unpacks `_setup_app(...)` from 3 values to 4 — every occurrence of `client, task_id, _ = _setup_app(...)` becomes `client, task_id, _, _ = _setup_app(...)` (7 call sites: `test_resume_endpoint_fully_resolves_and_assembles`, `test_resume_endpoint_leaves_other_unresolved_scenes_pending`, `test_resume_endpoint_404_for_unknown_scene`, `test_resume_endpoint_400_for_scene_not_needing_fix`, `test_resume_endpoint_rejects_unreadable_upload_content`, `test_resume_endpoint_accepts_real_image_regardless_of_filename_extension`, `test_resume_endpoint_normalizes_uploaded_image_to_target_resolution`). `test_resume_endpoint_404_for_unknown_task` and `test_resume_endpoint_works_via_project_id_when_task_store_has_no_record` build their `app`/`client` directly rather than via `_setup_app` and need no change.

Then append these two new tests:

```python
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
    assert store.get(task_id).state == "TASK_STATE_INPUT_REQUIRED"
```

```python
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
    assert store.get(task_id).state == "TASK_STATE_COMPLETED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/ -v`
Expected: many FAILs across `test_message_send.py`, `test_get_task_route.py`, `test_app_scaffold.py`, `test_cancel_endpoint.py` (routes don't exist at `/a2a/*` yet, no auth enforcement, no cancel route), and `test_resume_endpoint.py` (unpacking error from the changed `_setup_app` return arity, and `TASK_STATE_INPUT_REQUIRED` not yet set).

- [ ] **Step 3: Implement**

Replace `src/video_draft_pipeline/a2a_server/app.py` entirely with:

```python
import os
import uuid
from pathlib import Path
from typing import Callable

from fastapi import BackgroundTasks, Depends, FastAPI, File, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .agent_card import build_agent_card
from .auth import A2AAuthError, require_a2a_auth
from .brief_intake import BriefIntakeAgent, BriefIntakeError, IntakeResult
from .errors import error_response
from .protocol import (
    ProtocolError,
    TaskState,
    build_task_response,
    build_unresolved_artifact,
    build_video_artifact,
    extract_text,
    parse_message_send_request,
)
from .render_runner import build_unresolved_scenes, default_resume_render_agent, run_render_task
from .tasks import TaskStore
from ..agents.errors import MissingAPIKeyError
from ..agents.video_render_agent import VideoRenderAgent
from ..image_normalize import ImageNormalizeError, normalize_image_bytes
from ..orchestrator import PipelineError, resume_scene_with_image
from ..project_store import ProjectStore, ProjectStoreError
from ..render_backends.veo_backend import VeoBackendError
from ..schema import Project, ProjectInput

SERVER_MAX_BUDGET_USD = float(os.environ.get("SERVER_MAX_BUDGET_USD", "5.00"))
_TERMINAL_STATES = {
    TaskState.COMPLETED.value,
    TaskState.FAILED.value,
    TaskState.CANCELED.value,
    TaskState.REJECTED.value,
}


def _project_input_from_intake(intake: IntakeResult) -> ProjectInput:
    kwargs = {
        "preset": intake.preset or "이벤트",
        "scene_type": intake.scene_type or "인게임",
        "duration_sec": intake.duration_sec or 10,
        "brief": intake.brief,
    }
    if intake.max_budget_usd is not None:
        kwargs["max_budget_usd"] = min(intake.max_budget_usd, SERVER_MAX_BUDGET_USD)
    return ProjectInput(**kwargs)


def _task_response(record, media_public_base_url: str) -> dict:
    artifacts = None
    if record.state == TaskState.COMPLETED.value and record.output_video_url:
        artifacts = [build_video_artifact(record.answer, record.output_video_url)]
    elif record.state == TaskState.INPUT_REQUIRED.value and record.unresolved_scenes:
        artifacts = [build_unresolved_artifact(record.unresolved_scenes)]
    return build_task_response(
        record.task_id,
        record.context_id,
        record.state,
        answer=record.answer,
        unresolved_scenes=record.unresolved_scenes if record.state == TaskState.INPUT_REQUIRED.value else None,
        artifacts=artifacts,
    )


def create_app(
    self_internal_url: str | None = None,
    media_public_base_url: str | None = None,
    media_dir: str = "media",
    task_store: TaskStore | None = None,
    intake_agent: BriefIntakeAgent | None = None,
    render_fn: Callable[[ProjectInput], Project] | None = None,
    project_store: ProjectStore | None = None,
    resume_render_agent_fn: Callable[[], VideoRenderAgent] = default_resume_render_agent,
) -> FastAPI:
    internal_url = self_internal_url or os.environ.get("SELF_INTERNAL_URL", "http://video-agent:8002")
    store = task_store or TaskStore()
    media_url = media_public_base_url or os.environ.get("MEDIA_PUBLIC_BASE_URL", "http://localhost:8002")
    store_for_projects = project_store or ProjectStore(str(Path(media_dir) / "a2a_server" / "projects"))

    app = FastAPI()
    app.state.media_public_base_url = media_url
    app.state.task_store = store

    @app.exception_handler(A2AAuthError)
    def _handle_auth_error(request: Request, exc: A2AAuthError):
        return error_response("UNAUTHENTICATED", exc.message)

    Path(media_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict:
        return build_agent_card(internal_url)

    @app.get("/a2a/tasks/{task_id}", dependencies=[Depends(require_a2a_auth)])
    def get_task(task_id: str):
        record = store.get(task_id)
        if record is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")
        return _task_response(record, media_url)

    @app.post("/a2a/message:send", dependencies=[Depends(require_a2a_auth)])
    async def message_send(request: Request, background_tasks: BackgroundTasks):
        body = await request.json()
        try:
            message = parse_message_send_request(body)
        except ProtocolError as exc:
            return error_response(exc.status, exc.message)

        existing_task_id = store.task_id_for_message(message.messageId)
        if existing_task_id is not None:
            existing_record = store.get(existing_task_id)
            return _task_response(existing_record, media_url)

        text = extract_text(message)
        if not text:
            return error_response("INVALID_ARGUMENT", "message.parts must include non-empty text")

        try:
            agent = intake_agent or BriefIntakeAgent()
            intake = await run_in_threadpool(agent.run, text)
        except MissingAPIKeyError as exc:
            return error_response("UNAVAILABLE", str(exc))
        except BriefIntakeError as exc:
            return error_response("UNAVAILABLE", str(exc))

        if intake.clarifying_question:
            return {"message": {"parts": [{"text": intake.clarifying_question}]}}

        try:
            project_input = _project_input_from_intake(intake)
        except ValidationError as exc:
            return error_response("INVALID_ARGUMENT", str(exc))

        record = store.create()
        store.register_message_id(message.messageId, record.task_id)
        store.mark_working(record.task_id)
        background_tasks.add_task(run_render_task, store, record.task_id, project_input, media_url, render_fn)
        return _task_response(store.get(record.task_id), media_url)

    @app.post("/a2a/tasks/{task_id}:cancel", dependencies=[Depends(require_a2a_auth)])
    def cancel_task(task_id: str):
        record = store.get(task_id)
        if record is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")
        if record.state not in _TERMINAL_STATES:
            store.request_cancel(task_id)
            record = store.get(task_id)
        return _task_response(record, media_url)

    @app.post("/tasks/{task_id}/scenes/{scene_id}/resume")
    async def resume_scene(task_id: str, scene_id: str, file: UploadFile = File(...)):
        record = store.get(task_id)
        if record is not None and record.project_id is not None:
            project_id = record.project_id
        else:
            # Fallback: the in-memory TaskStore is empty after a server
            # restart, but ProjectStore is durable on disk. Accept task_id
            # doubling as a project_id (task_/proj_ prefixes never collide)
            # so a human can still resume using the project's own id.
            project_id = task_id

        try:
            project = store_for_projects.load(project_id)
        except ProjectStoreError as exc:
            return error_response("NOT_FOUND", str(exc))

        scene = next((s for s in project.scenes if s.scene_id == scene_id), None)
        if scene is None:
            return error_response("NOT_FOUND", f"Unknown scene: {scene_id}")
        if not scene.needs_manual_fix:
            return error_response("INVALID_ARGUMENT", f"Scene {scene_id} does not need a manual fix")

        contents = await file.read()
        try:
            contents = normalize_image_bytes(contents)
        except ImageNormalizeError as exc:
            return error_response("INVALID_ARGUMENT", str(exc))

        upload_dir = Path(media_dir) / "manual_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        # normalize_image_bytes always re-encodes as PNG, so the saved file
        # is always .png regardless of the uploaded filename's extension.
        image_path = upload_dir / f"{project.project_id}_{scene_id}_{uuid.uuid4().hex[:8]}.png"
        image_path.write_bytes(contents)

        try:
            project = await run_in_threadpool(
                resume_scene_with_image,
                project,
                scene_id,
                str(image_path),
                resume_render_agent_fn(),
                store_for_projects,
            )
        except (PipelineError, VeoBackendError, MissingAPIKeyError) as exc:
            return error_response("UNAVAILABLE", str(exc))

        remaining = build_unresolved_scenes(project, media_url)
        output_video_url = f"{media_url}/{project.output_video_url}" if project.output_video_url else None

        if record is not None:
            if remaining:
                store.set_unresolved_scenes(record.task_id, remaining)
                store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")
            else:
                answer = f"영상 초안이 완성되었습니다.\n{output_video_url}" if output_video_url else "영상 초안이 완성되었습니다."
                store.mark_completed(record.task_id, answer, output_video_url=output_video_url)

        return {
            "scene_id": scene_id,
            "resolved": True,
            "remaining_unresolved": remaining,
            "output_video_url": output_video_url,
        }

    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server/ -v`
Expected: all PASS.

Then run the full suite to confirm no regressions elsewhere: `pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/app.py tests/a2a_server/test_message_send.py tests/a2a_server/test_get_task_route.py tests/a2a_server/test_app_scaffold.py tests/a2a_server/test_cancel_endpoint.py tests/a2a_server/test_resume_endpoint.py
git commit -m "feat: move message:send/tasks/cancel under /a2a with auth, keep resume-upload and agent-card unprefixed"
```

---

### Task 9: `.env.example` — document `VIDEO_SERVICE_TOKEN`

**Files:**
- Modify: `.env.example`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Add the new variable**

Append to `.env.example`:

```
# A2A 1.0 protocol: Bearer Service Token the Orchestrator (Main Agent) must
# send as `Authorization: Bearer {VIDEO_SERVICE_TOKEN}` on every /a2a/*
# request, alongside an `A2A-Version: 1.0` header. Not read from any other
# location (never commit a real value here — see the team's A2A doc §15:
# tokens don't belong in Agent Cards, git, source, logs, or the browser).
VIDEO_SERVICE_TOKEN=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: document VIDEO_SERVICE_TOKEN env var for A2A Bearer auth"
```

---

### Task 10: `scripts/a2a_server_smoke_test.py` — update for `/a2a` prefix and auth headers

**Files:**
- Modify: `scripts/a2a_server_smoke_test.py`

**Interfaces:** none (manual script, not part of `pytest`).

- [ ] **Step 1: Update the script**

In `scripts/a2a_server_smoke_test.py`:

1. Add a `--service-token` CLI arg (defaults to reading `VIDEO_SERVICE_TOKEN` from the environment) in `parse_args()`:

```python
import os
...
    parser.add_argument("--service-token", default=os.environ.get("VIDEO_SERVICE_TOKEN", ""))
```

2. The agent card's `supportedInterfaces[0]["url"]` is now a base URL (`.../a2a`), not the full `message:send` URL — append the operation, and add the required headers:

```python
    interfaces = [i for i in card["supportedInterfaces"] if i["protocolBinding"] == "HTTP+JSON"]
    if not interfaces:
        raise SystemExit("Agent card has no HTTP+JSON supportedInterfaces entry")
    base_url = interfaces[0]["url"]
    message_send_url = f"{base_url}/message:send"

    payload = {
        "message": {
            "messageId": "smoke-test",
            "role": "ROLE_USER",
            "parts": [{"text": args.message}],
        },
        "metadata": {"mode": "video_draft", "locale": "ko", "context": {}, "evidence": []},
    }
    headers = {
        "content-type": "application/json",
        "Authorization": f"Bearer {args.service_token}",
        "A2A-Version": "1.0",
    }
    print(f"POST {message_send_url}")
    response = httpx.post(message_send_url, json=payload, headers=headers, timeout=10.0)
    response.raise_for_status()
    body = response.json()
```

3. Update the polling loop's terminal-state check and headers:

```python
    task_id = body["task"]["id"]
    task_url = f"{base_url}/tasks/{task_id}"
    print(f"task created: {task_id}, polling {task_url}")

    deadline = time.monotonic() + args.poll_timeout
    while True:
        task_response = httpx.get(task_url, headers=headers, timeout=5.0)
        task_response.raise_for_status()
        task = task_response.json()["task"]
        state = task["status"]["state"]
        if state in {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}:
            answer = task["status"].get("message", {}).get("parts", [{}])[0].get("text", "")
            print(f"\n{state}:\n{answer}")
            return 0 if state == "TASK_STATE_COMPLETED" else 1
        if time.monotonic() >= deadline:
            raise SystemExit(f"Polling timed out after {args.poll_timeout}s, last state: {state}")
        print(f"  ...{state}, waiting {args.poll_interval}s")
        time.sleep(args.poll_interval)
```

4. Update the module docstring's usage example to mention setting `VIDEO_SERVICE_TOKEN` before running.

- [ ] **Step 2: Manual verification (not automated — real billed calls)**

Run by hand, with a real `GEMINI_API_KEY`/`VEO_API_KEY` and a `VIDEO_SERVICE_TOKEN` set on both the server and this script:

```bash
VIDEO_SERVICE_TOKEN=dev-secret SELF_INTERNAL_URL=http://localhost:8002 uvicorn video_draft_pipeline.a2a_server.app:app --host 0.0.0.0 --port 8002
# separate terminal:
VIDEO_SERVICE_TOKEN=dev-secret python scripts/a2a_server_smoke_test.py --message "할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"
```

Expected: the script authenticates successfully against the `/a2a/*` routes and polls through to `TASK_STATE_COMPLETED`.

- [ ] **Step 3: Commit**

```bash
git add scripts/a2a_server_smoke_test.py
git commit -m "chore: update smoke test script for /a2a route prefix and Bearer auth"
```

---

## Post-plan note (not a task)

Once all 10 tasks are merged, video-agent speaks the new A2A format exclusively (hard cutover, per the spec). This will break Main Agent's *current* integration until your teammate's rewrite of `AI-agent_game_platform` lands — that's expected and was the explicit tradeoff accepted during brainstorming. Worth pinging the teammate once this lands so the gap window stays short.
