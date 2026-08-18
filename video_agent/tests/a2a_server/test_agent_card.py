from video_draft_pipeline.a2a_server.agent_card import build_agent_card


def test_build_agent_card_has_video_agent_identity():
    card = build_agent_card("http://video-agent:8002")

    assert card["name"] == "video-agent"
    assert card["url"] == "http://video-agent:8002/a2a"
    assert card["skills"] == [{"id": "video_draft", "name": "영상 초안"}]


def test_build_agent_card_supported_interfaces_url_matches_base_url():
    card = build_agent_card("http://video-agent:8002")

    assert card["supportedInterfaces"] == [
        {
            "url": "http://video-agent:8002/a2a",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }
    ]
    assert card["capabilities"] == {"streaming": False}
    assert card["securitySchemes"] == {}


def test_build_agent_card_url_and_supported_interfaces_url_are_identical():
    card = build_agent_card("http://video-agent:8002")

    assert card["url"] == card["supportedInterfaces"][0]["url"]


def test_build_agent_card_respects_a_different_internal_url():
    card = build_agent_card("http://localhost:9000")

    assert card["url"] == "http://localhost:9000/a2a"
    assert card["supportedInterfaces"][0]["url"] == "http://localhost:9000/a2a"
