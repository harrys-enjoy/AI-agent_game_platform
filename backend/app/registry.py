from dataclasses import dataclass

import httpx

from .a2a_client import A2AClient
from .contracts import AgentCard


@dataclass
class AgentStatus:
    available: bool = False
    error: str | None = None


class AgentRegistry:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 1.0):
        self.client = A2AClient(transport=transport, timeout=timeout)
        self._configured: dict[str, str] = {}
        self._cards: dict[str, AgentCard] = {}
        self._statuses: dict[str, AgentStatus] = {}

    def register(self, name: str, base_url: str) -> None:
        self._configured[name] = base_url
        self._statuses.setdefault(name, AgentStatus())

    async def refresh(self) -> dict[str, AgentCard]:
        for name, base_url in self._configured.items():
            try:
                card = await self.client.get_agent_card(base_url)
                self._cards[name] = card
                self._statuses[name] = AgentStatus(available=True)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                self._statuses[name] = AgentStatus(available=False, error=str(exc))
        return dict(self._cards)

    def available(self) -> list[AgentCard]:
        return [self._cards[name] for name, status in self._statuses.items() if status.available and name in self._cards]

    def status(self, name: str) -> AgentStatus:
        return self._statuses.get(name, AgentStatus(error="Agent is not registered"))
