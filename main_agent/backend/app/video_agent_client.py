import uuid
from typing import Any, Literal
from urllib.parse import quote

import httpx

from .errors import A2AError
from .registry import AgentRegistry

A2A_VERSION = "1.0"


def _headers(registry: AgentRegistry) -> dict[str, str]:
    headers = dict(registry.headers("video-agent"))
    headers["A2A-Version"] = A2A_VERSION
    return headers


async def _call(
    url: str,
    method: Literal["post", "get", "delete"],
    *,
    headers: dict[str, str],
    json: dict | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "post":
                response = await client.post(url, json=json, headers=headers)
            elif method == "delete":
                response = await client.delete(url, headers=headers)
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


async def send_message(registry: AgentRegistry, text: str, user_id: str | None = None) -> dict[str, Any]:
    config = registry.config("video-agent")
    body = {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]}}
    headers = _headers(registry)
    if user_id:
        # HTTP header values must be ASCII/latin-1 - percent-encode (assignee
        # names are Korean), same convention as workmate's X-Workmate-Assignee.
        headers["X-Video-Agent-User"] = quote(user_id)
    return await _call(f"{config.base_url}/a2a/message:send", "post", headers=headers, json=body, timeout=60.0)


async def get_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}", "get", headers=_headers(registry))


async def list_tasks(registry: AgentRegistry, user_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    config = registry.config("video-agent")
    url = f"{config.base_url}/a2a/tasks?user_id={quote(user_id)}&limit={limit}&offset={offset}"
    return await _call(url, "get", headers=_headers(registry))


async def get_task_detail(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}/detail", "get", headers=_headers(registry))


async def cancel_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}:cancel", "post", headers=_headers(registry))


async def delete_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}", "delete", headers=_headers(registry))


async def get_veo_usage(registry: AgentRegistry) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/veo-usage", "get", headers=_headers(registry))
