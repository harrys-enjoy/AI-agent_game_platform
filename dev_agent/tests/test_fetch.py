from dataclasses import dataclass, field

from github import GithubException

from graph.fetch import FETCH_ERROR_REPO_NOT_EXIST, endpoint_agent, fetch_node


@dataclass
class FakeBranch:
    name: str


@dataclass
class FakeFile:
    filename: str
    patch: str | None


@dataclass
class FakeOutput:
    summary: str | None


@dataclass
class FakeCheckRun:
    name: str
    conclusion: str | None
    output: FakeOutput | None


@dataclass
class FakeCommit:
    check_runs: list

    def get_check_runs(self):
        return self.check_runs


@dataclass
class FakeHead:
    ref: str


@dataclass
class FakePR:
    number: int
    title: str
    state: str
    head: FakeHead
    files: list
    commits: list

    def get_files(self):
        return self.files

    def get_commits(self):
        return self.commits


@dataclass
class FakeReadme:
    decoded_content: bytes


@dataclass
class FakeContentFile:
    path: str
    type: str
    decoded_content: bytes = b""


@dataclass
class FakeRepo:
    branches: list
    pulls: list
    readme_content: bytes | None = None
    files: dict = field(default_factory=dict)  # 경로 -> 텍스트 내용, 디렉터리 목록은 경로에서 파생

    def get_branches(self):
        return self.branches

    def get_pulls(self, state="open"):
        return self.pulls

    def get_pull(self, number):
        return next(p for p in self.pulls if p.number == number)

    def get_readme(self):
        if self.readme_content is None:
            raise GithubException(404, {"message": "Not Found"}, {})
        return FakeReadme(decoded_content=self.readme_content)

    def get_contents(self, path):
        if path in self.files:
            return FakeContentFile(path=path, type="file", decoded_content=self.files[path].encode("utf-8"))

        prefix = f"{path}/" if path else ""
        entries = {}  # name -> "dir"/"file", 중복 디렉터리 제거용
        for p in self.files:
            if not p.startswith(prefix):
                continue
            rest = p[len(prefix):]
            name, _, remainder = rest.partition("/")
            entries[name] = "dir" if remainder else "file"
        return [FakeContentFile(path=f"{prefix}{name}", type=typ) for name, typ in sorted(entries.items())]


@dataclass
class FakeGithub:
    repo: FakeRepo

    def get_repo(self, name):
        return self.repo


def _make_pr():
    check_run = FakeCheckRun(
        name="test-suite",
        conclusion="failure",
        output=FakeOutput(summary="2 tests failed"),
    )
    commit = FakeCommit(check_runs=[check_run])
    return FakePR(
        number=42,
        title="Add shiny sprite toggle",
        state="open",
        head=FakeHead(ref="branch-42"),
        files=[FakeFile(filename="src/battle.ts", patch="+added line")],
        commits=[commit],
    )


@dataclass
class FakeGithub404:
    def get_repo(self, name):
        raise GithubException(404, {"message": "Not Found"}, {})


@dataclass
class FakeGithub500:
    def get_repo(self, name):
        raise GithubException(500, {"message": "Internal Server Error"}, {})


def test_fetch_node_returns_error_code_for_missing_repo():
    result = fetch_node({"repo": "owner/does-not-exist", "pr_number": None}, gh_client=FakeGithub404())

    assert result["results"]["fetch"] == FETCH_ERROR_REPO_NOT_EXIST
    assert result["diff"] == ""
    assert result["branches"] == []
    assert result["prs"] == []
    assert result["ci_logs"] == []


def test_fetch_node_reraises_non_404_github_errors():
    try:
        fetch_node({"repo": "owner/repo", "pr_number": None}, gh_client=FakeGithub500())
        assert False, "500 오류인데 예외가 안 났다"
    except GithubException as exc:
        assert exc.status == 500


def test_fetch_node_collects_branches_and_prs():
    repo = FakeRepo(branches=[FakeBranch(name="main"), FakeBranch(name="beta")], pulls=[_make_pr()])
    gh = FakeGithub(repo=repo)

    result = fetch_node({"repo": "rest8050/pokerogue_test", "pr_number": None}, gh_client=gh)

    assert result["branches"] == ["main", "beta"]
    assert result["prs"] == [
        {"number": 42, "title": "Add shiny sprite toggle", "state": "open", "branch": "branch-42"}
    ]


