# Deployment Cleanup (Delete Stopped kosa-deploy-* Containers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the kosa_front "배포 현황" dashboard delete a STOPPED `kosa-deploy-*` deployment (and its compose siblings) from the UI, instead of leaving crashed test deployments piling up forever.

**Architecture:** One new backend endpoint (`DELETE /api/deployments/{name}`) that validates the container is STOPPED, finds its `com.docker.compose.project` label, and either `docker compose -p <project> down`s the whole project or `docker rm`s the single container. The frontend adds a "삭제" button to STOPPED cards in both existing deployment views, wired to call that endpoint and refresh.

**Tech Stack:** FastAPI (kosa_front's existing app), `docker` CLI via `subprocess` (existing `_run_docker` helper), vanilla JS (kosa_front's existing `main.js`, no framework/bundler).

## Global Constraints

- Scope is `dev_agent/` only — do not touch any other top-level folder in this monorepo (teammates have work in progress elsewhere).
- Only STOPPED deployments are deletable. RUNNING containers must be rejected with 409, enforced server-side (not just hidden in the UI) — the design explicitly chose this after considering and rejecting "allow RUNNING + confirm dialog".
- Deleting a compose-based deployment must remove the whole project (all sibling containers + network), not just the clicked container — confirmed via manual testing that `docker compose -p <project> down` works from the project name/label alone, no compose file needed.
- No confirmation dialog on delete (user's explicit choice: STOPPED-only is safe enough).
- No bulk "delete all" action — per-card delete only (user's explicit choice).
- Do not delete the underlying Docker image — only containers/network. Images get overwritten on the next deploy of the same repo; a separate `docker image prune -f` already runs during deploy.
- Follow existing kosa_front conventions: raise `HTTPException` directly from helper functions (see `get_docker_container_logs`), don't invent a new `{"ok": ..., "error": ...}` result-dict style.

---

### Task 1: Backend — `delete_docker_deployment()` + `DELETE /api/deployments/{name}` endpoint

**Files:**
- Modify: `dev_agent/kosa_front/main.py:474` (insert new function after `get_docker_container_logs`, before the `# Mock Data Generators` section comment at line 477)
- Modify: `dev_agent/kosa_front/main.py:804` (append new endpoint after `get_deployment_logs`, end of file)
- Test: `dev_agent/kosa_front/tests/test_deployments.py` (new file)

**Interfaces:**
- Consumes: `DEPLOY_CONTAINER_PREFIX` (`dev_agent/kosa_front/main.py:375`, already `"kosa-deploy-"`), `_run_docker(args: List[str]) -> subprocess.CompletedProcess` (`main.py:387`, already exists — runs `[docker_path, *args]` with `capture_output=True, text=True, timeout=10`).
- Produces: `async def delete_docker_deployment(name: str) -> None` — raises `HTTPException` on any failure, returns `None` on success. `DELETE /api/deployments/{name}` route returns `{"status": "deleted", "name": name}` (200) on success.

Verified manually against a real container before writing this task (so the plan doesn't guess at Docker CLI behavior):
```
$ docker inspect --format '{{.State.Running}}\t{{index .Config.Labels "com.docker.compose.project"}}' kosa-deploy-dockersamples-todo-list-app-mysql-1
false	kosa-deploy-dockersamples-todo-list-app

$ docker compose -p kosa-deploy-dockersamples-todo-list-app down
 Container kosa-deploy-dockersamples-todo-list-app-app-1 Stopping
 Container kosa-deploy-dockersamples-todo-list-app-mysql-1 Stopping
 ...
 Network kosa-deploy-dockersamples-todo-list-app_default Removed
$ echo $?
0
```
`docker compose -p <project> down` works from the project name alone (no `-f <compose file>` needed) — Compose v2 finds everything via the `com.docker.compose.project` label. This confirms the design is implementable exactly as planned.

- [ ] **Step 1: Write the failing tests**

Create `dev_agent/kosa_front/tests/test_deployments.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as kosa_main  # noqa: E402


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def client():
    return TestClient(kosa_main.app)


def test_delete_rejects_name_without_prefix(client, monkeypatch):
    calls = []
    monkeypatch.setattr(kosa_main, "_run_docker", lambda args: calls.append(args) or FakeCompleted())

    res = client.delete("/api/deployments/some-other-container")

    assert res.status_code == 400
    assert calls == []  # never touches docker for an unprefixed name


def test_delete_rejects_running_container(client, monkeypatch):
    def fake_run_docker(args):
        assert args[0] == "inspect"
        return FakeCompleted(stdout="true\t\n")

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 409


def test_delete_404s_when_container_missing(client, monkeypatch):
    monkeypatch.setattr(
        kosa_main, "_run_docker", lambda args: FakeCompleted(returncode=1, stderr="No such object")
    )

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 404


def test_delete_removes_single_container_when_no_compose_label(client, monkeypatch):
    calls = []

    def fake_run_docker(args):
        calls.append(args)
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\t\n")
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 200
    assert res.json() == {"status": "deleted", "name": "kosa-deploy-owner-repo"}
    assert calls[1] == ["rm", "kosa-deploy-owner-repo"]


def test_delete_removes_whole_compose_project_when_label_present(client, monkeypatch):
    calls = []

    def fake_run_docker(args):
        calls.append(args)
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\tkosa-deploy-owner-repo\n")
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo-mysql-1")

    assert res.status_code == 200
    assert calls[1] == ["compose", "-p", "kosa-deploy-owner-repo", "down"]


def test_delete_returns_500_when_removal_fails(client, monkeypatch):
    def fake_run_docker(args):
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\t\n")
        return FakeCompleted(returncode=1, stderr="permission denied")

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 500
    assert "permission denied" in res.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `dev_agent/kosa_front/`:
```bash
cd dev_agent/kosa_front
python -m pytest tests/test_deployments.py -v
```
Expected: all 6 tests FAIL — some with `AttributeError: module 'main' has no attribute ...` won't happen (route just 404s/405s since `DELETE /api/deployments/{name}` doesn't exist yet), so expect `assert res.status_code == 400` etc. to fail with the actual status being `405 Method Not Allowed` (no DELETE route registered yet).

- [ ] **Step 3: Add `delete_docker_deployment()` — insert after line 474 in `dev_agent/kosa_front/main.py`**

Insert this function immediately after `get_docker_container_logs` (which ends at line 474) and before the `# ==========================================` / `# Mock Data Generators (Graceful Fallback)` comment block at line 477:

```python
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
```

- [ ] **Step 4: Add the route — append after line 804 (end of file) in `dev_agent/kosa_front/main.py`**

```python


@app.delete("/api/deployments/{name}")
async def delete_deployment(name: str):
    """Delete a stopped kosa-deploy-* deployment (and its compose siblings, if any)."""
    await delete_docker_deployment(name)
    return {"status": "deleted", "name": name}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd dev_agent/kosa_front
python -m pytest tests/test_deployments.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add dev_agent/kosa_front/main.py dev_agent/kosa_front/tests/test_deployments.py
git commit -m "feat: delete stopped kosa-deploy-* deployments via DELETE /api/deployments/{name}"
```

---

### Task 2: Frontend — delete button on STOPPED cards in both deployment views

**Files:**
- Modify: `dev_agent/kosa_front/static/js/main.js:596-620` (`renderContainerCards` — top grid)
- Modify: `dev_agent/kosa_front/static/js/main.js:633-660` (`renderContainerList` — history list, already has `.btn-view-log`)

**Interfaces:**
- Consumes: `DELETE /api/deployments/{name}` from Task 1 (returns `{"status": "deleted", "name": ...}` on 200, `{"detail": "..."}` JSON body on 4xx/5xx — matches the existing `.btn-view-log` error-handling pattern at `main.js:662-680`).
- Consumes: `escapeHtml(str)` (existing helper, `main.js:579`), `fetchDeployments()` (existing, `main.js:290` — re-fetches and re-renders both views).
- Produces: `async function deleteDeployment(containerName)` — no return value consumed elsewhere, only called from the two render functions' click handlers.

No backend changes in this task — it's pure frontend wiring against the endpoint Task 1 already ships and tests.

- [ ] **Step 1: Add `deleteDeployment()` — insert after `renderContainerList` (after line 660, before `openTerminalLogModal` at line 662) in `dev_agent/kosa_front/static/js/main.js`**

```javascript
  async function deleteDeployment(containerName) {
    try {
      const res = await fetch(`/api/deployments/${encodeURIComponent(containerName)}`, { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(`삭제하지 못했습니다: ${err.detail || res.statusText}`);
        return;
      }
      await fetchDeployments();
    } catch (err) {
      alert(`삭제하지 못했습니다: ${err.message}`);
    }
  }
```

- [ ] **Step 2: Add the delete button to `renderContainerCards` — replace lines 596-620 in `dev_agent/kosa_front/static/js/main.js`**

Old:
```javascript
    DOM.envCardsGrid.innerHTML = containers.map(c => `
      <div class="glass-panel env-card">
        <div class="env-card-header">
          <span class="env-name" style="display: flex; align-items: center; gap: 0.5rem; font-weight: 800;">
            <i class="fa-solid fa-box" style="color: var(--primary);"></i>
            <span>${escapeHtml(c.repo)}</span>
          </span>
          <span class="badge ${c.running ? 'badge-open' : 'badge-closed'}">${c.running ? 'RUNNING' : 'STOPPED'}</span>
        </div>

        <div style="font-family: 'Fira Code', monospace; font-size: 0.82rem; margin-top: 0.4rem;">
          <div>포트: <strong>${escapeHtml(c.ports || '-')}</strong></div>
          <div style="color: var(--text-dim);">${escapeHtml(c.status)}</div>
        </div>

        <div class="metric-bar-group">
          <div class="metric-label"><span>CPU 사용률</span><span>${escapeHtml(c.cpu_usage || '-')}</span></div>
          <div class="progress-track"><div class="progress-fill" style="width: ${parseFloat(c.cpu_usage) || 0}%;"></div></div>
        </div>

        <div class="metric-bar-group">
          <div class="metric-label"><span>Memory 사용량</span><span>${escapeHtml(c.memory_usage || '-')}</span></div>
        </div>
      </div>
    `).join('');
  }
```

New:
```javascript
    DOM.envCardsGrid.innerHTML = containers.map(c => `
      <div class="glass-panel env-card">
        <div class="env-card-header">
          <span class="env-name" style="display: flex; align-items: center; gap: 0.5rem; font-weight: 800;">
            <i class="fa-solid fa-box" style="color: var(--primary);"></i>
            <span>${escapeHtml(c.repo)}</span>
          </span>
          <span class="badge ${c.running ? 'badge-open' : 'badge-closed'}">${c.running ? 'RUNNING' : 'STOPPED'}</span>
        </div>

        <div style="font-family: 'Fira Code', monospace; font-size: 0.82rem; margin-top: 0.4rem;">
          <div>포트: <strong>${escapeHtml(c.ports || '-')}</strong></div>
          <div style="color: var(--text-dim);">${escapeHtml(c.status)}</div>
        </div>

        <div class="metric-bar-group">
          <div class="metric-label"><span>CPU 사용률</span><span>${escapeHtml(c.cpu_usage || '-')}</span></div>
          <div class="progress-track"><div class="progress-fill" style="width: ${parseFloat(c.cpu_usage) || 0}%;"></div></div>
        </div>

        <div class="metric-bar-group">
          <div class="metric-label"><span>Memory 사용량</span><span>${escapeHtml(c.memory_usage || '-')}</span></div>
        </div>

        ${!c.running ? `
        <button class="btn btn-secondary btn-delete-deploy" data-container-name="${escapeHtml(c.name)}" style="margin-top: 0.75rem; width: 100%;">
          <i class="fa-solid fa-trash"></i> 삭제
        </button>` : ''}
      </div>
    `).join('');

    // .btn-delete-deploy exists in both renderContainerCards and renderContainerList's
    // output — scope the wiring to this grid's own root so it doesn't also pick up (and
    // double-wire) the history list's buttons when both renders run back-to-back.
    DOM.envCardsGrid.querySelectorAll('.btn-delete-deploy').forEach(btn => {
      btn.addEventListener('click', () => void deleteDeployment(btn.getAttribute('data-container-name')));
    });
  }
```

- [ ] **Step 3: Add the delete button to `renderContainerList` — replace lines 633-660 in `dev_agent/kosa_front/static/js/main.js`**

Old:
```javascript
    DOM.deployHistoryList.innerHTML = containers.map(c => `
      <div class="pr-card">
        <div class="pr-card-header">
          <div class="pr-title-group">
            <div class="pr-title">
              <i class="fa-solid fa-box"></i> ${escapeHtml(c.name)}
            </div>
            <div style="font-size: 0.78rem; color: var(--text-dim);">${escapeHtml(c.image)}</div>
          </div>
          <span class="badge ${c.running ? 'badge-open' : 'badge-closed'}">${escapeHtml(c.status)}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 0.5rem;">
          <div style="font-size: 0.75rem; color: var(--text-muted); font-family: 'Fira Code', monospace;">
            ${escapeHtml(c.ports || '포트 없음')} • ${escapeHtml(c.created_at)}
          </div>
          <button class="btn btn-secondary btn-view-log" data-container-name="${escapeHtml(c.name)}">
            <i class="fa-solid fa-terminal"></i> 로그 보기
          </button>
        </div>
      </div>
    `).join('');

    document.querySelectorAll('.btn-view-log').forEach(btn => {
      btn.addEventListener('click', () => {
        openTerminalLogModal(btn.getAttribute('data-container-name'));
      });
    });
```

New:
```javascript
    DOM.deployHistoryList.innerHTML = containers.map(c => `
      <div class="pr-card">
        <div class="pr-card-header">
          <div class="pr-title-group">
            <div class="pr-title">
              <i class="fa-solid fa-box"></i> ${escapeHtml(c.name)}
            </div>
            <div style="font-size: 0.78rem; color: var(--text-dim);">${escapeHtml(c.image)}</div>
          </div>
          <span class="badge ${c.running ? 'badge-open' : 'badge-closed'}">${escapeHtml(c.status)}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 0.5rem;">
          <div style="font-size: 0.75rem; color: var(--text-muted); font-family: 'Fira Code', monospace;">
            ${escapeHtml(c.ports || '포트 없음')} • ${escapeHtml(c.created_at)}
          </div>
          <div style="display: flex; gap: 0.5rem;">
            <button class="btn btn-secondary btn-view-log" data-container-name="${escapeHtml(c.name)}">
              <i class="fa-solid fa-terminal"></i> 로그 보기
            </button>
            ${!c.running ? `
            <button class="btn btn-secondary btn-delete-deploy" data-container-name="${escapeHtml(c.name)}">
              <i class="fa-solid fa-trash"></i> 삭제
            </button>` : ''}
          </div>
        </div>
      </div>
    `).join('');

    document.querySelectorAll('.btn-view-log').forEach(btn => {
      btn.addEventListener('click', () => {
        openTerminalLogModal(btn.getAttribute('data-container-name'));
      });
    });

    // Scoped to this list's own root — see the matching comment in renderContainerCards.
    DOM.deployHistoryList.querySelectorAll('.btn-delete-deploy').forEach(btn => {
      btn.addEventListener('click', () => void deleteDeployment(btn.getAttribute('data-container-name')));
    });
```

- [ ] **Step 4: Manual verification (no JS test harness exists in this project for `main.js` — matches existing convention, all coverage here is on the Python backend)**

1. Rebuild and start the stack (or just `kosa-front` if only it changed):
   ```bash
   cd main_agent
   docker compose up -d --build kosa-front
   ```
2. Trigger a deploy that will end up STOPPED (reuse the known-crashing repo from the design's manual testing, or any repo without a working Dockerfile/compose entrypoint) via the dev-agent chat: `"테스트 레포지토리 하나 배포해줘"`.
3. Open `http://localhost:8004`, go to "배포 현황 & 파이프라인" tab.
4. Confirm: STOPPED cards (both the top grid and the "최근 배포 이력" list below) now show a "삭제" button; RUNNING cards do not.
5. Click "삭제" on one card. Confirm: the request succeeds, the card (and, if it was a compose deployment, its sibling containers) disappear from both views without a page reload.
6. Run `docker ps -a --filter name=kosa-deploy` in a terminal — confirm the container(s) are actually gone, not just hidden client-side.

- [ ] **Step 5: Commit**

```bash
git add dev_agent/kosa_front/static/js/main.js
git commit -m "feat: add delete button for stopped deployments in kosa_front dashboard"
```

---

## Self-Review Notes

- **Spec coverage:** Q1 (delete whole compose project) → Task 1 Step 3 (`compose -p <project> down`). Q2 (STOPPED-only, server-enforced) → Task 1 Step 3 (409 on `running == "true"`) + Task 2 Step 2/3 (button hidden client-side too, defense in depth matches the design). Q3 (no bulk delete) → no bulk-delete task exists anywhere in this plan. "No confirm dialog" → `deleteDeployment()` in Task 2 Step 1 has none.
- **Placeholder scan:** none found — every step has complete code, no TBD/TODO.
- **Type consistency:** `delete_docker_deployment(name: str) -> None` (Task 1) is only ever called from `delete_deployment` in the same task; `deleteDeployment(containerName)` (Task 2) is only called from the two click handlers added in the same task. No cross-task signature drift.
