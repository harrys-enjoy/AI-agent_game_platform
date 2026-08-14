import uuid
from typing import Any, Literal

import httpx

from .errors import A2AError
from .registry import AgentRegistry

A2A_VERSION = "1.0"


def _headers(registry: AgentRegistry) -> dict[str, str]:
    headers = dict(registry.headers("video-agent"))
    headers["A2A-Version"] = A2A_VERSION
    return headers


async def _call(url: str, method: Literal["post", "get"], *, headers: dict[str, str], json: dict | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if method == "post":
                response = await client.post(url, json=json, headers=headers)
            else:
                response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"video-agent unreachable: {exc}") from exc
    if response.is_error:
        try:
            raise A2AError.from_payload(response.json(), response.status_code)
        except ValueError:
            raise RuntimeError(f"video-agent HTTP {response.status_code}: {response.text}") from None
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"video-agent returned a non-JSON response: {response.text}") from None
    if not isinstance(payload, dict):
        raise RuntimeError("video-agent returned an unexpected response shape")
    return payload


async def send_message(registry: AgentRegistry, text: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    body = {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]}}
    return await _call(f"{config.base_url}/a2a/message:send", "post", headers=_headers(registry), json=body)


async def get_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}", "get", headers=_headers(registry))


async def cancel_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}:cancel", "post", headers=_headers(registry))
