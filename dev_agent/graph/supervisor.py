import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from graph.fetch import FETCH_ERROR_REPO_NOT_EXIST
from graph.llm_client import chat_completion

SUPERVISOR_TIMEOUT_SEC = 45

SYSTEM_PROMPT = """당신은 개발 보조 멀티에이전트의 슈퍼바이저입니다. 유저 요청을 읽고, \
필요한 워커를 순서대로 나열한 계획(plan)을 세우세요.

사용 가능한 노드:
- fetch: GitHub에서 PR diff, 브랜치 목록, PR 목록, CI 체크 결과를 가져옵니다. \
diff나 브랜치 목록이 아직 없다면 반드시 계획의 맨 앞에 포함하세요.
- review_agent: PR diff를 읽고 파일:라인별 리뷰 코멘트를 작성합니다. \
유저가 코드 리뷰를 요청할 때 포함하세요.
- endpoint_agent: 레포 전체를 스캔해서 현재 정의된 API 엔드포인트 목록을 마크다운 표로 만듭니다 \
(Flask/FastAPI 라우트만 인식, PR diff와 무관하게 레포 전체 기준). \
유저가 API/엔드포인트 목록을 요청할 때 포함하세요.
- branch_agent: 브랜치와 PR 목록으로 현황 문서를 작성합니다. \
유저가 브랜치 현황이나 프로젝트 상태를 요청할 때 포함하세요.
- ci_agent: PR의 CI 체크 실패 로그를 요약합니다. \
유저가 빌드/테스트 실패 원인을 요청할 때 포함하세요.
- ci_trigger: GitHub Actions에서 테스트 워크플로를 새로 실행하고 완료까지 기다립니다. \
유저가 "테스트 돌려줘", "CI 다시 실행해줘"처럼 실행 자체를 명시적으로 요청할 때만 포함하세요. \
이미 나온 결과를 묻기만 하는 요청에는 넣지 마세요 — 그건 fetch가 가져온 것으로 충분합니다. \
포함할 경우 반드시 ci_agent보다 앞에 두세요.
- deploy_trigger: 이 PC의 Docker Desktop에 대상 브랜치/PR을 직접 빌드해서 띄웁니다. \
유저가 "배포해줘", "띄워줘", "실행해서 보여줘"처럼 배포 자체를 명시적으로 요청할 때만 포함하세요. \
리뷰나 현황 질문에는 넣지 마세요.
- general_qa: 위 워커 어디에도 해당하지 않는 일반 질문(레포 이름, 프로젝트가 뭔지 등)에 \
이미 수집된 정보(README, 브랜치, PR 목록)로 답합니다. 다른 워커로 처리할 수 없는 요청이면 \
반드시 이것을 포함하세요.

요청에 필요 없는 워커는 계획에 넣지 마세요. 다른 워커 중 어느 것도 요청에 맞지 않으면 \
general_qa 하나만 반환하세요 — 빈 목록을 반환하지 마세요.

반드시 아래 형식의 JSON 객체 하나만 답하세요. 설명, 코드블록, 다른 텍스트를 덧붙이지 마세요.
{"plan": ["fetch", "review_agent"]}
"""


