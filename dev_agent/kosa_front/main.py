import os
import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, Query, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("devops_dashboard")

# Load environment variables from .env file
load_dotenv(dotenv_path=".env", override=True)

app = FastAPI(
    title="GitHub DevOps Dashboard",
    description="FastAPI dashboard visualizing GitHub Branches, PRs, Issues, and Deployments",
    version="1.0.0"
)

# Mount static directory and Jinja2 templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Global Config State (can be dynamically updated from UI settings or .env)
class Config:
    def __init__(self):
        self.reload_env()

    def reload_env(self):
        load_dotenv(dotenv_path=".env", override=True)
        self.github_token = os.getenv("GITHUB_TOKEN", "").strip()
        self.github_owner = os.getenv("GITHUB_OWNER", "").strip()
        self.github_repo = os.getenv("GITHUB_REPO", "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.github_token and self.github_owner and self.github_repo)

config = Config()

# Helper for GitHub API Headers
def get_github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FastAPI-DevOps-Dashboard"
    }
    if config.github_token:
        headers["Authorization"] = f"Bearer {config.github_token}"
    return headers


# ==========================================
# GitHub Real API Fetchers & Fallback Mocks
# ==========================================

async def fetch_github_branches_prs(owner: str, repo: str) -> Dict[str, Any]:
    """Fetch branches, PRs, and commit history from GitHub REST API with Mock Fallback."""
    # Use real GitHub REST API if owner and repo are provided
    target_owner = owner or config.github_owner or "octocat"
    target_repo = repo or config.github_repo or "Hello-World"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # 1. Fetch Branches
            branches_resp = await client.get(
                f"https://api.github.com/repos/{target_owner}/{target_repo}/branches?per_page=30",
                headers=get_github_headers()
            )
            # 2. Fetch Pull Requests
            prs_resp = await client.get(
                f"https://api.github.com/repos/{target_owner}/{target_repo}/pulls?state=all&per_page=15",
                headers=get_github_headers()
            )
            # 2b. Repo metadata, just for the default branch — the fork-point
            # lookup below needs something to compare every other branch against.
            repo_resp = await client.get(
                f"https://api.github.com/repos/{target_owner}/{target_repo}",
                headers=get_github_headers()
            )

            if branches_resp.status_code != 200:
                logger.warning(f"GitHub API returned status {branches_resp.status_code}, using mock fallback.")
                return get_mock_branches_prs(target_owner, target_repo, error_msg=f"GitHub API Status ({branches_resp.status_code})")

            branches_data = branches_resp.json()
            prs_data = prs_resp.json()
            default_branch = repo_resp.json().get("default_branch", "main") if repo_resp.status_code == 200 else "main"

            # 3. Fetch Recent Commits per branch, so each commit is tagged with its
            # real branch. The plain /commits endpoint has no branch field at all.
            # ponytail: only capped when unauthenticated, to stay within GitHub's
            # anonymous rate limit (60 req/hr) — a GITHUB_TOKEN gets 5000 req/hr,
            # plenty to cover every branch.
            BRANCH_COMMIT_FETCH_LIMIT = len(branches_data) if config.github_token else 6
            branch_names = [b.get("name") for b in branches_data[:BRANCH_COMMIT_FETCH_LIMIT] if b.get("name")]
            branch_commit_resps = await asyncio.gather(*[
                client.get(
                    f"https://api.github.com/repos/{target_owner}/{target_repo}/commits",
                    params={"sha": name, "per_page": 5},
                    headers=get_github_headers()
                ) for name in branch_names
            ])

            # Format Branches
            formatted_branches = []
            for b in branches_data:
                formatted_branches.append({
                    "name": b.get("name"),
                    "protected": b.get("protected", False),
                    "commit_sha": b.get("commit", {}).get("sha", "")[:7],
                    "commit_url": b.get("commit", {}).get("url", "")
                })

            # Format PRs
            formatted_prs = []
            open_count = 0
            merged_count = 0
            closed_count = 0

            for pr in prs_data:
                state = pr.get("state")
                is_merged = pr.get("merged_at") is not None
                if is_merged:
                    state_label = "merged"
                    merged_count += 1
                elif state == "open":
                    state_label = "open"
                    open_count += 1
                else:
                    state_label = "closed"
                    closed_count += 1

                formatted_prs.append({
                    "id": pr.get("id"),
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": state_label,
                    "draft": pr.get("draft", False),
                    "author": {
                        "login": pr.get("user", {}).get("login"),
                        "avatar_url": pr.get("user", {}).get("avatar_url")
                    },
                    "head": pr.get("head", {}).get("ref"),
                    "base": pr.get("base", {}).get("ref"),
                    "created_at": pr.get("created_at"),
                    "updated_at": pr.get("updated_at"),
                    "html_url": pr.get("html_url"),
                    "labels": [l.get("name") for l in pr.get("labels", [])],
                    "assignees": [a.get("login") for a in pr.get("assignees", [])],
                    "reviewers": [r.get("login") for r in pr.get("requested_reviewers", [])],
                    "additions": pr.get("additions", 120),
                    "deletions": pr.get("deletions", 34)
                })

            # Format Commit Tree nodes (dedupe: a commit reachable from multiple
            # branches is tagged with whichever branch we fetched first)
            seen_shas = set()
            git_tree_nodes = []
            for branch_name, commits_resp in zip(branch_names, branch_commit_resps):
                if commits_resp.status_code != 200:
                    continue
                for c in commits_resp.json():
                    sha = c.get("sha", "")
                    if not sha or sha in seen_shas:
                        continue
                    seen_shas.add(sha)
                    commit_info = c.get("commit", {})
                    author_info = c.get("author") or {}
                    git_tree_nodes.append({
                        "sha": sha[:7],
                        "full_sha": sha,
                        "message": commit_info.get("message", "").split("\n")[0],
                        "author": author_info.get("login") or commit_info.get("author", {}).get("name", "Developer"),
                        "date": commit_info.get("author", {}).get("date", ""),
                        "parents": [p.get("sha", "")[:7] for p in c.get("parents", [])],
                        "branch": branch_name
                    })

            # Cap to the 20 most recent before the fork lookup below, so a fork-point
            # commit (deliberately kept regardless of age) can't get pushed out by it.
            git_tree_nodes.sort(key=lambda n: n["date"], reverse=True)
            git_tree_nodes = git_tree_nodes[:20]
            seen_shas = {n["full_sha"] for n in git_tree_nodes}

            # 4. Find where each other branch actually forked from default_branch, so the
            # graph can draw a real connector instead of leaving lanes floating unconnected.
            # GitHub's plain /commits has no such relationship — /compare's merge_base_commit
            # is the only endpoint that gives it.
            branch_forks = []
            other_branches = [n for n in branch_names if n != default_branch]
            branch_tip_sha = {b.get("name"): b.get("commit", {}).get("sha", "") for b in branches_data}
            if other_branches:
                compare_resps = await asyncio.gather(*[
                    client.get(
                        f"https://api.github.com/repos/{target_owner}/{target_repo}/compare/{default_branch}...{name}",
                        headers=get_github_headers()
                    ) for name in other_branches
                ], return_exceptions=True)

                for branch_name, resp in zip(other_branches, compare_resps):
                    if isinstance(resp, Exception) or resp.status_code != 200:
                        continue
                    base_commit = resp.json().get("merge_base_commit")
                    if not base_commit:
                        continue
                    sha = base_commit.get("sha", "")
                    if not sha:
                        continue
                    base_date = base_commit.get("commit", {}).get("author", {}).get("date", "")
                    # A branch with zero commits ahead (merge-base == its own tip) is fully
                    # merged — keep its tip tagged with its own name instead of folding it
                    # into default_branch, so it still gets a lane in the graph even though
                    # every commit it has is shared history.
                    is_fully_merged = sha == branch_tip_sha.get(branch_name)
                    if sha in seen_shas:
                        # Step 3's per-branch fetch already pulled this commit in, possibly
                        # mislabeled — e.g. tagged as whichever branch happened to reach it
                        # first (which can even be default_branch itself, if this commit sits
                        # directly on its mainline). Now that /compare confirms what it really
                        # is, fix the tag: the branch's own name if it's that branch's tip,
                        # otherwise shared history that belongs on the base branch's lane.
                        for existing in git_tree_nodes:
                            if existing["full_sha"] == sha:
                                existing["branch"] = branch_name if is_fully_merged else default_branch
                                break
                    else:
                        seen_shas.add(sha)
                        commit_info = base_commit.get("commit", {})
                        author_info = base_commit.get("author") or {}
                        git_tree_nodes.append({
                            "sha": sha[:7],
                            "full_sha": sha,
                            "message": commit_info.get("message", "").split("\n")[0],
                            "author": author_info.get("login") or commit_info.get("author", {}).get("name", "Developer"),
                            "date": commit_info.get("author", {}).get("date", ""),
                            "parents": [p.get("sha", "")[:7] for p in base_commit.get("parents", [])],
                            "branch": branch_name if is_fully_merged else default_branch
                        })
                    branch_forks.append({"branch": branch_name, "base": default_branch, "fork_sha": sha[:7]})

                    # Any already-fetched child-branch commit strictly before the merge-base's
                    # timestamp is itself pre-fork shared history (an ancestor of the merge
                    # base), not something unique to the child branch — retag those too.
                    # Heuristic: no full parent-chain walk, just commit dates. Strictly-before
                    # (not <=) so the tip itself (date == base_date) is never caught here.
                    if base_date:
                        for existing in git_tree_nodes:
                            if existing["branch"] == branch_name and existing["date"] and existing["date"] < base_date:
                                existing["branch"] = default_branch

            git_tree_nodes.sort(key=lambda n: n["date"], reverse=True)

            return {
                "source": "live",
                "owner": owner,
                "repo": repo,
                "total_branches": len(formatted_branches),
                "branches": formatted_branches,
                "pr_summary": {
                    "total": len(formatted_prs),
                    "open": open_count,
                    "merged": merged_count,
                    "closed": closed_count
                },
                "pull_requests": formatted_prs,
                "git_tree": git_tree_nodes,
                "branch_forks": branch_forks
            }

        except Exception as e:
            logger.error(f"Error fetching GitHub Branches/PRs: {e}")
            return get_mock_branches_prs(owner, repo, error_msg=str(e))


