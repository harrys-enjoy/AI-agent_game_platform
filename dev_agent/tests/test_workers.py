from graph.workers import README_CONTEXT_MAX_CHARS, _readme_context, general_qa_agent, review_agent


def test_review_agent_skips_llm_when_diff_missing():
    result = review_agent({"diff": ""})

    assert "review" in result["results"]
    assert "diff" in result["results"]["review"]


def test_readme_context_empty_when_no_readme():
    assert _readme_context({"diff": "x"}) == ""
    assert _readme_context({"diff": "x", "readme": ""}) == ""


def test_readme_context_includes_readme_text():
    context = _readme_context({"readme": "# pokerogue_test\n데모 프로젝트"})

    assert "# pokerogue_test" in context
    assert "데모 프로젝트" in context


def test_readme_context_truncates_long_readme():
    long_readme = "x" * (README_CONTEXT_MAX_CHARS + 500)

    context = _readme_context({"readme": long_readme})

    assert len(context) <= README_CONTEXT_MAX_CHARS + 200  # 안내 문구 여유분


def test_review_agent_includes_readme_in_prompt(monkeypatch):
    captured = {}

    def fake_chat_completion(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return "리뷰 결과"

    monkeypatch.setattr("graph.workers.chat_completion", fake_chat_completion)

    review_agent({"diff": "+x = 1", "readme": "# pokerogue_test\n데모 프로젝트"})

    assert "pokerogue_test" in captured["prompt"]
    assert "+x = 1" in captured["prompt"]


def test_review_agent_omits_readme_section_when_absent(monkeypatch):
    captured = {}

    def fake_chat_completion(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return "리뷰 결과"

    monkeypatch.setattr("graph.workers.chat_completion", fake_chat_completion)

    review_agent({"diff": "+x = 1", "readme": ""})

    assert "README" not in captured["prompt"]


def test_general_qa_agent_answers_using_already_fetched_context(monkeypatch):
    captured = {}

    def fake_chat_completion(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return "이 레포 이름은 owner/repo입니다."

    monkeypatch.setattr("graph.workers.chat_completion", fake_chat_completion)

    result = general_qa_agent({
        "request": "레포 이름이 뭐야?",
        "repo": "owner/repo",
        "readme": "# repo\n데모 프로젝트",
        "branches": ["main"],
        "prs": [],
    })

    assert result["results"]["general"] == "이 레포 이름은 owner/repo입니다."
    assert "owner/repo" in captured["prompt"]
    assert "레포 이름이 뭐야?" in captured["prompt"]
    assert "데모 프로젝트" in captured["prompt"]


def test_general_qa_agent_does_not_fetch_new_data(monkeypatch):
    """새 GitHub 호출 없이 state에 이미 있는 값만 쓴다 — 별도 검색/수집 없음을 보장."""
    calls = []
    monkeypatch.setattr("graph.workers.chat_completion", lambda messages, **kwargs: calls.append(1) or "답변")

    general_qa_agent({"request": "이 프로젝트가 뭐야?", "repo": "owner/repo"})

    assert len(calls) == 1
