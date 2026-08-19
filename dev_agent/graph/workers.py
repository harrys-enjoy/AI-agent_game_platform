from graph.llm_client import chat_completion

README_CONTEXT_MAX_CHARS = 3000


def _readme_context(state: dict) -> str:
    """리뷰 프롬프트 앞에 붙일 README 요약. 없으면 빈 문자열(프롬프트에 안 붙음)."""
    readme = (state.get("readme") or "")[:README_CONTEXT_MAX_CHARS]
    if not readme:
        return ""
    return f"다음은 이 레포의 README입니다. 프로젝트 맥락 참고용입니다.\n\n{readme}\n\n"


def review_agent(state: dict) -> dict:
    if not state.get("diff"):
        return {"results": {"review": "리뷰할 PR diff가 없습니다."}}

    prompt = (
        f"{_readme_context(state)}"
        "다음은 GitHub PR의 diff입니다. 파일:라인 단위로 문제가 될 만한 부분을 짚어 "
        "코드 리뷰 코멘트를 작성하세요. 마크다운 리스트로 답하세요.\n\n"
        f"{state['diff']}"
    )
    content = chat_completion([{"role": "user", "content": prompt}])
    return {"results": {"review": content}}


def branch_agent(state: dict) -> dict:
    prompt = (
        "다음은 레포의 브랜치 목록과 PR 목록입니다. 현재 개발 진행 상황을 요약하는 "
        "마크다운 문서를 작성하세요.\n\n"
        f"브랜치: {state.get('branches', [])}\n"
        f"PR: {state.get('prs', [])}"
    )
    content = chat_completion([{"role": "user", "content": prompt}])
    return {"results": {"branch": content}}


def general_qa_agent(state: dict) -> dict:
    """다른 워커 어디에도 해당하지 않는 일반 질문에, fetch가 이미 모아둔 정보로 답한다.

    새 데이터 수집 없이 state에 이미 있는 repo/README/브랜치/PR만 프롬프트에 그대로
    넣는다 — 이 정보는 매 요청마다 fetch가 새로 가져오므로 별도 저장소나 검색이 필요 없다.
    """
    prompt = (
        f"레포: {state.get('repo')}\n"
        f"{_readme_context(state)}"
        f"브랜치: {state.get('branches', [])}\n"
        f"PR: {state.get('prs', [])}\n\n"
        f"위 정보로 다음 질문에 답하세요. 정보가 부족하면 부족하다고 답하세요.\n"
        f"질문: {state['request']}"
    )
    content = chat_completion([{"role": "user", "content": prompt}])
    return {"results": {"general": content}}


def ci_agent(state: dict) -> dict:
    ci_logs = state.get("ci_logs", [])
    ci_status = state.get("ci_status", "")

    if not ci_logs:
        return {"results": {"ci": ci_status or "실패한 CI 체크가 없습니다."}}

    status_line = f"실행 상태: {ci_status}\n\n" if ci_status else ""
    prompt = (
        "다음은 PR의 CI 체크 실패 로그입니다. 실패 원인을 요약하세요.\n\n"
        f"{status_line}{ci_logs}"
    )
    content = chat_completion([{"role": "user", "content": prompt}])
    return {"results": {"ci": content}}
