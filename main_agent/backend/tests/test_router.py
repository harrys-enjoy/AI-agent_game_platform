import json

import httpx
import pytest

from app.router import RouterLLM


class RouterTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        body = json.dumps({
            "choices": [{"message": {"content": '{"selected_agents":["video-agent"],"confidence":0.95,"needs_clarification":false}'}}],
        }).encode()
        return httpx.Response(200, content=body, request=request)


@pytest.mark.asyncio
async def test_router_selects_agent_from_structured_llm_response():
    router = RouterLLM({
        "ROUTER_LLM_ENABLED": "true",
        "ROUTER_MODEL_NAME": "router-model",
        "ROUTER_BASE_URL": "https://example.test/v1",
        "ROUTER_API_KEY": "secret",
    }, transport=RouterTransport())

    result = await router.select("전투 장면 영상을 만들어줘")

    assert result == {"selected_agents": ["video-agent"], "confidence": 0.95}


@pytest.mark.asyncio
async def test_router_returns_none_for_low_confidence():
    class LowConfidenceTransport(RouterTransport):
        async def handle_async_request(self, request):
            response = await super().handle_async_request(request)
            response._content = json.dumps({
                "choices": [{"message": {"content": '{"selected_agents":["video-agent"],"confidence":0.3}'}}],
            }).encode()
            return response

    router = RouterLLM({
        "ROUTER_LLM_ENABLED": "true",
        "ROUTER_MODEL_NAME": "router-model",
        "ROUTER_BASE_URL": "https://example.test/v1",
        "ROUTER_API_KEY": "secret",
    }, transport=LowConfidenceTransport())

    assert await router.select("모호한 요청") is None
