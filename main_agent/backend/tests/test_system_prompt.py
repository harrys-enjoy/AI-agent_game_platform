from app.main_agent_prompt import MAIN_AGENT_SYSTEM_PROMPT, get_agent_system_prompt
from app.main import build_agent_request


def test_main_agent_system_prompt_contains_core_operating_rules():
    assert "사용자의 동의 없이 Task를 자동 생성하지 않는다" in MAIN_AGENT_SYSTEM_PROMPT
    assert "Game Q&A" in MAIN_AGENT_SYSTEM_PROMPT
    assert "존재하지 않는 정보를 추측하지 않는다" in MAIN_AGENT_SYSTEM_PROMPT


def test_agent_prompt_is_selected_by_agent_name():
    assert "게임" in get_agent_system_prompt("game-qna-agent")
    assert "영상" in get_agent_system_prompt("video-agent")
    assert "코드" in get_agent_system_prompt("dev-agent")
    assert "업무" in get_agent_system_prompt("workmate-agent")
    assert get_agent_system_prompt("unknown-agent") == MAIN_AGENT_SYSTEM_PROMPT


def test_task_agent_request_also_carries_the_selected_agent_prompt():
    request = build_agent_request("dev-agent", "PR 변경사항을 검토해줘")
    assert request["message"] == "PR 변경사항을 검토해줘"
    assert "코드" in request["system_prompt"]
