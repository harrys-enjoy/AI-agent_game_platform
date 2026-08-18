import pytest

from app.contracts import AgentCard
from app.orchestrator import Orchestrator


class FakeClient:
    async def send_message(self, agent_url, request):
        return {"agent": agent_url, "summary": request["message"]}


class FakeRouter:
    async def select(self, request):
        return {"selected_agents": ["game-qna-agent"], "confidence": 0.95}


@pytest.mark.asyncio
async def test_orchestrator_runs_compound_request():
    cards = [
        AgentCard(name="dev-agent", description="development", url="dev", skills=[{"id": "code_review", "name": "code review"}]),
        AgentCard(name="game-qna-agent", description="game", url="game", skills=[{"id": "game_qa", "name": "game Q&A"}]),
    ]
    result = await Orchestrator(FakeClient()).run("게임 설정을 확인하고 코드를 리뷰해줘", cards)

    assert result.status == "succeeded"
    assert len(result.result["results"]) == 2


@pytest.mark.asyncio
async def test_orchestrator_prefers_router_selection():
    cards = [
        AgentCard(name="dev-agent", description="development", url="dev", skills=[]),
        AgentCard(name="game-qna-agent", description="game", url="game", skills=[]),
    ]
    selected = await Orchestrator(FakeClient(), router=FakeRouter()).select("세계관 캐릭터를 정리해줘", cards)

    assert [card.name for card in selected] == ["game-qna-agent"]
