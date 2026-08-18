import os
import re

from github import Auth, Github, GithubException

FETCH_ERROR_REPO_NOT_EXIST = "repository_not_exist"

# Flask 2.x/FastAPI 스타일(@app.get/@router.post/...)과 Flask 클래식(@app.route(methods=[...]))만
# 인식한다. Express/Spring/Next.js 같은 다른 스택은 지원 범위 밖.
_ROUTE_RE = re.compile(
    r'@\w+\.(get|post|put|patch|delete|route)\(\s*["\']([^"\']+)["\']'
    r'(?:[^)]*?methods\s*=\s*\[([^\]]*)\])?'
)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")

# ponytail: Contents API는 파일마다 API 호출 1회가 든다. 대형 레포에서 rate limit을
# 태우지 않도록 상한을 둔다 — 넘으면 git clone 기반 스캔으로 바꿔야 한다.
MAX_PYTHON_FILES_SCANNED = 300


def get_github_client() -> Github:
    """PyGithub 클라이언트를 만든다. GITHUB_TOKEN이 있으면 인증, 없으면 익명 접속.

    PyGithub은 5xx/rate-limit(403)를 기본 GithubRetry로 이미 재시도하고, 404는 재시도
    안 한다 — 별도 재시도 로직을 여기 추가할 필요가 없다.
    """
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return Github(auth=Auth.Token(token))
    return Github()


def fetch_node(state: dict, gh_client: Github | None = None) -> dict:
    """PR diff, 브랜치 목록, PR 목록, CI 체크 결과를 한 번에 수집한다.

    레포 자체가 없으면(404) 예외를 그대로 던지지 않는다 — 워크스페이스 설정 오타 같은
    확정적 오류라 재시도해도 똑같이 실패하고, 잡지 않으면 그래프 전체가 죽어서
    이미 완료된 다른 워커 결과까지 날아간다.
    """
    gh = gh_client or get_github_client()
    try:
        repo = gh.get_repo(state["repo"])
    except GithubException as exc:
        if exc.status == 404:
            return {
                "results": {"fetch": FETCH_ERROR_REPO_NOT_EXIST},
                "diff": "",
                "readme": "",
                "branches": [],
                "prs": [],
                "ci_logs": [],
            }
        raise

    branches = [b.name for b in repo.get_branches()]
    prs = [
        {"number": pr.number, "title": pr.title, "state": pr.state, "branch": pr.head.ref}
        for pr in repo.get_pulls(state="all")
    ]
    readme = _fetch_readme(repo)

    diff = ""
    ci_logs: list[dict] = []
    pr_number = state.get("pr_number")
    if pr_number:
        pr = repo.get_pull(pr_number)
        diff = _fetch_diff_text(pr)
        ci_logs = _fetch_ci_logs(pr)

    return {
        "branches": branches,
        "prs": prs,
        "diff": diff,
        "readme": readme,
        "ci_logs": ci_logs,
    }


def _fetch_readme(repo) -> str:
    """레포 README를 가져온다. 없으면 빈 문자열 — 리뷰 컨텍스트용 부가 정보라
    없다고 fetch 전체를 실패시키지 않는다."""
    try:
        readme = repo.get_readme()
    except GithubException:
        return ""
    return readme.decoded_content.decode("utf-8", errors="ignore")


def _fetch_diff_text(pr) -> str:
    parts = []
    for f in pr.get_files():
        parts.append(f"--- {f.filename}\n{f.patch or '(binary or no textual diff)'}")
    return "\n\n".join(parts)


def _fetch_ci_logs(pr) -> list[dict]:
    commits = list(pr.get_commits())
    if not commits:
        return []
    commit = commits[-1]
    logs = []
    for run in commit.get_check_runs():
        if run.conclusion not in (None, "success"):
            logs.append(
                {
                    "name": run.name,
                    "conclusion": run.conclusion,
                    "summary": (run.output.summary if run.output else "") or "",
                }
            )
    return logs


def _list_python_files(repo) -> list[str]:
    """레포의 .py 파일 경로를 재귀적으로 나열한다."""
    paths: list[str] = []
    stack = [""]
    while stack:
        contents = repo.get_contents(stack.pop())
        if not isinstance(contents, list):
            contents = [contents]
        for item in contents:
            if item.type == "dir":
                stack.append(item.path)
            elif item.path.endswith(".py"):
                paths.append(item.path)
            if len(paths) >= MAX_PYTHON_FILES_SCANNED:
                return paths
    return paths


def _scan_routes(repo, file_path: str) -> list[dict]:
    """한 파일에서 라우트 데코레이터를 찾아 (메서드, 경로, 함수명, 위치)를 뽑는다.

    정규식 매칭이라 데코레이터가 여러 줄에 걸치거나 경로를 f-string/변수로 조립하면
    놓친다 — 흔한 한 줄짜리 데코레이터만 다룬다.
    """
    text = repo.get_contents(file_path).decoded_content.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    routes = []
    for i, line in enumerate(lines):
        m = _ROUTE_RE.search(line)
        if not m:
            continue
        verb, url_path, methods_raw = m.groups()
        if verb == "route":
            methods = [tok.strip(" \"'") for tok in methods_raw.split(",")] if methods_raw else ["GET"]
        else:
            methods = [verb.upper()]

        func_name = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            stripped = lines[j].strip()
            dm = _DEF_RE.match(lines[j])
            if dm:
                func_name = dm.group(1)
                break
            if stripped == "" or stripped.startswith("@"):
                continue
            break

        routes.append({"file": file_path, "line": i + 1, "methods": methods, "path": url_path, "func": func_name})
    return routes


def _format_routes_markdown(routes: list[dict]) -> str:
    if not routes:
        return "감지된 엔드포인트가 없습니다."
    header = "| Method | Path | Function | 위치 |\n|---|---|---|---|"
    rows = [
        f"| {', '.join(r['methods'])} | {r['path']} | {r['func'] or '-'} | {r['file']}:{r['line']} |"
        for r in routes
    ]
    return "\n".join([header, *rows])


def endpoint_agent(state: dict, gh_client: Github | None = None) -> dict:
    """레포 전체를 스캔해서 Flask/FastAPI 라우트 정의를 마크다운 표로 만든다.

    LLM을 쓰지 않는다 — 결정론적 정규식 스캔. fetch_node가 먼저 실행돼 레포 존재를
    확인한 뒤에만 supervisor가 이 노드를 호출하므로, 여기서 404를 따로 처리하지 않는다.
    """
    gh = gh_client or get_github_client()
    repo = gh.get_repo(state["repo"])

    routes = []
    for file_path in _list_python_files(repo):
        routes.extend(_scan_routes(repo, file_path))

    return {"results": {"endpoint": _format_routes_markdown(routes)}}
