import httpx
import pytest

from app.registry import AgentRegistry


@pytest.mark.asyncio
async def test_registry_marks_failed_card_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    registry = AgentRegistry(transport=transport)
    registry.register("workmate-agent", "http://workmate-agent:8001")

    cards = await registry.refresh()

    assert cards == {}
    assert registry.status("workmate-agent").available is False
