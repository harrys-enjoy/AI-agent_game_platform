import json
import os
import re

from github import Auth, Github, GithubException

from graph.llm_client import chat_completion

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

# 정규식이 못 잡는 언어(Go/Node/Java/...)를 위한 LLM 폴백 — 파일 경로만 먼저 보여주고
# LLM이 후보를 고르게 한 뒤(선택) 그 내용만 스캔한다(추출), 못 찾으면 나머지 경로로 재시도.
LLM_FILE_CONTENT_MAX_CHARS = 4000
LLM_FILES_PER_ROUND = 8
# ponytail: 라운드마다 LLM 호출 2회(선택+추출). 라운드 상한 없이 돌면 큰 레포에서 비용이
# 무한정 늘 수 있어 상한을 둔다 — 그래도 못 찾으면 정규식만큼 못 찾는 레포라고 본다.
LLM_FILE_SELECTION_MAX_ROUNDS = 3

_ENDPOINT_SYSTEM_PROMPT = (
    "너는 소스 코드에서 HTTP 엔드포인트를 찾아내는 도구다. 주어진 파일들에서 라우트 정의를 "
    "모두 찾아 JSON 배열로만 답하라. 설명이나 코드블록 표시 없이 순수 JSON만 출력한다. "
    '각 항목은 {"methods": ["GET"], "path": "/users", "func": "함수명", "file": "경로", "line": 12} '
    "형식이다. 라우트를 못 찾으면 빈 배열 []을 출력한다."
)


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


def _list_files(repo, matches, max_files: int) -> list[str]:
    """matches(path)가 참인 파일 경로를 재귀적으로 나열한다(최대 max_files개)."""
    paths: list[str] = []
    stack = [""]
    while stack:
        contents = repo.get_contents(stack.pop())
        if not isinstance(contents, list):
            contents = [contents]
        for item in contents:
            if item.type == "dir":
                stack.append(item.path)
            elif matches(item.path):
                paths.append(item.path)
            if len(paths) >= max_files:
                return paths
    return paths


def _list_python_files(repo) -> list[str]:
    """레포의 .py 파일 경로를 재귀적으로 나열한다."""
    return _list_files(repo, lambda p: p.endswith(".py"), MAX_PYTHON_FILES_SCANNED)


def _strip_json_fence(text: str) -> str:
    """LLM이 ```json ... ``` 코드블록으로 감싸 보내는 경우를 벗겨낸다."""
    return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _llm_pick_candidate_paths(all_paths: list[str], tried: set[str]) -> list[str]:
    """전체 파일 경로 목록(내용 없이 경로만)에서 라우트가 있을 법한 파일을 LLM이 고른다."""
    remaining = [p for p in all_paths if p not in tried]
    if not remaining:
        return []

    prompt = (
        "다음은 한 레포지토리의 파일 경로 목록이다. HTTP 라우트/엔드포인트 정의가 있을 "
        f"가능성이 가장 높은 파일을 최대 {LLM_FILES_PER_ROUND}개 골라 파일 경로 문자열의 "
        "JSON 배열로만 답하라. 설명이나 코드블록 표시 없이 순수 JSON 배열만 출력한다. "
        "후보가 없으면 빈 배열 []을 출력한다.\n\n" + "\n".join(remaining)
    )
    content = chat_completion([{"role": "user", "content": prompt}])

    try:
        picked = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError:
        return []
    if not isinstance(picked, list):
        return []

    remaining_set = set(remaining)
    return [p for p in picked if isinstance(p, str) and p in remaining_set][:LLM_FILES_PER_ROUND]


def _parse_llm_routes(content: str) -> list[dict]:
    try:
        raw = json.loads(_strip_json_fence(content))
        return [
            {"file": r["file"], "line": r.get("line") or 0, "methods": list(r["methods"]), "path": r["path"], "func": r.get("func") or ""}
            for r in raw
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def _llm_scan_routes(repo) -> list[dict]:
    """정규식 스캔이 0건일 때만 쓰는 폴백.

    ReAct 스타일 루프: 레포 파일 경로 전체를 LLM에 주고 라우트가 있을 법한 파일을
    고르게 한 뒤(선택) 그 파일 내용에서 라우트를 뽑고(추출), 못 찾으면 이미 시도한
    파일을 뺀 나머지로 다시 선택→추출을 반복한다.
    """
    all_paths = _list_files(repo, lambda p: True, MAX_PYTHON_FILES_SCANNED)
    tried: set[str] = set()

    for _ in range(LLM_FILE_SELECTION_MAX_ROUNDS):
        picked = _llm_pick_candidate_paths(all_paths, tried)
        if not picked:
            break
        tried.update(picked)

        files_block = "\n\n".join(
            f"### {path}\n{repo.get_contents(path).decoded_content.decode('utf-8', errors='ignore')[:LLM_FILE_CONTENT_MAX_CHARS]}"
            for path in picked
        )
        content = chat_completion([
            {"role": "system", "content": _ENDPOINT_SYSTEM_PROMPT},
            {"role": "user", "content": files_block},
        ])
        routes = _parse_llm_routes(content)
        if routes:
            return routes

    return []


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
    ordered = sorted(routes, key=lambda r: (r["file"], r["path"]))
    rows = [
        f"| {', '.join(r['methods'])} | {r['path']} | {r['func'] or '-'} | {r['file']}:{r['line']} |"
        for r in ordered
    ]
    return "\n".join([header, *rows])


def endpoint_agent(state: dict, gh_client: Github | None = None) -> dict:
    """레포 전체를 스캔해서 라우트 정의를 마크다운 표로 만든다.

    1차는 결정론적 정규식 스캔(Flask/FastAPI). 여기서 하나도 못 찾으면 그때만 LLM
    폴백으로 다른 언어/프레임워크(Go/Node/Java 등)를 시도한다 — 매 요청마다 LLM을
    쓰면 비용이 크므로, 정규식이 이미 찾았으면 LLM은 아예 호출하지 않는다.
    fetch_node가 먼저 실행돼 레포 존재를 확인한 뒤에만 supervisor가 이 노드를
    호출하므로, 여기서 404를 따로 처리하지 않는다.
    """
    gh = gh_client or get_github_client()
    repo = gh.get_repo(state["repo"])

    routes = []
    for file_path in _list_python_files(repo):
        routes.extend(_scan_routes(repo, file_path))

    if not routes:
        routes = _llm_scan_routes(repo)

    return {"results": {"endpoint": _format_routes_markdown(routes)}}
