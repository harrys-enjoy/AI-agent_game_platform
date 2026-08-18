from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError


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

    try:
        parts = [Part(**p) for p in raw_parts if isinstance(p, dict)]
        return Message(messageId=message_id, role=role, parts=parts)
    except ValidationError as exc:
        raise ProtocolError("INVALID_ARGUMENT", str(exc))


def extract_text(message: Message) -> str:
    return "\n".join(part.text for part in message.parts if part.text)


def build_artifact(artifact_id: str, name: str, parts: list[dict]) -> dict:
    return {"artifactId": artifact_id, "name": name, "parts": parts}


def build_video_artifact(artifact_id: str, answer: str, output_video_url: str | None) -> dict:
    parts = [{"text": answer, "mediaType": "text/markdown"}]
    if output_video_url:
        parts.append({"data": {"output_video_url": output_video_url}, "mediaType": "application/json"})
    return build_artifact(artifact_id, "영상 초안 결과", parts)


def build_unresolved_artifact(artifact_id: str, unresolved_scenes: list[dict]) -> dict:
    parts = [{"data": {"unresolvedScenes": unresolved_scenes}, "mediaType": "application/json"}]
    return build_artifact(artifact_id, "수동 수정 필요 장면", parts)


def build_task_response(
    task_id: str,
    context_id: str,
    state: str,
    answer: str | None = None,
    detail: str | None = None,
    unresolved_scenes: list[dict] | None = None,
    artifacts: list[dict] | None = None,
) -> dict:
    status: dict = {"state": state}
    if answer is not None:
        parts = [{"text": answer}]
        if detail:
            parts.append({"text": detail})
        status["message"] = {"parts": parts}
    if unresolved_scenes:
        status["unresolvedScenes"] = unresolved_scenes
    task: dict = {"id": task_id, "contextId": context_id, "status": status}
    if artifacts:
        task["artifacts"] = artifacts
    return {"task": task}
