def build_agent_card(internal_url: str) -> dict:
    base_url = f"{internal_url}/a2a"
    return {
        "name": "video-agent",
        "description": "게임 마케팅 영상 초안 생성 Agent",
        "url": base_url,
        "skills": [{"id": "video_draft", "name": "영상 초안"}],
        "capabilities": {"streaming": False},
        "supportedInterfaces": [
            {
                "url": base_url,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ],
        "securitySchemes": {},
    }
