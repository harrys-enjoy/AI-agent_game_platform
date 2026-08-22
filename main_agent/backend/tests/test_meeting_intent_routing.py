import pytest

from app import main


@pytest.mark.asyncio
async def test_meeting_analysis_intent_routes_to_workmate_before_router(monkeypatch):
    class FailIfCalled:
        async def select(self, request):
            raise AssertionError("meeting analysis should bypass the general router")

    monkeypatch.setattr(main, "router", FailIfCalled())

    result = await main.resolve_internal_chat_route("오늘 회의 내용 분석해줘")

    assert result == {"agent": "workmate-agent", "needs_selection": False}
