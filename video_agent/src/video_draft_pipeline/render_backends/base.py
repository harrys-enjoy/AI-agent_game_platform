from typing import Protocol

from ..schema import Candidate, RenderResult


class RenderBackend(Protocol):
    name: str

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        ...

    def estimate_cost(self, duration_sec: float) -> float:
        ...
