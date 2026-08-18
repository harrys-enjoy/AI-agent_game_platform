from graph.history import format_recent, new_history, record_turn


def test_record_turn_appends_entry():
    history = new_history()

    entry = record_turn(
        history,
        request="이 PR 리뷰해줘",
        repo="owner/repo",
        pr_number=1,
        executed_nodes=["supervisor", "fetch", "review_agent"],
        final_response="## 코드 리뷰\n\n문제 없음",
    )

    assert list(history) == [entry]
    assert entry["executed_nodes"] == ["fetch", "review_agent"]
    assert entry["error"] is None


def test_record_turn_drops_oldest_beyond_maxlen():
    history = new_history()

    for i in range(9):
        record_turn(
            history,
            request=f"요청 {i}",
            repo="owner/repo",
            pr_number=None,
            executed_nodes=[],
            final_response="",
        )

    assert len(history) == 8
    assert history[0]["request"] == "요청 1"
    assert history[-1]["request"] == "요청 8"


def test_format_recent_empty_history_returns_empty_string():
    assert format_recent(new_history()) == ""


def test_format_recent_includes_request_and_status():
    history = new_history()
    record_turn(
        history,
        request="브랜치 현황 정리해줘",
        repo="owner/repo",
        pr_number=None,
        executed_nodes=["supervisor", "fetch", "branch_agent"],
        final_response="## 브랜치/PR 현황",
    )
    record_turn(
        history,
        request="배포해줘",
        repo="owner/repo",
        pr_number=2,
        executed_nodes=["supervisor", "deploy_trigger"],
        final_response="",
        error="Docker Desktop이 실행 중이 아닙니다.",
    )

    text = format_recent(history)

    assert "브랜치 현황 정리해줘" in text
    assert "fetch, branch_agent" in text
    assert "배포해줘" in text
    assert "오류: Docker Desktop이 실행 중이 아닙니다." in text
