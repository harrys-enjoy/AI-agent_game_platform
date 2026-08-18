from graph.supervisor import (
    _drop_diff_workers_when_diff_missing,
    _end_early_on_fatal_fetch_error,
    _gate_explicit_actions,
    compose_final_response,
)


def test_compose_final_response_orders_sections_and_adds_headers():
    results = {"ci": "빌드 실패: X", "review": "L12: 오타"}

    output = compose_final_response(results)

    assert output.index("## 코드 리뷰") < output.index("## CI 실패 요약")
    assert "L12: 오타" in output
    assert "빌드 실패: X" in output


def test_compose_final_response_only_includes_present_keys():
    results = {"branch": "브랜치 3개"}

    output = compose_final_response(results)

    assert "## 브랜치/PR 현황" in output
    assert "## 코드 리뷰" not in output
    assert "## CI 실패 요약" not in output


def test_compose_final_response_empty_results():
    assert compose_final_response({}) == "실행된 워커가 없습니다."


def test_compose_final_response_includes_deploy_section():
    results = {"deploy": "배포 완료: http://localhost:8000 (브랜치 beta)"}

    output = compose_final_response(results)

    assert "## 배포 결과" in output
    assert "http://localhost:8000" in output


def test_compose_final_response_includes_general_qa_section():
    results = {"general": "이 레포 이름은 owner/repo입니다."}

    output = compose_final_response(results)

    assert "## 답변" in output
    assert "owner/repo" in output


def test_compose_final_response_includes_fetch_error_section():
    results = {"fetch": "repository_not_exist"}

    output = compose_final_response(results)

    assert "## 오류" in output
    assert "repository_not_exist" in output


def test_end_early_on_fatal_fetch_error_clears_pending_when_repo_missing():
    pending = ["review_agent", "branch_agent"]
    state = {"results": {"fetch": "repository_not_exist"}}

    assert _end_early_on_fatal_fetch_error(pending, state) == []


def test_end_early_on_fatal_fetch_error_leaves_pending_untouched_otherwise():
    pending = ["review_agent", "branch_agent"]
    state = {"results": {}}

    assert _end_early_on_fatal_fetch_error(pending, state) == pending


def test_gate_explicit_actions_drops_ci_trigger_without_explicit_request():
    plan = ["fetch", "ci_trigger", "ci_agent"]

    result = _gate_explicit_actions(plan, "브랜치 현황 정리해줘")

    assert result == ["fetch", "ci_agent"]


def test_gate_explicit_actions_drops_deploy_trigger_without_explicit_request():
    plan = ["fetch", "review_agent", "deploy_trigger"]

    result = _gate_explicit_actions(plan, "이 PR 코드 리뷰해줘")

    assert result == ["fetch", "review_agent"]


def test_gate_explicit_actions_keeps_ci_trigger_when_explicitly_requested():
    plan = ["fetch", "ci_trigger", "ci_agent"]

    result = _gate_explicit_actions(plan, "테스트 돌려줘")

    assert result == plan


def test_gate_explicit_actions_keeps_deploy_trigger_when_explicitly_requested():
    plan = ["fetch", "deploy_trigger"]

    result = _gate_explicit_actions(plan, "이 브랜치 배포해줘")

    assert result == plan


def test_gate_explicit_actions_leaves_unrelated_plan_untouched():
    plan = ["fetch", "branch_agent"]

    result = _gate_explicit_actions(plan, "브랜치 현황 정리해줘")

    assert result == plan


def test_drop_diff_workers_removes_them_when_fetch_done_and_diff_empty():
    pending = ["review_agent", "endpoint_agent", "branch_agent"]
    state = {"diff": "", "branches": ["main"]}

    result = _drop_diff_workers_when_diff_missing(pending, state)

    assert result == ["endpoint_agent", "branch_agent"]


def test_drop_diff_workers_keeps_them_when_diff_present():
    pending = ["review_agent", "endpoint_agent"]
    state = {"diff": "--- a.py\n+x = 1", "branches": ["main"]}

    result = _drop_diff_workers_when_diff_missing(pending, state)

    assert result == pending


def test_drop_diff_workers_waits_until_fetch_has_run():
    pending = ["fetch", "review_agent"]
    state = {"diff": "", "branches": []}

    result = _drop_diff_workers_when_diff_missing(pending, state)

    assert result == pending
