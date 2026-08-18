"""GitHub Actions 테스트 워크플로를 직접 실행하고 완료까지 기다린 뒤 실패 로그를 수집한다.

fetch 노드가 '이미 끝난' 체크 결과를 수동적으로 읽는 것과 달리, 이 노드는 워크플로를
능동적으로 트리거한다. 쓰기 동작이므로 GITHUB_TOKEN(actions:write)이 반드시 필요하고,
유저가 명시적으로 실행을 요청했을 때만 supervisor가 이 노드를 계획에 넣는다.
"""

import os
import time

from github import Github

from graph.fetch import get_github_client

WORKFLOW_FILE = "tests.yml"
POLL_INTERVAL_SEC = 10
DEFAULT_TIMEOUT_SEC = 600

def _timeout_sec() -> int:
    return int(os.getenv("CI_TRIGGER_TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC))


def _resolve_ref(state: dict, repo) -> str:
    """실행할 브랜치를 정한다. PR 번호가 주어졌으면 그 PR의 브랜치, 아니면 레포 기본 브랜치."""
    pr_number = state.get("pr_number")
    if pr_number:
        for pr in state.get("prs", []):
            if pr.get("number") == pr_number and pr.get("branch"):
                return pr["branch"]
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