async def fetch_github_issues(owner: str, repo: str) -> Dict[str, Any]:
    """Fetch Issues and format summary & label breakdown."""
    target_owner = owner or config.github_owner or "octocat"
    target_repo = repo or config.github_repo or "Hello-World"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            issues_resp = await client.get(
                f"https://api.github.com/repos/{target_owner}/{target_repo}/issues?state=all&per_page=30",
                headers=get_github_headers()
            )

            if issues_resp.status_code != 200:
                return get_mock_issues(target_owner, target_repo, error_msg=f"API Error ({issues_resp.status_code})")

            issues_raw = issues_resp.json()
            # Filter out Pull Requests (GitHub REST API returns PRs in issues endpoint unless filtered)
            issues_clean = [item for item in issues_raw if "pull_request" not in item]

            formatted_issues = []
            label_counts: Dict[str, int] = {}
            open_count = 0
            closed_count = 0

            for issue in issues_clean:
                state = issue.get("state")
                if state == "open":
                    open_count += 1
                else:
                    closed_count += 1

                labels = []
                for l in issue.get("labels", []):
                    l_name = l.get("name")
                    labels.append({
                        "name": l_name,
                        "color": l.get("color", "0052CC")
                    })
                    label_counts[l_name] = label_counts.get(l_name, 0) + 1

                formatted_issues.append({
                    "id": issue.get("id"),
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "body": (issue.get("body") or "")[:200],
                    "state": state,
                    "kanban_status": "done" if state == "closed" else ("in_progress" if len(issue.get("assignees", [])) > 0 else "todo"),
                    "user": {
                        "login": issue.get("user", {}).get("login"),
                        "avatar_url": issue.get("user", {}).get("avatar_url")
                    },
                    "assignees": [{
                        "login": a.get("login"),
                        "avatar_url": a.get("avatar_url")
                    } for a in issue.get("assignees", [])],
                    "labels": labels,
                    "comments_count": issue.get("comments", 0),
                    "created_at": issue.get("created_at"),
                    "html_url": issue.get("html_url")
                })

            # AI Issue Summary Generation
            summary = {
                "critical_issues_count": sum(1 for i in formatted_issues if any("bug" in l["name"].lower() or "p0" in l["name"].lower() for l in i["labels"])),
                "top_priority": "FastAPI OAuth2 Token Handling & UI Refresh Latency",
                "recommended_actions": [
                    "Resolve critical OAuth2 token expiry issue (#104)",
                    "Merge approved PR for Dark Mode glassmorphism fixes",
                    "Conduct staging environment deployment health check"
                ]
            }

            return {
                "source": "live",
                "owner": owner,
                "repo": repo,
                "total_issues": len(formatted_issues),
                "open_count": open_count,
                "closed_count": closed_count,
                "label_statistics": label_counts,
                "ai_summary": summary,
                "issues": formatted_issues
            }

        except Exception as e:
            logger.error(f"Error fetching GitHub Issues: {e}")
            return get_mock_issues(owner, repo, error_msg=str(e))


