import asyncio
import time
import uuid
from typing import Any

import httpx

from .contracts import AgentCard
from .errors import A2AError


class A2AClient:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 600.0,
        poll_interval: float = 1.0,
        poll_timeout: float = 600.0,
    ):
        self.transport = transport
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    async def get_agent_card(self, base_url: str) -> AgentCard:
        card_url = base_url.rstrip("/") + "/.well-known/agent-card.json"
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
            response = await client.get(card_url)
            response.raise_for_status()
            return AgentCard.model_validate(response.json())

    @staticmethod
    def select_http_json_endpoint(card: AgentCard) -> str | None:
        for interface in card.supported_interfaces:
            if interface.protocol_binding == "HTTP+JSON" and interface.protocol_version == "1.0":
                return interface.url
        return None

    @staticmethod
    def _read_text_parts(parts: Any) -> str:
        if not isinstance(parts, list):
            return ""
        return "\n".join(part["text"] for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))

    @classmethod
    def _extract_answer(cls, body: dict[str, Any]) -> str:
        message_answer = cls._read_text_parts(body.get("message", {}).get("parts"))
        if message_answer:
            return message_answer
        task_status = body.get("task", {}).get("status", {})
        task_answer = cls._read_text_parts(task_status.get("message", {}).get("parts"))
        if task_answer:
            return task_answer
        for artifact in body.get("task", {}).get("artifacts", []):
            artifact_answer = cls._read_text_parts(artifact.get("parts"))
            if artifact_answer:
                return artifact_answer
        return ""

    @staticmethod
    def _extract_pending_action(body: dict[str, Any]) -> dict[str, Any] | None:
        """`assistant_ask`가 확인이 필요한 동작(예: `analyze_meeting`)을 골랐을 때
        같은 Artifact의 JSON Data Part에 실어 보내는 `pending_action`을 읽는다
        (`app/a2a/runtime.py::_artifact_parts`, `assistant_ask_workflow`가 만드는
        `{"type": "assistant_reply", "data": {...}}` 봉투 — `workmate-agent`의
        `tools/m51_legacy_adapter.py::_legacy_response`와 같은 자리를 읽는 로직이다).
        확인 없이 자동 실행하면 안 되는 동작이라, 이 값이 있으면 `chat_reply()`가
        안내 문구를 답변에 덧붙인다(2026-08-19 실사용 중 발견 — 이게 없으면 채팅이
        확인을 기다리며 "죽은 것처럼" 그냥 멈춰 보였다).

        `message:send`(`{"task": {...}}`로 감싼 응답)와 `GET .../tasks/{id}`(Task
        객체가 그대로 최상위에 오는 응답) 둘 다 받을 수 있다 — `m51_legacy_adapter.py::
        _legacy_response`와 같은 두 모양 판별을 그대로 따른다."""

        task = body.get("task")
        if not isinstance(task, dict):
            task = body if isinstance(body.get("status"), dict) else None
        if not isinstance(task, dict):
            return None
        for artifact in task.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            for part in artifact.get("parts", []):
                if not isinstance(part, dict):
                    continue
                data = part.get("data")
                if isinstance(data, dict) and data.get("type") == "assistant_reply":
                    reply_data = data.get("data")
                    if isinstance(reply_data, dict) and reply_data.get("pending_action"):
                        return reply_data["pending_action"]
        return None

    async def send_message(
        self,
        agent_url: str,
        request: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        agent_url = agent_url.rstrip("/")
        if agent_url.endswith("/a2a"):
            agent_url += "/message:send"
        is_http_json = agent_url.endswith("/message:send")
        if is_http_json:
            parts = [{"text": request.get("message", "")}]
            if request.get("skill_id"):
                data: dict[str, Any] = {
                    "skill_id": request["skill_id"],
                    "message": request.get("message", ""),
                }
                # 확인 버튼 재전송(`main.py::chat_reply()`가 `ChatReplyRequest.confirmed_skill_id`
                # 를 받았을 때) — 그대로 실어 보내면 workmate-agent의
                # `assistant_ask_workflow()`가 route()를 다시 안 묻고 바로 실행한다.
                if request.get("confirmed_skill_id"):
                    data["confirmed_skill_id"] = request["confirmed_skill_id"]
                    data["confirmed_arguments"] = request.get("confirmed_arguments") or {}
                parts = [{"data": data, "mediaType": "application/json"}]
            payload = {
                "message": {
                    "messageId": request.get("request_id") or str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "parts": parts,
                    **({"contextId": request["context_id"]} if request.get("context_id") else {}),
                },
                "metadata": {
                    "mode": request.get("mode", "game_qa"),
                    "locale": request.get("locale", "ko"),
                    "context": request.get("context", {}),
                    "evidence": request.get("evidence", []),
                    "owner": request.get("owner"),
                    **({"systemPrompt": request["system_prompt"]} if request.get("system_prompt") else {}),
                },
            }
        else:
            payload = {"jsonrpc": "2.0", "id": "main-agent", "method": "SendMessage", "params": request}
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
            response = await client.post(
                agent_url,
                json=payload,
                headers={"content-type": "application/a2a+json", "A2A-Version": "1.0", **(headers or {})} if is_http_json else headers,
            )
            if response.is_error:
                try:
                    raise A2AError.from_payload(response.json(), response.status_code)
                except ValueError:
                    raise RuntimeError(f"A2A HTTP {response.status_code}: {response.text}") from None
            body = response.json()
            if is_http_json:
                answer = self._extract_answer(body)
                if answer:
                    return {"status": "succeeded", "answer": answer, "pending_action": self._extract_pending_action(body), "raw": body}
                if body.get("task"):
                    task = body["task"]
                    task_url = task.get("url")
                    if not task_url and task.get("id"):
                        task_url = agent_url.rsplit("/message:send", 1)[0].rstrip("/") + f"/tasks/{task['id']}"
                    if task_url:
                        return await self.poll_task(task_url, headers=headers)
                    return {"status": "running", "task": task, "raw": body}
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "A2A request failed"))
            return body.get("result", {})

    async def poll_task(self, task_url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        terminal = {
            "TASK_STATE_COMPLETED": "succeeded",
            "TASK_STATE_FAILED": "failed",
            "TASK_STATE_CANCELED": "cancelled",
            "completed": "succeeded",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        deadline = time.monotonic() + self.poll_timeout
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
            while True:
                response = await client.get(task_url, headers=headers)
                if response.is_error:
                    try:
                        raise A2AError.from_payload(response.json(), response.status_code)
                    except ValueError:
                        raise RuntimeError(f"A2A Task HTTP {response.status_code}: {response.text}") from None
                body = response.json()
                task = body.get("task", body)
                state = task.get("status", {}).get("state", task.get("status"))
                status = terminal.get(state)
                answer = self._extract_answer(body)
                if status:
                    return {"status": status, "answer": answer, "pending_action": self._extract_pending_action(body), "task": task, "raw": body}
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"A2A Task polling timed out: {task_url}")
                await asyncio.sleep(self.poll_interval)