def test_fetch_node_skips_diff_and_ci_when_no_pr_number():
    repo = FakeRepo(branches=[FakeBranch(name="main")], pulls=[_make_pr()])
    gh = FakeGithub(repo=repo)

    result = fetch_node({"repo": "rest8050/pokerogue_test", "pr_number": None}, gh_client=gh)

    assert result["diff"] == ""
    assert result["ci_logs"] == []


def test_fetch_node_collects_diff_and_ci_logs_when_pr_number_given():
    repo = FakeRepo(branches=[FakeBranch(name="main")], pulls=[_make_pr()])
    gh = FakeGithub(repo=repo)

    result = fetch_node({"repo": "rest8050/pokerogue_test", "pr_number": 42}, gh_client=gh)

    assert "src/battle.ts" in result["diff"]
    assert "+added line" in result["diff"]
    assert result["ci_logs"] == [{"name": "test-suite", "conclusion": "failure", "summary": "2 tests failed"}]


def test_fetch_node_includes_readme_when_present():
    repo = FakeRepo(
        branches=[FakeBranch(name="main")],
        pulls=[_make_pr()],
        readme_content="# pokerogue_test\n데모 프로젝트".encode("utf-8"),
    )
    gh = FakeGithub(repo=repo)

    result = fetch_node({"repo": "rest8050/pokerogue_test", "pr_number": None}, gh_client=gh)

    assert result["readme"] == "# pokerogue_test\n데모 프로젝트"


def test_fetch_node_returns_empty_readme_when_missing():
    repo = FakeRepo(branches=[FakeBranch(name="main")], pulls=[_make_pr()])
    gh = FakeGithub(repo=repo)

    result = fetch_node({"repo": "rest8050/pokerogue_test", "pr_number": None}, gh_client=gh)

    assert result["readme"] == ""


def test_fetch_node_skips_successful_checks():
    check_run = FakeCheckRun(name="lint", conclusion="success", output=FakeOutput(summary="ok"))
    commit = FakeCommit(check_runs=[check_run])
    pr = FakePR(
        number=7,
        title="Fix typo",
        state="open",
        head=FakeHead(ref="branch-7"),
        files=[FakeFile(filename="README.md", patch="+fix")],
        commits=[commit],
    )
    repo = FakeRepo(branches=[FakeBranch(name="main")], pulls=[pr])
    gh = FakeGithub(repo=repo)

    result = fetch_node({"repo": "rest8050/pokerogue_test", "pr_number": 7}, gh_client=gh)

    assert result["ci_logs"] == []


def test_endpoint_agent_lists_flask_route_with_methods():
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={
            "app/routes.py": (
                "from flask import Blueprint\n"
                "bp = Blueprint('x', __name__)\n\n"
                "@bp.route('/users', methods=['GET', 'POST'])\n"
                "def list_users():\n"
                "    pass\n"
            ),
        },
    )
    gh = FakeGithub(repo=repo)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    output = result["results"]["endpoint"]
    assert "GET, POST" in output
    assert "/users" in output
    assert "list_users" in output
    assert "app/routes.py:4" in output


def test_endpoint_agent_lists_fastapi_route():
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={
            "api/main.py": (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.get('/health')\n"
                "async def health():\n"
                "    return {'ok': True}\n"
            ),
        },
    )
    gh = FakeGithub(repo=repo)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    output = result["results"]["endpoint"]
    assert "GET" in output
    assert "/health" in output
    assert "health" in output


def test_endpoint_agent_scans_nested_directories():
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={"src/api/v1/users.py": "@app.delete('/users/{id}')\ndef delete_user():\n    pass\n"},
    )
    gh = FakeGithub(repo=repo)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    output = result["results"]["endpoint"]
    assert "DELETE" in output
    assert "src/api/v1/users.py" in output


def test_endpoint_agent_returns_message_when_no_routes_found(monkeypatch):
    repo = FakeRepo(branches=[], pulls=[], files={"README.md": "hello"})
    gh = FakeGithub(repo=repo)

    # LLM 폴백도 후보를 하나도 못 고르는 경우를 흉내낸다.
    monkeypatch.setattr("graph.fetch.chat_completion", lambda messages, **kwargs: "[]")

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    assert result["results"]["endpoint"] == "감지된 엔드포인트가 없습니다."


def test_endpoint_agent_sorts_routes_by_file_then_path():
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={
            "z_app.py": "@app.get('/z')\ndef z():\n    pass\n",
            "a_app.py": "@app.get('/b')\ndef b():\n    pass\n\n@app.get('/a')\ndef a():\n    pass\n",
        },
    )
    gh = FakeGithub(repo=repo)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    rows = [line for line in result["results"]["endpoint"].splitlines() if line.startswith("|") and "Method" not in line and "---" not in line]
    assert [row.split("|")[2].strip() for row in rows] == ["/a", "/b", "/z"]


