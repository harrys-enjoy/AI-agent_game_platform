import json
import os
from typing import Any

import httpx


ROUTABLE_AGENTS = (
    "workmate-agent",
    "video-agent",
    "dev-agent",
    "game-qna-agent",
)

ROUTER_SYSTEM_PROMPT = """You are the routing classifier for an AI workspace.
Choose one or more agents for the user's request. The current chat label is only a UI entry point; ignore it and classify the request itself.
Allowed agents only: workmate-agent, video-agent, dev-agent, game-qna-agent.
Use game-qna-agent for game lore, RPG characters, factions, items, monsters, and story review.
Use video-agent for video generation, scenes, shots, camera, lighting, or visual prompts.
Use dev-agent for code, bugs, tests, APIs, deployment, or programming.
Use workmate-agent for meetings, reports, schedules, business tasks, and general office work.
Examples: "오늘 할 일과 우선순위를 정리해줘" -> workmate-agent; "회의 녹음을 정리해줘" -> workmate-agent; "전투 장면 영상을 만들어줘" -> video-agent; "이 코드의 오류를 찾아줘" -> dev-agent; "전우치의 세계관을 설명해줘" -> game-qna-agent.
Return JSON only, with this exact shape:
{"selected_agents":["agent-name"],"confidence":0.0,"needs_clarification":false}
Select multiple agents only when the request genuinely needs multiple independent capabilities.
"""


class RouterLLM:
    def __init__(self, env: dict[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None):
        env = env or os.environ
        self.enabled = (env.get("ROUTER_LLM_ENABLED") or env.get("MODEL_ENABLED", "false")).lower() == "true"
        router_model, router_base, router_key = env.get("ROUTER_MODEL_NAME"), env.get("ROUTER_BASE_URL"), env.get("ROUTER_API_KEY")
        if self.enabled and not (router_model and router_base and router_key):
            # main_agent/.env is shared with game-qna-agent, which sets its own MODEL_NAME/
            # MODEL_BASE_URL/MODEL_API_KEY for its own LLM calls. Falling back to those same
            # names here would silently point request-routing at qna_agent's model instead of
            # a router-specific one - warn loudly rather than let that happen quietly.
            import warnings

            warnings.warn(
                "RouterLLM: ROUTER_LLM_ENABLED is true but ROUTER_MODEL_NAME/ROUTER_BASE_URL/ROUTER_API_KEY "
                "aren't all set - falling back to MODEL_NAME/MODEL_BASE_URL/MODEL_API_KEY, which is also "
                "game-qna-agent's own LLM config in the shared main_agent/.env. Set ROUTER_* explicitly if "
                "the router should use a different model.",
                stacklevel=2,
            )
        self.model = router_model or env.get("MODEL_NAME", "")
        self.base_url = (router_base or env.get("MODEL_BASE_URL") or env.get("QWEN_BASE_URL", "")).rstrip("/")
        self.api_key = router_key or env.get("MODEL_API_KEY", "")
        self.timeout = float(env.get("ROUTER_TIMEOUT_SECONDS", "8"))
        self.transport = transport

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.model and self.base_url and self.api_key)

    async def select(self, request: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": request},
            ],
            "temperature": 0,
            "max_tokens": 200,
        }
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                result = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError):
            return None

        selected = [agent for agent in result.get("selected_agents", []) if agent in ROUTABLE_AGENTS]
        try:
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if not selected or confidence < 0.6 or result.get("needs_clarification"):
            return None
        lower_request = request.lower()
        if any(term in lower_request for term in ("스케줄", "일정", "회의", "오늘 할 일", "우선순위", "업무", "보고서")):
            selected = ["workmate-agent"]
        return {"selected_agents": selected, "confidence": confidence}

    async def review(self, request: str, agent: str, answer: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        prompt = f"""Review whether the selected agent handled the request.
Request: {request}
Selected agent: {agent}
Answer: {answer}
Return JSON only: {{\"accepted\":true,\"replacement_agent\":null,\"reason\":\"...\"}}.
If the answer is clearly outside the agent's responsibility, set accepted=false and choose one replacement agent from: {', '.join(ROUTABLE_AGENTS)}.
"""
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json={"model": self.model, "messages": [{"role": "system", "content": prompt}], "temperature": 0, "max_tokens": 160},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                result = json.loads(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError):
            return None
        replacement = result.get("replacement_agent")
        if replacement not in ROUTABLE_AGENTS:
            replacement = None
        return {"accepted": bool(result.get("accepted", True)), "replacement_agent": replacement, "reason": str(result.get("reason", ""))}
