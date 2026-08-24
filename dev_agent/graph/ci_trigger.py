"""GitHub Actions 테스트 워크플로를 직접 실행하고 완료까지 기다린 뒤 실패 로그를 수집한다.

fetch 노드가 '이미 끝난' 체크 결과를 수동적으로 읽는 것과 달리, 이 노드는 워크플로를
능동적으로 트리거한다. 쓰기 동작이므로 GITHUB_TOKEN(actions:write)이 반드시 필요하고,
유저가 명시적으로 실행을 요청했을 때만 supervisor가 이 노드를 계획에 넣는다.
"""

import os
import re
import time

from github import Github

from graph.fetch import get_github_client

WORKFLOW_FILE = "tests.yml"
POLL_INTERVAL_SEC = 10
DEFAULT_TIMEOUT_SEC = 600
# Python의 \w는 유니코드 인식이라 한글도 "단어 문자"로 쳐서 "feat/x를"처럼 조사가
# 브랜치명에 바로 붙는(공백 없는) 가장 흔한 한국어 표현을 못 잡는다. 그래서 경계
# 문자 클래스를 ASCII로 제한한다 — "." 도 경계에 포함해 "main.py" 같은 파일명
# 안의 오탐도 막는다(원래 계획엔 없었지만 같은 문제라 같이 닫는다).
# "/"는 경계에서 뺐다 — GitHub URL(".../tree/feat-bench")처럼 브랜치명 바로 앞에
# "/"가 오는 게 흔한데, "/"를 경계로 치면 그 앞의 "/" 때문에 매치가 거부돼서
# 항상 기본 브랜치로 폴백됐다(실제로 겪음). "/"는 "_"/"."/"-"와 달리 토큰을
# 하나로 묶는 문자가 아니라 진짜 구분자라 경계로 볼 필요가 애초에 없었다 —
# "feat"과 "feat/x"가 둘 다 있을 때 더 구체적인 쪽을 우선하는 건 아래 longest-first
# 정렬이 이미 처리한다.
_BOUNDARY = r"[A-Za-z0-9_.-]"

def _timeout_sec() -> int:
    return int(os.getenv("CI_TRIGGER_TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC))


def _find_mentioned_branch(request: str, branches: list[str]) -> str | None:
    """요청 텍스트에 실제 브랜치 이름이 단어 경계로 등장하면 그 이름을 돌려준다.

    긴 이름부터 검사해서 "feat"과 "feat/x"가 둘 다 존재할 때 더 구체적인 쪽을
    우선한다. 단순 substring 검사면 "main"이 "main_agent" 안에서 오탐된다 — 이
    모노레포 자체에 그런 디렉터리가 있어 실제로 위험한 케이스다. 앞뒤가
    ASCII 단어 문자(영숫자/밑줄)나 ".", "-"가 아닐 때만 진짜 매치로 인정한다
    (branch 안에 포함된 "/"는 re.escape로 그대로 리터럴 매치되므로 영향 없음 —
    "/"를 경계에서 뺀 이유는 위 _BOUNDARY 정의 옆 주석 참고). \\w를 그대로 쓰면 유니코드 인식이라 한글 조사가 브랜치명에 바로
    붙는 표현("feat/x를 배포해줘")을 못 잡으므로 _BOUNDARY로 ASCII만 경계로 친다.
    """
    for branch in sorted(branches, key=len, reverse=True):
        pattern = rf"(?<!{_BOUNDARY}){re.escape(branch)}(?!{_BOUNDARY})"
        if re.search(pattern, request):
            return branch
    return None


def _resolve_ref(state: dict, repo) -> str:
    """실행할 브랜치를 정한다. PR 번호가 주어졌으면 그 PR의 브랜치, 아니면 요청 텍스트에
    실제 브랜치 이름이 언급됐으면 그 브랜치, 그것도 아니면 레포 기본 브랜치."""
    pr_number = state.get("pr_number")
    if pr_number:
        for pr in state.get("prs", []):
            if pr.get("number") == pr_number and pr.get("branch"):
                return pr["branch"]
    mentioned = _find_mentioned_branch(state.get("request") or "", state.get("branches") or [])
    if mentioned:
        return mentioned
    return repo.default_branch


def _latest_run_id(workflow, ref: str):
    """해당 브랜치에서 workflow_dispatch로 실행된 가장 최근 런의 id. 없으면 None."""
    for run in workflow.get_runs(branch=ref, event="workflow_dispatch"):
        return run.id
    return None


def _collect_failed_jobs(run) -> list[dict]:
    """실패한 잡만 fetch 노드의 ci_logs와 같은 형태로 뽑는다."""
    logs = []
    for job in run.jobs():
        if job.conclusion in (None, "success", "skipped"):
            continue
        failed_steps = [s.name for s in (job.steps or []) if s.conclusion == "failure"]
        logs.append(
            {
                "name": job.name,
                "conclusion": job.conclusion,
                "summary": f"실패 스텝: {', '.join(failed_steps)}" if failed_steps else "",
            }
        )
    return logs


def ci_trigger_node(state: dict, gh_client: Github | None = None) -> dict:
    if not os.getenv("GITHUB_TOKEN"):
        return {
            "ci_logs": [],
            "ci_status": (
                "GITHUB_TOKEN이 없어 워크플로를 실행할 수 없습니다. "
                "workflow_dispatch는 actions:write 권한이 필요합니다."
            ),
        }

    gh = gh_client or get_github_client()
    repo = gh.get_repo(state["repo"])
    ref = _resolve_ref(state, repo)

    try:
        workflow = repo.get_workflow(WORKFLOW_FILE)
    except Exception as exc:
        return {"ci_logs": [], "ci_status": f"{WORKFLOW_FILE}을 찾을 수 없습니다: {exc}"}

    before_id = _latest_run_id(workflow, ref)

    if not workflow.create_dispatch(ref):
        return {"ci_logs": [], "ci_status": f"{ref} 브랜치에서 워크플로 실행 요청이 거부되었습니다."}

    run = _await_new_run(workflow, ref, before_id)
    if run is None:
        return {
            "ci_logs": [],
            "ci_status": f"{ref} 브랜치에서 실행을 요청했으나 새 런이 나타나지 않았습니다.",
        }

    run = _await_completion(run)
    url = run.html_url

    if run.status != "completed":
        return {
            "ci_logs": [],
            "ci_status": f"실행 중 ({run.status}) — 제한 시간 안에 끝나지 않았습니다. {url}",
        }

    if run.conclusion == "success":
        return {"ci_logs": [], "ci_status": f"CI 통과 ({ref}). {url}"}

    return {
        "ci_logs": _collect_failed_jobs(run),
        "ci_status": f"CI 실패 — {run.conclusion} ({ref}). {url}",
    }


def _await_new_run(workflow, ref: str, before_id):
    """dispatch 직후 새 런이 등록될 때까지 짧게 폴링한다. id 비교라 시계 오차에 영향받지 않는다."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SEC)
        current_id = _latest_run_id(workflow, ref)
        if current_id is not None and current_id != before_id:
            return workflow.get_runs(branch=ref, event="workflow_dispatch")[0]
    return None


def _await_completion(run):
    """런이 완료될 때까지 폴링한다. 제한 시간을 넘기면 마지막 상태 그대로 돌려준다."""
    deadline = time.monotonic() + _timeout_sec()
    while time.monotonic() < deadline:
        if run.status == "completed":
            return run
        time.sleep(POLL_INTERVAL_SEC)
        run.update()
    return run
