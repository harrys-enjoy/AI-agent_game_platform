from dataclasses import dataclass
from collections.abc import Mapping

import httpx

from .a2a_client import A2AClient
from .contracts import AgentCard


@dataclass
class AgentStatus:
    available: bool = False
    error: str | None = None


@dataclass(frozen=True)
class AgentConfig:
    name: str
    base_url: str
    token: str | None = None


class AgentRegistry:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 1.0):
        self.client = A2AClient(transport=transport, timeout=timeout)
        self._configured: dict[str, AgentConfig] = {}
        self._cards: dict[str, AgentCard] = {}
        self._statuses: dict[str, AgentStatus] = {}

    @staticmethod
    def _base_url(url: str) -> str:
        return url.rstrip("/").rsplit("/message:send", 1)[0].removesuffix("/a2a")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AgentRegistry":
        registry = cls()
        names = [name.strip() for name in environ.get("AGENT_REGISTRY", "").split(",") if name.strip()]
        if not names:
            names = ["workmate-agent", "video-agent", "dev-agent", "game-qna-agent"]
        defaults = {
            "workmate-agent": "http://workmate-agent:8001",
            "video-agent": "http://video-agent:8002",
            "dev-agent": "http://dev-agent:8003",
            "game-qna-agent": "http://game-qa-agent:3000",
        }
        for name in names:
            env_name = name.removesuffix("-agent").upper().replace("-", "_")
            url = environ.get(f"{env_name}_AGENT_URL")
            if name == "game-qna-agent":
                url = url or environ.get("GAME_QA_AGENT_URL")
            url = url or defaults.get(name)
            if url:
                token = environ.get(f"{env_name}_AGENT_TOKEN") or None
                registry.register(name, url, token)
        return registry

    def register(self, name: str, base_url: str, token: str | None = None) -> None:
        self._configured[name] = AgentConfig(name=name, base_url=self._base_url(base_url), token=token)
        self._statuses.setdefault(name, AgentStatus())

    async def refresh(self) -> dict[str, AgentCard]:
        for name, config in self._configured.items():
            try:
                card = await self.client.get_agent_card(config.base_url)
                endpoint = self.client.select_http_json_endpoint(card)
                if endpoint:
                    card = card.model_copy(update={"url": endpoint})
                self._cards[name] = card
                self._statuses[name] = AgentStatus(available=True)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                self._statuses[name] = AgentStatus(available=False, error=str(exc))
        return dict(self._cards)

    def available(self) -> list[AgentCard]:
        return [self._cards[name] for name, status in self._statuses.items() if status.available and name in self._cards]

    def status(self, name: str) -> AgentStatus:
        return self._statuses.get(name, AgentStatus(error="Agent is not registered"))

    def config(self, name: str) -> AgentConfig:
        return self._configured[name]

    def headers(self, name: str) -> dict[str, str]:
        config = self.config(name)
        return {"Authorization": f"Bearer {config.token}"} if config.token else {}
