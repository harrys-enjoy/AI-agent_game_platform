import pytest

from graph.llm_client import ELICE_API_KEY
from graph.supervisor import supervisor_node

requires_elice_api = pytest.mark.skipif(
    not ELICE_API_KEY,
    reason="ELICE_API_KEY가 설정되지 않음 — supervisor 라우팅 테스트는 실제 Elice API 호출이 필요",
)


def _base_state(**overrides):
    state = {
        "request": "",
        "repo": "rest8050/pokerogue_test",
        "pr_number": None,
        "diff": "",
        "readme": "",
        "branches": [],
        "prs": [],
        "ci_logs": [],
        "pending": [],
        "planned": False,
        "results": {},
        "next": "",
        "final_response": "",
    }
    state.update(overrides)
    return state


@requires_elice_api
def test_supervisor_plans_fetch_first_when_diff_missing():
    state = _base_state(request="이 PR 리뷰해줘")

    result = supervisor_node(state)

    assert result["next"] == "fetch"
    assert result["planned"] is True


@requires_elice_api
def test_supervisor_plans_review_agent_when_diff_already_present():
    state = _base_state(
        request="이 PR 코드 리뷰해줘",
        diff="--- src/battle.ts\n+added a bug",
        branches=["main"],
    )

    result = supervisor_node(state)

    assert result["next"] == "review_agent"


@requires_elice_api
def test_supervisor_plans_branch_agent_for_status_request_when_branches_present():
    state = _base_state(
        request="브랜치 현황 정리해줘",
        branches=["main", "beta", "feature-x"],
    )

    result = supervisor_node(state)

    assert result["next"] == "branch_agent"


@requires_elice_api
def test_supervisor_ends_when_plan_exhausted():
    state = _base_state(
        request="이 PR 코드 리뷰해줘",
        diff="--- src/battle.ts\n+added a bug",
        branches=["main"],
        pending=[],
        planned=True,
        results={"review": "L1: 문제 없음"},
    )

    result = supervisor_node(state)

    assert result["next"] == "END"
    assert "final_response" in result
    assert "코드 리뷰" in result["final_response"]
