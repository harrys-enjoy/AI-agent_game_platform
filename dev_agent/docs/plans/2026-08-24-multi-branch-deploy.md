# Multi-Branch Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user name a specific branch in a chat request ("feat/x 브랜치 배포해줘") and have `deploy_trigger` actually deploy that branch, side-by-side with any other branch already deployed for the same repo, instead of always deploying (and colliding on) the default branch.

**Architecture:** `ci_trigger.py::_resolve_ref` (already shared by `ci_trigger` and `deploy_trigger`) gains a branch-name-matching step between the existing PR-number check and the default-branch fallback: it scans `state["branches"]` (already fetched by the `fetch` node) for a name that appears in `state["request"]` at a word boundary. `deploy_trigger.py::_slot_name` gains an optional `branch`/`default_branch` pair of parameters so the Docker container/image name includes the branch — but only when it differs from the repo's default branch, so existing default-branch deployments keep their current slot name unchanged.

**Tech Stack:** Python (no new dependencies), existing `pytest` test suite in `dev_agent/tests/`.

## Global Constraints

- Scope is `dev_agent/` only — do not touch any other top-level folder in this monorepo.
- One branch per chat request (user's explicit choice — no comma-separated multi-branch parsing in a single message).
- No kosa_front frontend changes in this plan (user's explicit choice — the branch-suffixed slot name is legible enough as-is on the existing cards; a prettier repo/branch split display is a separate future task if wanted).
- Default-branch deployments must keep their current slot name (`kosa-deploy-<repo>`, no branch suffix) — this is what makes the change backward compatible with the delete feature and any deployment already running.
- Branch matching must not have false positives from a name being a substring of a longer word (e.g. branch `main` must not match inside `main_agent` — this monorepo has directories named exactly that, so it's a real risk, not a hypothetical one).

---

### Task 1: Branch-name resolution in `_resolve_ref`

**Files:**
- Modify: `dev_agent/graph/ci_trigger.py:1-30` (add `_find_mentioned_branch`, extend `_resolve_ref`)
- Test: `dev_agent/tests/test_ci_trigger.py`

**Interfaces:**
- Consumes: nothing new — `state["branches"]` (list of branch name strings, already produced by `graph/fetch.py:71`) and `state["request"]` (already the raw user message, set in `dev_agent/a2a_server.py`'s `initial_state`).
- Produces: `_find_mentioned_branch(request: str, branches: list[str]) -> str | None`. `_resolve_ref(state: dict, repo) -> str` keeps its existing signature and return type — Task 2 calls it exactly as `deploy_trigger_node` already does today.

- [ ] **Step 1: Write the failing tests**

Add to `dev_agent/tests/test_ci_trigger.py`, right after the existing `test_resolve_ref_falls_back_when_pr_number_not_in_list` test (currently ending at line 52):

```python
def test_find_mentioned_branch_matches_exact_name():
    assert _find_mentioned_branch("feat/x 배포해줘", ["main", "feat/x"]) == "feat/x"


def test_find_mentioned_branch_ignores_substring_inside_larger_word():
    # "main" must not match inside "main_agent" — a real directory name in this repo.
    assert _find_mentioned_branch("main_agent 폴더 상태 보여줘", ["main"]) is None


def test_find_mentioned_branch_prefers_longer_more_specific_match():
    assert _find_mentioned_branch("feat/x 배포해줘", ["feat", "feat/x"]) == "feat/x"


def test_find_mentioned_branch_returns_none_when_nothing_matches():
    assert _find_mentioned_branch("아무 브랜치도 언급 안 함", ["main", "feat/x"]) is None


def test_resolve_ref_uses_mentioned_branch_when_no_pr_number():
    state = {"pr_number": None, "prs": [], "request": "feat/x 배포해줘", "branches": ["beta", "feat/x"]}
    assert _resolve_ref(state, FakeRepo()) == "feat/x"


def test_resolve_ref_prefers_pr_branch_over_mentioned_branch():
    state = {
        "pr_number": 42,
        "prs": [{"number": 42, "branch": "demo/bug-1"}],
        "request": "feat/x 배포해줘",
        "branches": ["beta", "feat/x"],
    }
    assert _resolve_ref(state, FakeRepo()) == "demo/bug-1"


def test_resolve_ref_falls_back_to_default_when_no_branch_mentioned():
    state = {"pr_number": None, "prs": [], "request": "그냥 상태 보여줘", "branches": ["beta", "feat/x"]}
    assert _resolve_ref(state, FakeRepo()) == "beta"
```

Also add `_find_mentioned_branch` to the existing import line at the top of the file (currently line 3):

```python
from graph.ci_trigger import _collect_failed_jobs, _find_mentioned_branch, _resolve_ref, ci_trigger_node
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
cd dev_agent
python -m pytest tests/test_ci_trigger.py -v
```
Expected: the 3 existing `test_resolve_ref_*` tests still PASS unchanged; the 7 new tests FAIL — `_find_mentioned_branch` tests with `ImportError` (name doesn't exist yet), the new `_resolve_ref` tests with `AssertionError` (falls back to `"beta"` since no branch-matching exists yet, but `test_resolve_ref_uses_mentioned_branch_when_no_pr_number` expects `"feat/x"`).

- [ ] **Step 3: Implement `_find_mentioned_branch` and extend `_resolve_ref` — replace lines 1-30 of `dev_agent/graph/ci_trigger.py`**

Old (lines 1-30):
```python
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
```

New:
```python
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

def _timeout_sec() -> int:
    return int(os.getenv("CI_TRIGGER_TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC))


def _find_mentioned_branch(request: str, branches: list) -> str | None:
    """요청 텍스트에 실제 브랜치 이름이 단어 경계로 등장하면 그 이름을 돌려준다.

    긴 이름부터 검사해서 "feat"과 "feat/x"가 둘 다 존재할 때 더 구체적인 쪽을
    우선한다. 단순 substring 검사면 "main"이 "main_agent" 안에서 오탐된다 — 이
    모노레포 자체에 그런 디렉터리가 있어 실제로 위험한 케이스다. 앞뒤가 단어
    문자(영숫자/밑줄)나 "/", "-"가 아닐 때만 진짜 매치로 인정한다.
    """
    for branch in sorted(branches, key=len, reverse=True):
        pattern = r"(?<![\w/-])" + re.escape(branch) + r"(?![\w/-])"
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
    mentioned = _find_mentioned_branch(state.get("request", ""), state.get("branches", []))
    if mentioned:
        return mentioned
    return repo.default_branch
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd dev_agent
python -m pytest tests/test_ci_trigger.py -v
```
Expected: all 10 tests PASS (3 original + 7 new).

- [ ] **Step 5: Run the full dev_agent suite to confirm no regressions**

```bash
cd dev_agent
python -m pytest tests/ -q
```
Expected: same pass count as before this change, plus the 7 new tests (146 + 7 = 153 passed, 4 skipped — matching the baseline from the previous feature's final run, with 7 more added here).

- [ ] **Step 6: Commit**

```bash
git add dev_agent/graph/ci_trigger.py dev_agent/tests/test_ci_trigger.py
git commit -m "feat: resolve target branch from chat text, not just PR number"
```

---

### Task 2: Branch-aware deployment slot naming

**Files:**
- Modify: `dev_agent/graph/deploy_trigger.py:117-124` (`_slot_name`)
- Modify: `dev_agent/graph/deploy_trigger.py:308-344` (`deploy_trigger_node` — reorder so `ref` is known before `slot` is computed)
- Test: `dev_agent/tests/test_deploy_trigger.py`

**Interfaces:**
- Consumes: `_resolve_ref(state, repo) -> str` from Task 1 (already imported in this file via `from graph.ci_trigger import _resolve_ref`, line 26 — unchanged).
- Produces: `_slot_name(repo: str, branch: str | None = None, default_branch: str | None = None) -> str` — the `branch`/`default_branch` params are both optional and default to `None`, so every existing call site (`_slot_name("owner/repo-a")`) keeps working unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `dev_agent/tests/test_deploy_trigger.py`, right after `test_slot_name_differs_per_repo` (currently ending at line 406):

```python
def test_slot_name_appends_branch_when_not_default():
    assert _slot_name("owner/repo", "feat/x", "main") == "kosa-deploy-owner-repo-feat-x"


def test_slot_name_omits_branch_when_it_equals_default():
    assert _slot_name("owner/repo", "main", "main") == "kosa-deploy-owner-repo"


def test_slot_name_omits_branch_when_not_provided():
    assert _slot_name("owner/repo") == "kosa-deploy-owner-repo"
```

Add these after `test_deploy_trigger_node_uses_different_slot_for_different_repo` (currently ending at line 459):

```python
def test_deploy_trigger_node_uses_branch_specific_slot_when_branch_mentioned():
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            captured["clone_branch"] = cmd[cmd.index("--branch") + 1]
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-a", "request": "feat/x 브랜치로 배포해줘", "branches": ["beta", "feat/x"]},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert captured["clone_branch"] == "feat/x"
    assert captured["build_tag"] == _slot_name("owner/repo-a", "feat/x", "beta")
    assert captured["build_tag"] != _slot_name("owner/repo-a")  # default-branch slot untouched


def test_deploy_trigger_node_keeps_bare_slot_when_default_branch_mentioned():
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-a", "request": "beta 브랜치 배포해줘", "branches": ["beta", "feat/x"]},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert captured["build_tag"] == _slot_name("owner/repo-a")
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
cd dev_agent
python -m pytest tests/test_deploy_trigger.py -v
```
Expected: the 3 new `_slot_name` tests FAIL with `TypeError: _slot_name() takes 1 positional argument but 2/3 were given`. The 2 new `deploy_trigger_node` tests FAIL on the `build_tag` assertion (still gets the bare repo slot, since branch isn't threaded through yet).

- [ ] **Step 3: Update `_slot_name` — replace lines 117-124 of `dev_agent/graph/deploy_trigger.py`**

Old:
```python
def _slot_name(repo: str) -> str:
    """레포별로 겹치지 않는 컨테이너/이미지 이름을 만든다.

    "owner/name" 형태의 "/"는 Docker 이름에 못 쓰므로 치환하고, 이미지 태그는
    소문자만 허용되므로 소문자로 통일한다.
    """
    safe = _UNSAFE_SLOT_CHARS.sub("-", repo.lower())
    return f"{_SLOT_PREFIX}-{safe}"
```

New:
```python
def _slot_name(repo: str, branch: str | None = None, default_branch: str | None = None) -> str:
    """레포별로(그리고 기본 브랜치가 아닌 브랜치를 지정했다면 브랜치별로도) 겹치지 않는
    컨테이너/이미지 이름을 만든다.

    "owner/name" 형태의 "/"는 Docker 이름에 못 쓰므로 치환하고, 이미지 태그는
    소문자만 허용되므로 소문자로 통일한다. 기본 브랜치 배포는 지금까지처럼 브랜치를
    슬롯 이름에 안 붙인다 — 그래야 기존에 떠 있는 배포/삭제 기능과 호환된다. 다른
    브랜치를 명시했을 때만 같은 레포를 나란히 배포할 수 있도록 슬롯을 분리한다.
    """
    safe_repo = _UNSAFE_SLOT_CHARS.sub("-", repo.lower())
    if branch and branch != default_branch:
        safe_branch = _UNSAFE_SLOT_CHARS.sub("-", branch.lower())
        return f"{_SLOT_PREFIX}-{safe_repo}-{safe_branch}"
    return f"{_SLOT_PREFIX}-{safe_repo}"
```

- [ ] **Step 4: Reorder `deploy_trigger_node` so `ref` is resolved before `slot` — replace lines 308-344 of `dev_agent/graph/deploy_trigger.py`**

Old:
```python
def deploy_trigger_node(
    state: dict,
    gh_client: Github | None = None,
    run=subprocess.run,
    health_check=_wait_for_health,
    compose_health_check=_wait_for_compose_healthy,
    port_range: range = PORT_RANGE,
) -> dict:
    docker = _docker_path()

    try:
        info = run([docker, "info"], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired):
        return {"results": {"deploy": "Docker Desktop이 실행 중이 아닙니다. 켜고 다시 시도해주세요."}}

    if info.returncode != 0:
        return {"results": {"deploy": "Docker Desktop이 실행 중이 아닙니다. 켜고 다시 시도해주세요."}}

    worker = _acquire_lock()
    if worker is None:
        return {
            "results": {
                "deploy": f"이미 배포가 {MAX_CONCURRENT_DEPLOYS}건 진행 중입니다. 잠시 후 다시 시도해주세요."
            }
        }

    slot = _slot_name(state["repo"])
    clone_dir = _clone_dir(worker)

    try:
        gh = gh_client or get_github_client()
        repo = gh.get_repo(state["repo"])
        ref = _resolve_ref(state, repo)

        clone_error = _clone_repo(state["repo"], ref, run, clone_dir)
```

New:
```python
def deploy_trigger_node(
    state: dict,
    gh_client: Github | None = None,
    run=subprocess.run,
    health_check=_wait_for_health,
    compose_health_check=_wait_for_compose_healthy,
    port_range: range = PORT_RANGE,
) -> dict:
    docker = _docker_path()

    try:
        info = run([docker, "info"], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired):
        return {"results": {"deploy": "Docker Desktop이 실행 중이 아닙니다. 켜고 다시 시도해주세요."}}

    if info.returncode != 0:
        return {"results": {"deploy": "Docker Desktop이 실행 중이 아닙니다. 켜고 다시 시도해주세요."}}

    worker = _acquire_lock()
    if worker is None:
        return {
            "results": {
                "deploy": f"이미 배포가 {MAX_CONCURRENT_DEPLOYS}건 진행 중입니다. 잠시 후 다시 시도해주세요."
            }
        }

    clone_dir = _clone_dir(worker)

    try:
        gh = gh_client or get_github_client()
        repo = gh.get_repo(state["repo"])
        ref = _resolve_ref(state, repo)
        slot = _slot_name(state["repo"], ref, repo.default_branch)

        clone_error = _clone_repo(state["repo"], ref, run, clone_dir)
```

Everything after this point in the function (`compose_file = _find_compose_file(clone_dir)` onward, through the end of the `try` block and the `finally: _release_lock(worker)`) is unchanged — `slot` is still in scope, just computed one step later than before.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd dev_agent
python -m pytest tests/test_deploy_trigger.py -v
```
Expected: all tests PASS, including the 5 new ones.

- [ ] **Step 6: Run the full dev_agent suite to confirm no regressions**

```bash
cd dev_agent
python -m pytest tests/ -q
```
Expected: 153 + 5 = 158 passed, 4 skipped.

- [ ] **Step 7: Commit**

```bash
git add dev_agent/graph/deploy_trigger.py dev_agent/tests/test_deploy_trigger.py
git commit -m "feat: give non-default-branch deployments their own container slot"
```

- [ ] **Step 8: Manual verification against the real stack**

1. Rebuild and restart dev-agent (the only container whose code changed):
   ```bash
   cd main_agent
   docker compose up -d --build dev-agent
   ```
2. Confirm the repo is still correctly configured (from the earlier session fix):
   ```bash
   docker exec main_agent-dev-agent-1 python -c "import os; print(os.environ.get('WORKSPACE_REPO_MAP'))"
   ```
   Expected: `game-team-a=harrys-enjoy/AI-agent_game_platform` (no duplicated key this time).
3. Deploy the default branch first, to have a baseline running deployment:
   ```bash
   docker exec main_agent-main-agent-1 python -c "
   import httpx, json
   r = httpx.post('http://127.0.0.1:8000/api/chats/Development%20Assistant/reply', json={'content':'배포해줘','owner':'테스트'}, timeout=300)
   print(r.status_code); print(r.json().get('answer'))
   "
   ```
4. Deploy a named non-default branch of the same repo (use an actual branch that exists on `harrys-enjoy/AI-agent_game_platform` at the time — check with `git branch -r` if `feat/logging` or another branch isn't pushed yet, pick one that is, e.g. `codex/orchestrator-docker` itself since that's always present):
   ```bash
   docker exec main_agent-main-agent-1 python -c "
   import httpx, json
   r = httpx.post('http://127.0.0.1:8000/api/chats/Development%20Assistant/reply', json={'content':'codex/orchestrator-docker 브랜치로 배포해줘','owner':'테스트'}, timeout=300)
   print(r.status_code); print(r.json().get('answer'))
   "
   ```
5. Confirm both are running side by side, under distinct slot names:
   ```bash
   docker ps -a --filter "name=kosa-deploy" --format "{{.Names}}\t{{.Status}}"
   ```
   Expected: two different container name prefixes for the same repo — one bare (`kosa-deploy-harrys-enjoy-ai-agent_game_platform...`) and one with the branch suffix (`...-codex-orchestrator-docker`) — both present, neither having stopped/removed the other.
6. Open `http://localhost:8004`, "배포 현황 & 파이프라인" tab — confirm both deployments show as separate cards, and (from the previous feature) that STOPPED ones can still be deleted individually without affecting the other.
7. Clean up whatever test containers this leaves behind the same way as before (`docker compose -p <project> down` per project, or the dashboard's delete button now that Task 1/2 of the previous plan shipped it).

---

## Self-Review Notes

- **Spec coverage:** "브랜치 지정" via free text (Q1: A/A) → Task 1's `_find_mentioned_branch` + real-branch-list matching. Word-boundary safety (raised in design discussion re: `main`/`main_agent`) → `_find_mentioned_branch`'s regex guard, with a dedicated test. "한 번에 하나씩, 여러 번 요청" (Q1 chosen option) → no multi-branch-per-message parsing anywhere in this plan, by design. Branch-aware slots so repeat requests for different branches don't collide (the original ask) → Task 2's `_slot_name` change. "프론트 안 건드림" (Q3: A) → no `kosa_front/` files touched anywhere in this plan.
- **Placeholder scan:** none found.
- **Type consistency:** `_find_mentioned_branch(request: str, branches: list) -> str | None` defined in Task 1, used only inside `_resolve_ref` in the same task — no cross-task drift. `_slot_name(repo: str, branch: str | None = None, default_branch: str | None = None) -> str` defined in Task 2 Step 3, called with the 3-arg form only inside `deploy_trigger_node` (Task 2 Step 4) and the new Task 2 tests — matches everywhere.