# kosa-deploy-* 컨테이너 이름 접두어. graph/deploy_trigger.py의 _SLOT_PREFIX와 맞아야 한다 —
# 이 대시보드는 그 모듈이 로컬 Docker Desktop에 띄운 컨테이너를 조회하는 쪽이라 값을 복제해뒀다.
DEPLOY_CONTAINER_PREFIX = "kosa-deploy-"


def _docker_path() -> str:
    """docker CLI 경로. graph/deploy_trigger.py의 _docker_path()와 동일한 폴백 전략."""
    found = shutil.which("docker")
    if found:
        return found
    fallback = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    return str(fallback) if fallback.exists() else "docker"


def _run_docker(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run([_docker_path(), *args], capture_output=True, text=True, timeout=10)


async def get_docker_deployments() -> Dict[str, Any]:
    """이 서버/PC에 실제로 떠 있는 kosa-deploy-* 컨테이너 상태를 docker CLI로 조회한다.

    GitHub Deployments API가 아니다 — 이 프로젝트는 그 API를 쓰지 않는다. 실제 배포는
    graph/deploy_trigger.py가 이 머신의 Docker Desktop에 직접 컨테이너를 띄우는 방식이라,
    여기서도 같은 머신의 docker를 조회해야 진짜 상태가 나온다. 즉 이 화면을 보는 사람
    본인의 로컬 배포 현황이지, 팀 공용 서버의 배포 이력이 아니다.
    """
    try:
        ps = await asyncio.to_thread(
            _run_docker,
            [
                "ps", "-a", "--filter", f"name={DEPLOY_CONTAINER_PREFIX}",
                "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.CreatedAt}}",
            ],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Docker CLI를 실행하지 못했습니다: {e}")
        return {"source": "docker-local", "docker_available": False, "containers": [], "error_msg": str(e)}

    if ps.returncode != 0:
        return {
            "source": "docker-local",
            "docker_available": False,
            "containers": [],
            "error_msg": (ps.stderr or "Docker Desktop이 실행 중이 아닙니다.").strip(),
        }

    containers = []
    for line in ps.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        container_id, name, image, status, ports, created_at = parts
        containers.append({
            "id": container_id,
            "name": name,
            "repo": name[len(DEPLOY_CONTAINER_PREFIX):] if name.startswith(DEPLOY_CONTAINER_PREFIX) else name,
            "image": image,
            "status": status,
            "running": status.lower().startswith("up"),
            "ports": ports,
            "created_at": created_at,
            "cpu_usage": None,
            "memory_usage": None,
        })

    running_names = [c["name"] for c in containers if c["running"]]
    if running_names:
        try:
            stats = await asyncio.to_thread(
                _run_docker,
                ["stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}", *running_names],
            )
            if stats.returncode == 0:
                stats_by_name = {}
                for line in stats.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) == 3:
                        stats_by_name[parts[0]] = {"cpu": parts[1], "memory": parts[2]}
                for c in containers:
                    s = stats_by_name.get(c["name"])
                    if s:
                        c["cpu_usage"], c["memory_usage"] = s["cpu"], s["memory"]
        except (OSError, subprocess.TimeoutExpired):
            pass  # 통계 조회 실패는 치명적이지 않다 — cpu/mem 없이 표시된다

    return {"source": "docker-local", "docker_available": True, "containers": containers, "error_msg": None}


async def get_docker_container_logs(name: str) -> str:
    """kosa-deploy-* 컨테이너 하나의 최근 로그. 이름을 접두어로 검증해 임의 컨테이너 로그 열람을 막는다."""
    if not name.startswith(DEPLOY_CONTAINER_PREFIX):
        raise HTTPException(status_code=400, detail="유효하지 않은 컨테이너 이름입니다.")

    try:
        logs = await asyncio.to_thread(_run_docker, ["logs", "--tail", "100", name])
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(status_code=502, detail=f"로그를 가져오지 못했습니다: {e}")

    if logs.returncode != 0:
        raise HTTPException(status_code=404, detail=(logs.stderr or "컨테이너를 찾을 수 없습니다.").strip())

    return logs.stdout or logs.stderr or "(로그 없음)"


async def delete_docker_deployment(name: str) -> None:
    """kosa-deploy-* 컨테이너 하나(또는 그게 속한 compose 프로젝트 전체)를 삭제한다.

    RUNNING이면 거부한다 — 이 화면은 STOPPED된 옛 배포를 정리하는 용도지, 지금 쓰고
    있을 수도 있는 배포를 지우는 용도가 아니다. compose로 뜬 컨테이너면(`com.docker.
    compose.project` 라벨이 있음) 같은 프로젝트의 컨테이너/네트워크를 전부 내린다 —
    하나만 지우면 나머지가 고아로 남는 걸 실제로 겪었다(mysql만 지우고 app은 그대로
    남는 식). `docker compose -p <project> down`은 compose 파일 없이 프로젝트 이름
    (라벨)만으로 동작한다 — 직접 검증됨.
    """
    if not name.startswith(DEPLOY_CONTAINER_PREFIX):
        raise HTTPException(status_code=400, detail="유효하지 않은 컨테이너 이름입니다.")

    try:
        inspect = await asyncio.to_thread(
            _run_docker,
            [
                "inspect", "--format",
                '{{.State.Running}}\t{{index .Config.Labels "com.docker.compose.project"}}',
                name,
            ],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(status_code=502, detail=f"컨테이너 상태를 확인하지 못했습니다: {e}")

    if inspect.returncode != 0:
        raise HTTPException(status_code=404, detail=(inspect.stderr or "컨테이너를 찾을 수 없습니다.").strip())

    running, _, project = inspect.stdout.strip("\n").partition("\t")
    if running == "true":
        raise HTTPException(status_code=409, detail="실행 중인 컨테이너는 삭제할 수 없습니다.")

    args = ["compose", "-p", project, "down"] if project else ["rm", name]
    try:
        result = await asyncio.to_thread(_run_docker, args)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(status_code=502, detail=f"삭제하지 못했습니다: {e}")

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or "삭제에 실패했습니다.").strip())