def test_endpoint_agent_falls_back_to_llm_for_non_python_repo(monkeypatch):
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={"main.go": "func main() {\n\trouter.HandleFunc(\"/ping\", pingHandler)\n}\n"},
    )
    gh = FakeGithub(repo=repo)

    def fake_chat_completion(messages, **kwargs):
        if messages[0]["role"] == "system":  # 추출 라운드
            return '```json\n[{"methods": ["GET"], "path": "/ping", "func": "pingHandler", "file": "main.go", "line": 2}]\n```'
        return '["main.go"]'  # 선택 라운드

    monkeypatch.setattr("graph.fetch.chat_completion", fake_chat_completion)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    output = result["results"]["endpoint"]
    assert "/ping" in output
    assert "pingHandler" in output
    assert "main.go:2" in output


def test_endpoint_agent_llm_fallback_sends_path_list_first_then_only_picked_file_content(monkeypatch):
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={
            "main.go": "router.HandleFunc(\"/ping\", pingHandler)\n",
            "util.go": "func add(a, b int) int {\n\treturn a + b\n}\n",
        },
    )
    gh = FakeGithub(repo=repo)
    captured = {}

    def fake_chat_completion(messages, **kwargs):
        if messages[0]["role"] == "system":
            captured["extraction_prompt"] = messages[-1]["content"]
            return '[{"methods": ["GET"], "path": "/ping", "func": "pingHandler", "file": "main.go", "line": 1}]'
        captured["selection_prompt"] = messages[-1]["content"]
        return '["main.go"]'

    monkeypatch.setattr("graph.fetch.chat_completion", fake_chat_completion)

    endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    # 파일 선택 단계엔 경로 목록 전체(내용 없이)를 넘긴다.
    assert "main.go" in captured["selection_prompt"]
    assert "util.go" in captured["selection_prompt"]
    # 실제 내용 스캔은 LLM이 고른 파일만.
    assert "main.go" in captured["extraction_prompt"]
    assert "util.go" not in captured["extraction_prompt"]


def test_endpoint_agent_llm_fallback_retries_with_next_files_when_first_round_finds_nothing(monkeypatch):
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={
            "a.go": "package a\n",
            "b.go": "router.HandleFunc(\"/ping\", pingHandler)\n",
        },
    )
    gh = FakeGithub(repo=repo)
    selection_prompts = []

    def fake_chat_completion(messages, **kwargs):
        if messages[0]["role"] == "system":
            if "b.go" in messages[-1]["content"]:
                return '[{"methods": ["GET"], "path": "/ping", "func": "pingHandler", "file": "b.go", "line": 1}]'
            return "[]"
        selection_prompts.append(messages[-1]["content"])
        return '["a.go"]' if len(selection_prompts) == 1 else '["b.go"]'

    monkeypatch.setattr("graph.fetch.chat_completion", fake_chat_completion)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    assert "/ping" in result["results"]["endpoint"]
    assert len(selection_prompts) == 2
    assert "a.go" not in selection_prompts[1]  # 이미 시도한 파일은 다음 라운드에서 빠진다


def test_endpoint_agent_llm_fallback_returns_no_endpoints_on_malformed_json(monkeypatch):
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={"main.go": "router.HandleFunc(\"/ping\", pingHandler)\n"},
    )
    gh = FakeGithub(repo=repo)

    def fake_chat_completion(messages, **kwargs):
        if messages[0]["role"] == "system":
            return "이건 JSON이 아닙니다"
        return '["main.go"]'

    monkeypatch.setattr("graph.fetch.chat_completion", fake_chat_completion)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    assert result["results"]["endpoint"] == "감지된 엔드포인트가 없습니다."


def test_endpoint_agent_skips_llm_when_regex_already_found_routes(monkeypatch):
    repo = FakeRepo(
        branches=[],
        pulls=[],
        files={"app.py": "@app.get('/health')\ndef health():\n    pass\n"},
    )
    gh = FakeGithub(repo=repo)

    def explode(messages, **kwargs):
        raise AssertionError("정규식이 이미 라우트를 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr("graph.fetch.chat_completion", explode)

    result = endpoint_agent({"repo": "owner/repo"}, gh_client=gh)

    assert "/health" in result["results"]["endpoint"]