class RoutingPlan(BaseModel):
    plan: list[
        Literal[
            "fetch",
            "review_agent",
            "endpoint_agent",
            "branch_agent",
            "ci_agent",
            "general_qa",
            "ci_trigger",
            "deploy_trigger",
        ]
    ] = Field(
        description="유저 요청을 처리하기 위해 순서대로 실행할 노드 목록"
    )
    # reasoning 필드를 두지 않는다. 아무도 읽지 않는데 자유 서술이 붙으면 JSON 파싱만
    # 복잡해진다 — plan 하나만 있는 최소 스키마를 프롬프트로 강제한다.


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def _parse_routing_plan(content: str) -> RoutingPlan:
    """모델 응답에서 JSON 객체를 뽑아 RoutingPlan으로 파싱한다.

    가이드 디코딩(구조화 출력 강제) 없이 프롬프트만으로 JSON을 요청하므로, 모델이
    ```json 코드블록으로 감싸거나 앞뒤에 설명을 붙이는 경우가 있다 — 정규식으로
    가장 바깥 {...} 블록만 골라낸다.
    """
    match = _JSON_OBJECT_RE.search(content)
    json_text = match.group(0) if match else content
    try:
        return RoutingPlan.model_validate(json.loads(json_text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"라우팅 응답을 JSON으로 파싱하지 못함: {content!r}") from exc


def _order_ci_before_summary(plan: list[str]) -> list[str]:
    """ci_trigger는 반드시 ci_agent보다 먼저 와야 한다.

    순서가 뒤집히면 ci_agent가 실행 전의 낡은 상태를 요약해버린다. 프롬프트로만
    지시하지 않고 코드로 보장한다.
    """
    if "ci_trigger" not in plan or "ci_agent" not in plan:
        return plan
    if plan.index("ci_trigger") < plan.index("ci_agent"):
        return plan
    reordered = [node for node in plan if node != "ci_trigger"]
    reordered.insert(reordered.index("ci_agent"), "ci_trigger")
    return reordered


# ponytail: substring heuristic, not real intent classification — upgrade to a
# proper NLU check if false negatives (missed explicit requests) become a problem
_CI_TRIGGER_KEYWORDS = ("돌려", "다시 실행", "재실행")
_DEPLOY_TRIGGER_KEYWORDS = ("배포", "띄워", "실행해서 보여")


def _gate_explicit_actions(plan: list[str], request: str) -> list[str]:
    """ci_trigger/deploy_trigger는 실제 쓰기 동작이라, 약한 모델의 프롬프트 준수만으로는
    "명시적 요청 시에만 포함"을 보장할 수 없다. 유저 요청 문구에 해당 키워드가 없으면
    plan에 들어있어도 코드로 제거한다.
    """
    filtered = list(plan)
    if "ci_trigger" in filtered and not any(kw in request for kw in _CI_TRIGGER_KEYWORDS):
        filtered = [n for n in filtered if n != "ci_trigger"]
    if "deploy_trigger" in filtered and not any(kw in request for kw in _DEPLOY_TRIGGER_KEYWORDS):
        filtered = [n for n in filtered if n != "deploy_trigger"]
    return filtered


def _drop_diff_workers_when_diff_missing(pending: list[str], state: dict) -> list[str]:
    """fetch가 이미 끝났는데 diff가 비어 있으면 diff에 의존하는 워커를 코드로 제거한다.

    LLM을 다시 불러 재계획하는 대신, fetch 결과만 보고 판단하면 되는 경우라 코드로
    싸게 처리한다. review_agent는 워커 내부에도 빈 diff 가드가 있지만, 여기서 미리 빼면
    쓸모없는 그래프 노드 왕복 자체가 안 생긴다. endpoint_agent는 레포 전체를 스캔하는
    독립적인 작업이라 diff 유무와 무관하다 — 여기서 빼지 않는다.
    """
    if "fetch" in pending:
        return pending  # fetch가 아직 안 끝났으면 diff 판단을 미룬다
    if state.get("diff"):
        return pending
    return [n for n in pending if n != "review_agent"]


def _end_early_on_fatal_fetch_error(pending: list[str], state: dict) -> list[str]:
    """fetch가 레포 자체를 못 찾았으면 나머지 워커는 전부 의미가 없다 — 즉시 종료.

    diff/branches/prs가 다 비어있는 채로 나머지 워커를 계속 돌리면 각자 "데이터 없음"
    응답만 반복하며 시간을 버린다. 코드로 바로 끊는다.
    """
    if state.get("results", {}).get("fetch") == FETCH_ERROR_REPO_NOT_EXIST:
        return []
    return pending


def _build_status_summary(state: dict) -> str:
    has_diff = bool(state.get("diff"))
    has_branches = bool(state.get("branches"))
    history_context = state.get("history_context") or ""
    prefix = f"{history_context}\n\n" if history_context else ""
    return (
        f"{prefix}"
        f"현재 상태:\n"
        f"- diff 이미 수집됨: {has_diff}\n"
        f"- 브랜치/PR 목록 이미 수집됨: {has_branches}\n"
        f"유저 요청: {state['request']}"
    )


def supervisor_node(state: dict) -> dict:
    if not state.get("planned"):
        content = chat_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_status_summary(state)},
            ],
            max_tokens=4096,
            timeout=SUPERVISOR_TIMEOUT_SEC,
        )
        decision = _parse_routing_plan(content)
        pending = _order_ci_before_summary(list(decision.plan))
        pending = _gate_explicit_actions(pending, state["request"])
        if not state.get("branches") and (not pending or pending[0] != "fetch"):
            pending = ["fetch"] + pending
    else:
        pending = list(state.get("pending", []))

    pending = _drop_diff_workers_when_diff_missing(pending, state)
    pending = _end_early_on_fatal_fetch_error(pending, state)

    if not pending:
        return {
            "next": "END",
            "pending": [],
            "planned": True,
            "final_response": compose_final_response(state.get("results", {})),
        }

    next_node, *rest = pending
    return {"next": next_node, "pending": rest, "planned": True}


def compose_final_response(results: dict) -> str:
    """워커 출력을 하나의 마크다운 응답으로 결정적으로(비-LLM) 조합한다."""
    if not results:
        return "실행된 워커가 없습니다."

    titles = {
        "fetch": "## 오류",
        "general": "## 답변",
        "review": "## 코드 리뷰",
        "endpoint": "## 엔드포인트 목록",
        "branch": "## 브랜치/PR 현황",
        "ci": "## CI 실패 요약",
        "deploy": "## 배포 결과",
    }
    sections = []
    for key in ["fetch", "general", "review", "endpoint", "branch", "ci", "deploy"]:
        if key in results:
            sections.append(f"{titles[key]}\n\n{results[key]}")
    return "\n\n".join(sections)
