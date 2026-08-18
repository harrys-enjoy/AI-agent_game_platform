"""API 키 없이 그래프 배선 전체를 검증하는 스모크 테스트.

LLM 호출만 가짜로 대체하고 나머지는 전부 진짜로 돌린다:
- 라우팅 계획: 고정값 (LLM 판단 대신)
- 워커 출력: 프롬프트 길이만 보고하는 더미 텍스트
- GitHub 호출: 진짜 (공개 레포, 익명 접근 시 60회/시간)

검증되는 것: supervisor 라우팅 -> fetch -> 워커 실행 -> results 병합 -> 최종 조합
검증 안 되는 것: LLM이 실제로 쓸만한 리뷰를 쓰는지 (키 받은 뒤 streamlit으로 확인)

사용법:
    python smoke_test.py                        # GitHub 없이 (가짜 fetch)
    python smoke_test.py --live-github          # 진짜 GitHub 호출
    python smoke_test.py --live-github --pr 1   # 특정 PR까지 수집
"""

import argparse
import json
import sys

import graph.supervisor as supervisor_mod
import graph.workers as workers_mod

DEFAULT_REPO = "rest8050/pokerogue_test"
PLAN = [
    "fetch",
    "review_agent",
    "endpoint_agent",
    "branch_agent",
    "ci_trigger",
    "ci_agent",
    "deploy_trigger",
]


def _fake_chat_completion(messages: list[dict], **kwargs) -> str:
    """system 메시지 유무로 supervisor(라우팅) 호출인지 workers(생성) 호출인지 구분한다."""
    if any(m["role"] == "system" for m in messages):
        return json.dumps({"plan": PLAN})
    prompt = messages[-1]["content"]
    return f"[가짜 LLM 응답] 프롬프트 {len(prompt)}자 수신"


def install_fake_llm() -> None:
    """supervisor와 workers가 공유하는 chat_completion을 가짜로 교체.

    노드는 호출 시점에 모듈 전역을 보므로 임포트 순서 무관.
    """
    supervisor_mod.chat_completion = _fake_chat_completion
    workers_mod.chat_completion = _fake_chat_completion


def install_fake_ci_trigger() -> None:
    """ci_trigger는 --live-github 여부와 무관하게 항상 가짜로 둔다.

    이 노드는 실제 GitHub Actions 워크플로를 실행시키는 쓰기 동작이다. 스모크 테스트는
    배선을 확인하는 용도이므로, 사용자가 요청하지도 않은 CI 실행에 Actions 사용량을
    소모해서는 안 된다.
    """
    import graph.build as build_mod
    import graph.ci_trigger as ci_mod

    def fake_ci_trigger_node(state: dict, gh_client=None) -> dict:
        return {
            "ci_logs": [{"name": "test-shard-1", "conclusion": "failure", "summary": "실패 스텝: vitest"}],
            "ci_status": "CI 실패 — failure (beta). https://example.invalid/runs/1 [가짜]",
        }

    ci_mod.ci_trigger_node = fake_ci_trigger_node
    build_mod.ci_trigger_node = fake_ci_trigger_node


def install_fake_deploy_trigger() -> None:
    """deploy_trigger는 --live-github 여부와 무관하게 항상 가짜로 둔다.

    이 노드는 실제로 이 PC의 Docker Desktop에 컨테이너를 띄우는 쓰기 동작이다.
    스모크 테스트는 배선을 확인하는 용도이므로, 사용자가 요청하지도 않은 배포로
    로컬 리소스를 소모해서는 안 된다.
    """
    import graph.build as build_mod
    import graph.deploy_trigger as deploy_mod

    def fake_deploy_trigger_node(state: dict, gh_client=None) -> dict:
        return {"results": {"deploy": "배포 완료: http://localhost:8000 (브랜치 beta) [가짜]"}}

    deploy_mod.deploy_trigger_node = fake_deploy_trigger_node
    build_mod.deploy_trigger_node = fake_deploy_trigger_node


def install_fake_github() -> None:
    """fetch_node/endpoint_agent가 네트워크를 타지 않도록 고정 데이터를 반환하게 만든다."""
    import graph.fetch as fetch_mod

    def fake_fetch_node(state: dict, gh_client=None) -> dict:
        return {
            "branches": ["main", "beta", "demo/bug-1"],
            "prs": [{"number": 1, "title": "데모 PR", "state": "open", "branch": "demo/bug-1"}],
            "diff": "--- src/battle.ts\n+const x = null;\n+x.foo();",
            "readme": "# pokerogue_test\n포켓몬류 배틀 로그라이크 데모 프로젝트입니다.",
            "ci_logs": [{"name": "test-suite", "conclusion": "failure", "summary": "2 tests failed"}],
        }

    def fake_endpoint_agent(state: dict, gh_client=None) -> dict:
        return {
            "results": {
                "endpoint": "| Method | Path | Function | 위치 |\n|---|---|---|---|\n"
                "| GET | /battle | get_battle | src/routes.py:12 | [가짜]"
            }
        }

    fetch_mod.fetch_node = fake_fetch_node
    fetch_mod.endpoint_agent = fake_endpoint_agent
    import graph.build as build_mod

    build_mod.fetch_node = fake_fetch_node
    build_mod.endpoint_agent = fake_endpoint_agent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--live-github", action="store_true", help="진짜 GitHub API를 호출한다")
    args = parser.parse_args()

    install_fake_llm()
    install_fake_ci_trigger()
    install_fake_deploy_trigger()
    if not args.live_github:
        install_fake_github()

    from graph.build import build_graph

    graph = build_graph()

    initial_state = {
        "request": "이 PR 리뷰하고 브랜치 현황도 정리해줘. CI 다시 실행하고 배포도 해줘",
        "repo": args.repo,
        "pr_number": args.pr,
        "diff": "",
        "readme": "",
        "branches": [],
        "prs": [],
        "ci_logs": [],
        "ci_status": "",
        "pending": [],
        "planned": False,
        "results": {},
        "next": "",
        "final_response": "",
    }

    print(f"[모드] LLM=가짜, GitHub={'진짜' if args.live_github else '가짜'}")
    print(f"[대상] {args.repo}" + (f" PR #{args.pr}" if args.pr else " (PR 미지정)"))
    print("-" * 60)

    visited = []
    final_state = None
    for step in graph.stream(initial_state, stream_mode="updates"):
        for node_name, node_output in step.items():
            visited.append(node_name)
            print(f"  실행: {node_name}")
            final_state = node_output

    print("-" * 60)
    print(f"[방문 순서] {' -> '.join(visited)}")

    expected = {"supervisor", *PLAN}
    missing = expected - set(visited)
    if missing:
        print(f"FAIL: 실행되지 않은 노드가 있습니다: {sorted(missing)}")
        return 1

    report = (final_state or {}).get("final_response", "")
    if not report:
        print("FAIL: final_response가 비어 있습니다.")
        return 1

    print("\n[최종 리포트]")
    print(report)

    for header in [
        "## 코드 리뷰",
        "## 엔드포인트 목록",
        "## 브랜치/PR 현황",
        "## CI 실패 요약",
        "## 배포 결과",
    ]:
        if header not in report:
            print(f"\nFAIL: 리포트에 '{header}' 섹션이 없습니다.")
            return 1

    print(f"\nPASS: {len(PLAN)}개 노드 전부 실행, 5개 섹션 전부 조합됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
