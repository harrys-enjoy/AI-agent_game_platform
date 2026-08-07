import asyncio
import time
from typing import Any

import httpx

from .contracts import AgentCard
from .errors import A2AError


class A2AClient:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
        poll_interval: float = 1.0,
        poll_timeout: float = 30.0,
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

    async def send_message(
        self,
        agent_url: str,
        request: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        is_http_json = agent_url.rstrip("/").endswith("/message:send")
        if is_http_json:
            payload = {
                "message": {
                    "messageId": request.get("request_id", "main-agent"),
                    "role": "ROLE_USER",
                    "parts": [{"text": request.get("message", "")}],
                    **({"contextId": request["context_id"]} if request.get("context_id") else {}),
                },
                "metadata": {
                    "mode": request.get("mode", "game_qa"),
                    "locale": request.get("locale", "ko"),
                    "context": request.get("context", {}),
                    "evidence": request.get("evidence", []),
                    **({"systemPrompt": request["system_prompt"]} if request.get("system_prompt") else {}),
                },
            }
        else:
            payload = {"jsonrpc": "2.0", "id": "main-agent", "method": "SendMessage", "params": request}
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
            response = await client.post(
                agent_url,
                json=payload,
                headers={"content-type": "application/a2a+json", **(headers or {})} if is_http_json else headers,
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
                    return {"status": "succeeded", "answer": answer, "raw": body}
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
                    return {"status": status, "answer": answer, "task": task, "raw": body}
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"A2A Task polling timed out: {task_url}")
                await asyncio.sleep(self.poll_interval)
