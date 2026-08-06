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

    async def send_message(self, agent_url: str, request: dict[str, Any]) -> dict[str, Any]:
        is_http_json = agent_url.rstrip("/").endswith("/message:send")
        if is_http_json:
            payload = {
                "message": {
                    "messageId": "main-agent",
                    "role": "ROLE_USER",
                    "parts": [{"text": request.get("message", "")}],
                },
                "metadata": {
                    "mode": request.get("mode", "game_qa"),
                    "locale": request.get("locale", "ko"),
                    **({"systemPrompt": request["system_prompt"]} if request.get("system_prompt") else {}),
                },
            }
        else:
            payload = {"jsonrpc": "2.0", "id": "main-agent", "method": "SendMessage", "params": request}
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
            response = await client.post(agent_url, json=payload)
            if response.is_error:
                raise RuntimeError(f"A2A HTTP {response.status_code}: {response.text}")
            body = response.json()
            if is_http_json and "message" in body:
                text = body.get("message", {}).get("parts", [{}])[0].get("text", "")
                return {"status": "succeeded", "answer": text, "raw": body}
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "A2A request failed"))
            return body.get("result", {})