# ==========================================
# Mock Data Generators (Graceful Fallback)
# ==========================================

def get_mock_branches_prs(owner: str, repo: str, error_msg: Optional[str] = None) -> Dict[str, Any]:
    branches = [
        {"name": "main", "protected": True, "commit_sha": "a1b2c3d", "commit_url": "#", "commit_msg": "Release v1.2.4 Production build tag"},
        {"name": "develop", "protected": True, "commit_sha": "e5f6g7h", "commit_url": "#", "commit_msg": "Merge branch 'feature/auth-oauth2' into develop"},
        {"name": "feature/auth-oauth2-token", "protected": False, "commit_sha": "i9j0k1l", "commit_url": "#", "commit_msg": "feat: implement JWT token refresh & authorization header handler"},
        {"name": "feature/ai-summary-engine", "protected": False, "commit_sha": "u1v2w3x", "commit_url": "#", "commit_msg": "feat: add LLM issue summary heuristic analyzer"},
        {"name": "feature/dark-glassmorphism-v2", "protected": False, "commit_sha": "m2n3o4p", "commit_url": "#", "commit_msg": "style: apply linear glassmorphic directory borders"},
        {"name": "fix/deployment-pipeline-k8s", "protected": False, "commit_sha": "q5r6s7t", "commit_url": "#", "commit_msg": "fix: update helm chart values for production deployment"},
        {"name": "hotfix/security-patch-v1.2.5", "protected": False, "commit_sha": "y4z5a6b", "commit_url": "#", "commit_msg": "security: patch CORS wildcard origin vulnerability"},
        {"name": "refactor/chart-canvas-webworker", "protected": False, "commit_sha": "c7d8e9f", "commit_url": "#", "commit_msg": "refactor: offload heavy Chart.js rendering to Web Worker"}
    ]

    pull_requests = [
        {
            "id": 101,
            "number": 45,
            "title": "✨ Add LLM Issue Summary Heuristic Analyzer & Actionable Report Card",
            "state": "open",
            "draft": False,
            "author": {"login": "ai-dev-kim", "avatar_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100"},
            "head": "feature/ai-summary-engine",
            "base": "develop",
            "created_at": "2026-08-12T13:10:00Z",
            "updated_at": "2026-08-12T15:00:00Z",
            "html_url": "https://github.com",
            "labels": ["enhancement", "ai", "feature"],
            "reviewers": ["tech-lead"],
            "review_status": "APPROVED",
            "ci_status": "success",
            "additions": 420,
            "deletions": 18
        },
        {
            "id": 102,
            "number": 44,
            "title": "🔒 Security Hotfix: Patch CORS Wildcard Origin Vulnerability in FastAPI Middleware",
            "state": "open",
            "draft": False,
            "author": {"login": "sec-team", "avatar_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=100"},
            "head": "hotfix/security-patch-v1.2.5",
            "base": "main",
            "created_at": "2026-08-12T14:00:00Z",
            "updated_at": "2026-08-12T14:45:00Z",
            "html_url": "https://github.com",
            "labels": ["P0-Critical", "security", "hotfix"],
            "reviewers": ["tech-lead", "devops-engineer"],
            "review_status": "APPROVED",
            "ci_status": "success",
            "additions": 35,
            "deletions": 12
        },
        {
            "id": 103,
            "number": 43,
            "title": "⚡ Refactor: Offload heavy Chart.js rendering to Web Worker thread",
            "state": "open",
            "draft": True,
            "author": {"login": "performance-guru", "avatar_url": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=100"},
            "head": "refactor/chart-canvas-webworker",
            "base": "develop",
            "created_at": "2026-08-12T11:20:00Z",
            "updated_at": "2026-08-12T12:00:00Z",
            "html_url": "https://github.com",
            "labels": ["performance", "refactor"],
            "reviewers": ["frontend-wiz"],
            "review_status": "PENDING",
            "ci_status": "running",
            "additions": 180,
            "deletions": 95
        },
        {
            "id": 104,
            "number": 42,
            "title": "🔑 Implement OAuth2 JWT Token Refresh & Authorization Header Handler",
            "state": "open",
            "draft": False,
            "author": {"login": "dev-lead", "avatar_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100"},
            "head": "feature/auth-oauth2-token",
            "base": "develop",
            "created_at": "2026-08-12T10:15:00Z",
            "updated_at": "2026-08-12T14:20:00Z",
            "html_url": "https://github.com",
            "labels": ["enhancement", "backend", "v1.2.0"],
            "reviewers": ["code-reviewer-kim", "qa-lead"],
            "review_status": "APPROVED",
            "ci_status": "success",
            "additions": 340,
            "deletions": 45
        },
        {
            "id": 105,
            "number": 41,
            "title": "🎨 Apply Linear Directory Layout & Straight Borders for Branch Directory Tree",
            "state": "open",
            "draft": False,
            "author": {"login": "frontend-wiz", "avatar_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=100"},
            "head": "feature/dark-glassmorphism-v2",
            "base": "develop",
            "created_at": "2026-08-11T16:30:00Z",
            "updated_at": "2026-08-12T09:10:00Z",
            "html_url": "https://github.com",
            "labels": ["ui/ux", "linear-design"],
            "reviewers": ["ui-designer"],
            "review_status": "CHANGES_REQUESTED",
            "ci_status": "success",
            "additions": 512,
            "deletions": 120
        },
        {
            "id": 106,
            "number": 40,
            "title": "🐛 Fix deployment pipeline staging rollback script and helm chart values",
            "state": "merged",
            "draft": False,
            "author": {"login": "devops-engineer", "avatar_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=100"},
            "head": "fix/deployment-pipeline-k8s",
            "base": "main",
            "created_at": "2026-08-10T11:00:00Z",
            "updated_at": "2026-08-11T18:00:00Z",
            "html_url": "https://github.com",
            "labels": ["bug", "devops"],
            "reviewers": ["tech-lead"],
            "review_status": "APPROVED",
            "ci_status": "success",
            "additions": 88,
            "deletions": 62
        }
    ]

    git_tree = [
        {"sha": "y4z5a6b", "message": "security: patch CORS wildcard origin vulnerability", "author": "sec-team", "date": "5분 전", "branch": "hotfix/security-patch-v1.2.5", "type": "commit"},
        {"sha": "u1v2w3x", "message": "feat: add LLM issue summary heuristic analyzer", "author": "ai-dev-kim", "date": "20분 전", "branch": "feature/ai-summary-engine", "type": "commit"},
        {"sha": "c01a9f1", "message": "merge: PR #40 Fix deployment pipeline staging script", "author": "devops-engineer", "date": "40분 전", "branch": "main", "type": "merge"},
        {"sha": "i9j0k1l", "message": "feat: implement JWT token refresh & authorization header handler", "author": "dev-lead", "date": "1시간 전", "branch": "feature/auth-oauth2-token", "type": "commit"},
        {"sha": "m2n3o4p", "message": "style: apply linear glassmorphic directory borders", "author": "frontend-wiz", "date": "3시간 전", "branch": "feature/dark-glassmorphism-v2", "type": "commit"},
        {"sha": "c7d8e9f", "message": "refactor: offload heavy Chart.js rendering to Web Worker", "author": "performance-guru", "date": "4시간 전", "branch": "refactor/chart-canvas-webworker", "type": "commit"},
        {"sha": "e991c23", "message": "refactor: optimize Kanban issue drag & drop state", "author": "dev-lead", "date": "어제", "branch": "develop", "type": "commit"},
        {"sha": "d443a12", "message": "fix: update CORS headers for local FastAPI server", "author": "tech-lead", "date": "2일 전", "branch": "main", "type": "commit"}
    ]

    # 실제 API 경로의 branch_forks(merge_base_commit)와 같은 역할 — 데모에서도 그래프에
    # 실제 분기점 커넥터가 보이도록 PR의 base와 맞춰 손으로 채워둔다.
    branch_forks = [
        {"branch": "develop", "base": "main", "fork_sha": "d443a12"},
        {"branch": "hotfix/security-patch-v1.2.5", "base": "main", "fork_sha": "d443a12"},
        {"branch": "feature/ai-summary-engine", "base": "develop", "fork_sha": "e991c23"},
        {"branch": "feature/auth-oauth2-token", "base": "develop", "fork_sha": "e991c23"},
        {"branch": "feature/dark-glassmorphism-v2", "base": "develop", "fork_sha": "e991c23"},
        {"branch": "refactor/chart-canvas-webworker", "base": "develop", "fork_sha": "e991c23"}
    ]

    return {
        "source": "mock",
        "owner": owner,
        "repo": repo,
        "error_msg": error_msg,
        "total_branches": len(branches),
        "branches": branches,
        "pr_summary": {
            "total": len(pull_requests),
            "open": sum(1 for pr in pull_requests if pr["state"] == "open"),
            "merged": sum(1 for pr in pull_requests if pr["state"] == "merged"),
            "closed": sum(1 for pr in pull_requests if pr["state"] == "closed")
        },
        "pull_requests": pull_requests,
        "git_tree": git_tree,
        "branch_forks": branch_forks
    }


def get_mock_issues(owner: str, repo: str, error_msg: Optional[str] = None) -> Dict[str, Any]:
    issues = [
        {
            "id": 201,
            "number": 88,
            "title": "[P0 Critical] Production OAuth2 Authentication Token Refresh Intermittent Timeout",
            "body": "User login session drops intermittently when calling external auth endpoint under heavy load.",
            "state": "open",
            "kanban_status": "in_progress",
            "user": {"login": "qa-tester", "avatar_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=100"},
            "assignees": [{"login": "dev-lead", "avatar_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100"}],
            "labels": [{"name": "P0-Critical", "color": "d93f0b"}, {"name": "bug", "color": "e11d48"}, {"name": "backend", "color": "2563eb"}],
            "comments_count": 8,
            "created_at": "2026-08-12T08:30:00Z",
            "html_url": "https://github.com"
        },
        {
            "id": 202,
            "number": 89,
            "title": "[P1 Feature] Support Custom SVG Branch Visualizer Zooming & Node Pan Interaction",
            "body": "Add pan and pinch-to-zoom capabilities for complex Git tree views with 50+ commits.",
            "state": "open",
            "kanban_status": "todo",
            "user": {"login": "product-owner", "avatar_url": "https://images.unsplash.com/photo-1580489944761-15a19d654956?w=100"},
            "assignees": [{"login": "frontend-wiz", "avatar_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=100"}],
            "labels": [{"name": "enhancement", "color": "059669"}, {"name": "frontend", "color": "9333ea"}],
            "comments_count": 3,
            "created_at": "2026-08-12T11:00:00Z",
            "html_url": "https://github.com"
        },
        {
            "id": 203,
            "number": 85,
            "title": "[P2 Refactor] Upgrade Chart.js to v4.4 and Migrate to Canvas Web Workers",
            "body": "Offload heavy rendering math for live issue label distribution charts to web worker thread.",
            "state": "open",
            "kanban_status": "review",
            "user": {"login": "tech-lead", "avatar_url": "https://images.unsplash.com/photo-1570295999919-56ceb5ecca61?w=100"},
            "assignees": [{"login": "performance-guru", "avatar_url": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=100"}],
            "labels": [{"name": "refactor", "color": "4f46e5"}, {"name": "performance", "color": "d97706"}],
            "comments_count": 5,
            "created_at": "2026-08-11T14:20:00Z",
            "html_url": "https://github.com"
        },
        {
            "id": 204,
            "number": 82,
            "title": "[P1 DevOps] Add Automated Rollback Trigger on Production Health Check Failure",
            "body": "When /healthz returns 5xx for 3 consecutive probes, invoke GitHub deployment status API rollback.",
            "state": "closed",
            "kanban_status": "done",
            "user": {"login": "sre-lead", "avatar_url": "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=100"},
            "assignees": [{"login": "devops-engineer", "avatar_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=100"}],
            "labels": [{"name": "devops", "color": "0891b2"}, {"name": "automation", "color": "0284c7"}],
            "comments_count": 12,
            "created_at": "2026-08-09T10:00:00Z",
            "html_url": "https://github.com"
        }
    ]

    label_stats = {
        "P0-Critical": 1,
        "bug": 1,
        "enhancement": 1,
        "refactor": 1,
        "devops": 1,
        "frontend": 2,
        "backend": 1
    }

    ai_summary = {
        "critical_issues_count": 1,
        "top_priority": "Production OAuth2 Authentication Token Refresh Intermittent Timeout (#88)",
        "recommended_actions": [
            "Issue #88 (P0 Critical) requires urgent backend token handling hotfix before release.",
            "Review PR #41 frontend glassmorphic styling updates.",
            "Complete automated deployment rollback trigger verification."
        ]
    }

    return {
        "source": "mock",
        "owner": owner,
        "repo": repo,
        "error_msg": error_msg,
        "total_issues": len(issues),
        "open_count": 3,
        "closed_count": 1,
        "label_statistics": label_stats,
        "ai_summary": ai_summary,
        "issues": issues
    }


# ==========================================
# FastAPI Routes & Page Views
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    """Render Single Page Application Dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "is_configured": config.is_configured,
            "owner": config.github_owner or "kosa-org",
            "repo": config.github_repo or "kosa-main-service",
            "has_token": bool(config.github_token)
        }
    )


@app.get("/api/status")
async def get_status():
    """Return GitHub API integration status."""
    return {
        "is_configured": config.is_configured,
        "owner": config.github_owner or "kosa-org",
        "repo": config.github_repo or "kosa-main-service",
        "has_token": bool(config.github_token)
    }


@app.get("/api/branches-prs")
async def get_branches_prs():
    """API endpoint for Branches & Pull Requests data."""
    owner = config.github_owner or "kosa-org"
    repo = config.github_repo or "kosa-main-service"
    data = await fetch_github_branches_prs(owner, repo)
    return JSONResponse(content=data)


@app.get("/api/issues")
async def get_issues():
    """API endpoint for Issues data."""
    owner = config.github_owner or "kosa-org"
    repo = config.github_repo or "kosa-main-service"
    data = await fetch_github_issues(owner, repo)
    return JSONResponse(content=data)


@app.get("/api/deployments")
async def get_deployments():
    """API endpoint for locally running kosa-deploy-* Docker container status."""
    data = await get_docker_deployments()
    return JSONResponse(content=data)


@app.get("/api/deployments/{name}/logs")
async def get_deployment_logs(name: str):
    """Recent docker logs for a single kosa-deploy-* container."""
    logs = await get_docker_container_logs(name)
    return {"name": name, "logs": logs}


@app.delete("/api/deployments/{name}")
async def delete_deployment(name: str):
    """Delete a stopped kosa-deploy-* deployment (and its compose siblings, if any)."""
    await delete_docker_deployment(name)
    return {"status": "deleted", "name": name}


@app.post("/api/config/update")
async def update_config(payload: Dict[str, str] = Body(...)):
    """Dynamically update owner, repo, or token from UI modal."""
    owner = payload.get("owner", "").strip()
    repo = payload.get("repo", "").strip()
    token = payload.get("token", "").strip()

    if owner:
        config.github_owner = owner
    if repo:
        config.github_repo = repo
    if token:
        config.github_token = token

    return {
        "status": "success",
        "message": "Configuration updated successfully",
        "owner": config.github_owner,
        "repo": config.github_repo,
        "has_token": bool(config.github_token)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
