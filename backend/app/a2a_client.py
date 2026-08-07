from typing import Any

import httpx

from .contracts import AgentCard


class A2AClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 5.0):
        self.transport = transport
        self.timeout = timeout

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
                raise RuntimeError(f"A2A HTTP {response.status_code}: {response.text}")
            body = response.json()
            if is_http_json:
                answer = self._extract_answer(body)
                if answer:
                    return {"status": "succeeded", "answer": answer, "raw": body}
                if body.get("task"):
                    return {"status": "running", "task": body["task"], "raw": body}
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "A2A request failed"))
            return body.get("result", {})
