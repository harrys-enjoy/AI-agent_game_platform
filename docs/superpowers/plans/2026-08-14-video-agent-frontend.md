# Video-agent 전용 프론트엔드 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated video-agent page to `AI-agent_game_platform/frontend` (new isolated MAIN backend routes + a new Tailwind/Radix/Vitest-based page) that lets a user compose a video brief via chat or form, watch the task through its full A2A lifecycle, resolve manual-fix scenes, and see the finished video — without touching the existing shared chat/task code paths.

**Architecture:** New isolated backend routes (`/api/video-agent/tasks*`) proxy directly to video-agent's `/a2a/*` surface with a purpose-built minimal client (not the shared, buggy `A2AClient`). The frontend is a second Vite entry point (`video-agent.html`) mounting a standalone `VideoAgentPage`, polling `GET /api/video-agent/tasks/{id}` every 5s (a live proxy — no server-side state machine) until a terminal state, pausing on `TASK_STATE_INPUT_REQUIRED` and resuming after a scene upload.

**Tech Stack:** FastAPI + httpx (backend, existing); React + Vite + TypeScript + Tailwind CSS + `@radix-ui/react-tabs` + Vitest + React Testing Library (frontend, Tailwind/Radix/Vitest are new and scoped to this page only).

## Global Constraints

- Backend: Python, FastAPI, `httpx>=0.28`, `pydantic>=2.8` (existing `backend/requirements.txt` floors — do not lower them).
- Frontend: TypeScript `strict: true` (existing `tsconfig.json`) — new code must type-check under it.
- Do not modify `frontend/src/App.tsx`, `frontend/src/styles.css`, or any existing `npm run test:*` script. Routing into the new page from the sidebar is explicitly out of scope (separate future work).
- New backend routes reuse the existing module-level `registry: AgentRegistry` and `A2AError` (`backend/app/errors.py`) and follow the exact try/except → `HTTPException` translation pattern already established by `resume_video_scene` (`backend/app/main.py:363-384`).
- New backend route tests must use `monkeypatch.setattr(httpx.AsyncClient, "post"/"get", fake_fn)`, exactly like the existing resume-route tests (`backend/tests/test_api.py:249-303`). Do not add a new HTTP-mocking library (no `respx`).
- Every outbound call to video-agent (`message:send`, `GET /a2a/tasks/{id}`, `POST /a2a/tasks/{id}:cancel`) must include both `Authorization: Bearer {token}` and `A2A-Version: 1.0` headers — this is the exact bug (missing header on polling GETs) found in the old shared client, and regression tests must assert both headers on every call type.
- Every `message:send` call must carry a freshly generated UUID4 `messageId` — never a hardcoded literal (the second bug found in the old shared client).
- Tailwind/Radix/Vitest are net-new dependencies, scoped to `frontend/src/video-agent/**`, `frontend/video-agent.html`, `frontend/src/video-agent-main.tsx`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`. Do not apply Tailwind's Preflight globally in a way that affects `index.html`/`App.tsx` — the Tailwind stylesheet is only imported from `video-agent-main.tsx`.
- Frontend API calls hit MAIN's backend at `http://127.0.0.1:8000`, mirroring the existing hardcoded `API_BASE_URL` constant already used in `App.tsx:17`.
- Reuse `frontend/src/resume-utils.ts` as-is for manual-fix scene state (`buildUnresolvedScenes`, `markSceneStatus`, `mergeResumeResult`, `buildResumeFormData`) — do not duplicate this logic.

---

## File Structure

**Backend (`backend/app/`):**
- `video_agent_client.py` — NEW. Minimal async httpx client: `send_message`, `get_task`, `cancel_task`.
- `main.py` — MODIFY. Add `VideoAgentTaskRequest` model + 3 routes.

**Backend tests (`backend/tests/`):**
- `test_video_agent_client.py` — NEW.
- `test_video_agent_routes.py` — NEW.

**Frontend tooling (`frontend/`):**
- `package.json` — MODIFY (new deps + `test:video-agent` script).
- `vite.config.ts` — MODIFY (multi-entry build + Vitest `test` block).
- `tailwind.config.js`, `postcss.config.js` — NEW.
- `video-agent.html` — NEW (second Vite entry).
- `src/video-agent-main.tsx` — NEW (mounts the page).

**Frontend page (`frontend/src/video-agent/`):**
- `types.ts` — NEW. Wire types shared across the page.
- `api.ts` — NEW. Fetch wrappers for the 3 new routes + existing resume route.
- `brief-compose.ts` — NEW. Pure function assembling `FormComposer` fields into a Korean sentence matching `brief_intake.py`'s regex hints.
- `use-video-task-polling.ts` — NEW. Polling hook.
- `ComposerTabs.tsx`, `ChatComposer.tsx`, `FormComposer.tsx`, `StatusBadge.tsx`, `TaskCanvas.tsx`, `VideoAgentPage.tsx` — NEW.
- `test-setup.ts` — NEW. Vitest/RTL jest-dom setup.

**Integration verification (`AI-agent_game_platform/`):**
- `scripts/video_agent_smoke_test.sh` — NEW. Manual/local smoke script (cross-repo, not part of `pytest`).

---

### Task 1: `video_agent_client.py` — minimal A2A client

**Files:**
- Create: `backend/app/video_agent_client.py`
- Test: `backend/tests/test_video_agent_client.py`

**Interfaces:**
- Consumes: `AgentRegistry.config(name) -> AgentConfig` (`base_url` has no `/a2a` suffix, per `registry.py:32`), `AgentRegistry.headers(name) -> dict[str, str]` (Bearer only, `registry.py:83-85`), `A2AError` (`errors.py`).
- Produces: `async def send_message(registry: AgentRegistry, text: str) -> dict`, `async def get_task(registry: AgentRegistry, task_id: str) -> dict`, `async def cancel_task(registry: AgentRegistry, task_id: str) -> dict` — all raise `A2AError` on a video-agent error envelope, `RuntimeError` on connection/parse failure. Consumed by Task 2's routes.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_video_agent_client.py
import httpx
import pytest

from app.errors import A2AError
from app.registry import AgentRegistry
from app.video_agent_client import cancel_task, get_task, send_message


def _registry():
    registry = AgentRegistry()
    registry.register("video-agent", "http://video-agent:8002", token="secret-token")
    return registry


@pytest.mark.asyncio
async def test_send_message_posts_a2a_envelope_with_fresh_message_id(monkeypatch):
    seen = {}

    async def fake_post(self, url, *, json=None, headers=None):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_SUBMITTED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await send_message(_registry(), "할로윈 이벤트 영상 15초로 만들어줘")

    assert seen["url"] == "http://video-agent:8002/a2a/message:send"
    assert seen["json"]["message"]["role"] == "ROLE_USER"
    assert seen["json"]["message"]["parts"] == [{"text": "할로윈 이벤트 영상 15초로 만들어줘"}]
    assert seen["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["headers"]["A2A-Version"] == "1.0"
    assert len(seen["json"]["message"]["messageId"]) > 0
    assert result["task"]["id"] == "task_1"


@pytest.mark.asyncio
async def test_send_message_uses_a_fresh_message_id_every_call(monkeypatch):
    seen_ids = []

    async def fake_post(self, url, *, json=None, headers=None):
        seen_ids.append(json["message"]["messageId"])
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_SUBMITTED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    registry = _registry()
    await send_message(registry, "브리프 1")
    await send_message(registry, "브리프 2")

    assert seen_ids[0] != seen_ids[1]


@pytest.mark.asyncio
async def test_get_task_sends_bearer_and_a2a_version_headers(monkeypatch):
    seen = {}

    async def fake_get(self, url, *, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_WORKING"}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await get_task(_registry(), "task_1")

    assert seen["url"] == "http://video-agent:8002/a2a/tasks/task_1"
    assert seen["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["headers"]["A2A-Version"] == "1.0"
    assert result["task"]["status"]["state"] == "TASK_STATE_WORKING"


@pytest.mark.asyncio
async def test_cancel_task_posts_to_cancel_endpoint(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        assert url == "http://video-agent:8002/a2a/tasks/task_1:cancel"
        assert headers["A2A-Version"] == "1.0"
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_CANCELED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await cancel_task(_registry(), "task_1")

    assert result["task"]["status"]["state"] == "TASK_STATE_CANCELED"


@pytest.mark.asyncio
async def test_get_task_raises_a2a_error_on_error_envelope(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(
            404,
            json={"error": {"code": 404, "status": "NOT_FOUND", "message": "Unknown task: task_x"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(A2AError) as exc_info:
        await get_task(_registry(), "task_x")

    assert exc_info.value.http_status == 404
    assert "Unknown task: task_x" in exc_info.value.message


@pytest.mark.asyncio
async def test_send_message_raises_runtime_error_when_unreachable(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(httpx.ConnectError):
        await send_message(_registry(), "브리프")


@pytest.mark.asyncio
async def test_get_task_raises_runtime_error_on_non_json_body(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(500, text="internal server error", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(RuntimeError, match="video-agent HTTP 500"):
        await get_task(_registry(), "task_1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_video_agent_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.video_agent_client'`

- [ ] **Step 3: Implement the client**

```python
# backend/app/video_agent_client.py
import uuid
from typing import Any, Literal

import httpx

from .errors import A2AError
from .registry import AgentRegistry

A2A_VERSION = "1.0"


def _headers(registry: AgentRegistry) -> dict[str, str]:
    headers = dict(registry.headers("video-agent"))
    headers["A2A-Version"] = A2A_VERSION
    return headers


async def _call(url: str, method: Literal["post", "get"], *, headers: dict[str, str], json: dict | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        if method == "post":
            response = await client.post(url, json=json, headers=headers)
        else:
            response = await client.get(url, headers=headers)
    if response.is_error:
        try:
            raise A2AError.from_payload(response.json(), response.status_code)
        except ValueError:
            raise RuntimeError(f"video-agent HTTP {response.status_code}: {response.text}") from None
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("video-agent returned an unexpected response shape")
    return payload


async def send_message(registry: AgentRegistry, text: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    body = {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]}}
    return await _call(f"{config.base_url}/a2a/message:send", "post", headers=_headers(registry), json=body)


async def get_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}", "get", headers=_headers(registry))


async def cancel_task(registry: AgentRegistry, task_id: str) -> dict[str, Any]:
    config = registry.config("video-agent")
    return await _call(f"{config.base_url}/a2a/tasks/{task_id}:cancel", "post", headers=_headers(registry))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_video_agent_client.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/video_agent_client.py backend/tests/test_video_agent_client.py
git commit -m "feat: add minimal video-agent A2A client with correct auth headers and fresh messageIds"
```

---

### Task 2: `/api/video-agent/tasks*` routes

**Files:**
- Modify: `backend/app/main.py` (imports near line 10-18; new model near line 40-50; new routes placed directly after `resume_video_scene`, i.e. after line 384)
- Test: `backend/tests/test_video_agent_routes.py`

**Interfaces:**
- Consumes: `video_agent_client.send_message/get_task/cancel_task` (Task 1), module-level `registry` (`main.py:173`), `A2AError` (`errors.py`).
- Produces: `POST /api/video-agent/tasks` (body `{"message": str}` → `dict`), `GET /api/video-agent/tasks/{task_id} -> dict`, `POST /api/video-agent/tasks/{task_id}/cancel -> dict`. Consumed by the frontend's `api.ts` (Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_video_agent_routes.py
import httpx
from fastapi.testclient import TestClient

from app.main import app


def test_create_video_agent_task_proxies_message_send(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        assert url == "http://video-agent:8002/a2a/message:send"
        assert headers["A2A-Version"] == "1.0"
        assert json["message"]["parts"] == [{"text": "15초 이벤트 영상 만들어줘"}]
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_SUBMITTED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks", json={"message": "15초 이벤트 영상 만들어줘"})

    assert response.status_code == 200
    assert response.json()["task"]["id"] == "task_1"


def test_create_video_agent_task_returns_clarifying_question_response(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        return httpx.Response(200, json={"message": {"parts": [{"text": "어떤 영상을 원하시나요?"}]}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks", json={"message": "안녕"})

    assert response.status_code == 200
    assert response.json()["message"]["parts"][0]["text"] == "어떤 영상을 원하시나요?"


def test_create_video_agent_task_returns_502_when_unreachable(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks", json={"message": "브리프"})

    assert response.status_code == 502


def test_get_video_agent_task_proxies_and_includes_a2a_version_header(monkeypatch):
    seen = {}

    async def fake_get(self, url, *, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_WORKING"}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = TestClient(app).get("/api/video-agent/tasks/task_1")

    assert response.status_code == 200
    assert seen["url"] == "http://video-agent:8002/a2a/tasks/task_1"
    assert seen["headers"]["A2A-Version"] == "1.0"
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_WORKING"


def test_get_video_agent_task_maps_not_found_error(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(
            404,
            json={"error": {"code": 404, "status": "NOT_FOUND", "message": "Unknown task: task_x"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = TestClient(app).get("/api/video-agent/tasks/task_x")

    assert response.status_code == 404
    assert "Unknown task: task_x" in response.json()["detail"]["message"]


def test_get_video_agent_task_returns_502_on_malformed_response(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(200, text="not json", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = TestClient(app).get("/api/video-agent/tasks/task_1")

    assert response.status_code == 502


def test_cancel_video_agent_task_proxies_to_cancel_endpoint(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        assert url == "http://video-agent:8002/a2a/tasks/task_1:cancel"
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_CANCELED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks/task_1/cancel")

    assert response.status_code == 200
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_CANCELED"


def test_cancel_video_agent_task_forwards_terminal_task_error(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        return httpx.Response(
            400,
            json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "Task already terminal"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = TestClient(app).post("/api/video-agent/tasks/task_1/cancel")

    assert response.status_code == 400
    assert "already terminal" in response.json()["detail"]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_video_agent_routes.py -v`
Expected: FAIL with 404s (routes don't exist yet)

- [ ] **Step 3: Add the model, import, and 3 routes**

In `backend/app/main.py`, add to the imports (near line 12, alongside the other `app.` imports):

```python
from . import video_agent_client
```

Add near `TaskRequest` (line 40-41):

```python
class VideoAgentTaskRequest(BaseModel):
    message: str
```

Add directly after `resume_video_scene` (after line 384):

```python
@app.post("/api/video-agent/tasks")
async def create_video_agent_task(payload: VideoAgentTaskRequest) -> dict:
    try:
        return await video_agent_client.send_message(registry, payload.message)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/video-agent/tasks/{task_id}")
async def get_video_agent_task(task_id: str) -> dict:
    try:
        return await video_agent_client.get_task(registry, task_id)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/video-agent/tasks/{task_id}/cancel")
async def cancel_video_agent_task(task_id: str) -> dict:
    try:
        return await video_agent_client.cancel_task(registry, task_id)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_video_agent_routes.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_video_agent_routes.py
git commit -m "feat: add /api/video-agent/tasks live-proxy routes"
```

---

### Task 3: Frontend tooling — Tailwind, second Vite entry, Vitest wiring

**Files:**
- Modify: `frontend/package.json`, `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/video-agent.html`, `frontend/src/video-agent-main.tsx`, `frontend/src/video-agent/styles.css`, `frontend/src/video-agent/test-setup.ts`

**Interfaces:**
- Produces: a working `npm run build` (both `index.html` and `video-agent.html` entries), a working `npx vitest run` command reading `src/video-agent/**/*.test.{ts,tsx}`, and a `video-agent.html` page that mounts a placeholder — replaced by the real `VideoAgentPage` in Task 11.

- [ ] **Step 1: Install dependencies**

Run: `cd frontend && npm install --save @radix-ui/react-tabs && npm install --save-dev tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event`

- [ ] **Step 2: Add Tailwind config**

```js
// frontend/tailwind.config.js
export default {
  content: ["./video-agent.html", "./src/video-agent/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

```js
// frontend/postcss.config.js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

```css
/* frontend/src/video-agent/styles.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 3: Add the second Vite entry**

```html
<!-- frontend/video-agent.html -->
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <title>영상 생성 - Video Agent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/video-agent-main.tsx"></script>
  </body>
</html>
```

```tsx
// frontend/src/video-agent-main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./video-agent/styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div>Video Agent (WIP)</div>
  </StrictMode>,
);
```

- [ ] **Step 4: Add jest-dom setup file**

```ts
// frontend/src/video-agent/test-setup.ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Wire multi-entry build and Vitest into `vite.config.ts`**

```ts
// frontend/vite.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        videoAgent: "video-agent.html",
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/video-agent/test-setup.ts"],
    include: ["src/video-agent/**/*.test.{ts,tsx}"],
  },
});
```

- [ ] **Step 6: Add the `test:video-agent` script to `package.json`**

In `frontend/package.json`, add to `"scripts"`:

```json
"test:video-agent": "vitest run"
```

- [ ] **Step 7: Verify the build works**

Run: `cd frontend && npm run build`
Expected: succeeds, producing both `dist/index.html` and `dist/video-agent.html`

- [ ] **Step 8: Verify Vitest runs (zero tests yet is fine)**

Run: `cd frontend && npm run test:video-agent`
Expected: exits 0 with "no test files found" — this is expected at this point; Task 4 adds the first real test.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tailwind.config.js frontend/postcss.config.js frontend/video-agent.html frontend/src/video-agent-main.tsx frontend/src/video-agent/styles.css frontend/src/video-agent/test-setup.ts
git commit -m "chore: add Tailwind, Vitest, and a second Vite entry scoped to the video-agent page"
```

---

### Task 4: `types.ts` + `api.ts`

**Files:**
- Create: `frontend/src/video-agent/types.ts`, `frontend/src/video-agent/api.ts`, `frontend/src/video-agent/api.test.ts`

**Interfaces:**
- Consumes: `RawUnresolvedScene`, `ResumeResult`, `buildResumeFormData` from `frontend/src/resume-utils.ts` (existing).
- Produces: `TaskState`, `Task`, `MessageSendResponse` types; `createVideoAgentTask(message: string): Promise<MessageSendResponse>`, `getVideoAgentTask(taskId: string): Promise<Task>`, `cancelVideoAgentTask(taskId: string): Promise<Task>`, `resumeVideoAgentScene(taskId: string, sceneId: string, file: File): Promise<ResumeResult>` — consumed by Task 6 (polling hook) and Task 11 (`VideoAgentPage`).

- [ ] **Step 1: Write `types.ts`**

```ts
// frontend/src/video-agent/types.ts
import type { RawUnresolvedScene } from "../resume-utils";

export type TaskState =
  | "TASK_STATE_SUBMITTED"
  | "TASK_STATE_WORKING"
  | "TASK_STATE_INPUT_REQUIRED"
  | "TASK_STATE_AUTH_REQUIRED"
  | "TASK_STATE_COMPLETED"
  | "TASK_STATE_FAILED"
  | "TASK_STATE_CANCELED"
  | "TASK_STATE_REJECTED";

export type ArtifactPart = { text?: string; data?: Record<string, unknown>; mediaType?: string };
export type Artifact = { artifactId: string; name: string; parts: ArtifactPart[] };
export type TaskStatus = { state: TaskState; message?: { parts: ArtifactPart[] }; unresolvedScenes?: RawUnresolvedScene[] };
export type Task = { id: string; contextId: string; status: TaskStatus; artifacts?: Artifact[] };
export type MessageSendResponse = { task: Task } | { message: { parts: ArtifactPart[] } };
```

- [ ] **Step 2: Write the failing test for `api.ts`**

```ts
// frontend/src/video-agent/api.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelVideoAgentTask, createVideoAgentTask, getVideoAgentTask, resumeVideoAgentScene } from "./api";

describe("video-agent api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the message and returns the task", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_SUBMITTED" } } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createVideoAgentTask("15초 이벤트 영상 만들어줘");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/video-agent/tasks",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "15초 이벤트 영상 만들어줘" }) }),
    );
    expect("task" in result && result.task.id).toBe("task_1");
  });

  it("throws when task creation fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
    await expect(createVideoAgentTask("브리프")).rejects.toThrow("HTTP 502");
  });

  it("fetches a task by id from the encoded url", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task: { id: "task 1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const task = await getVideoAgentTask("task 1");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/video-agent/tasks/task%201");
    expect(task.status.state).toBe("TASK_STATE_WORKING");
  });

  it("cancels a task", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_CANCELED" } } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const task = await cancelVideoAgentTask("task_1");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/video-agent/tasks/task_1/cancel", { method: "POST" });
    expect(task.status.state).toBe("TASK_STATE_CANCELED");
  });

  it("uploads a scene resume file as form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ scene_id: "scene_04", resolved: true, remaining_unresolved: [], output_video_url: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["fake"], "fixed.png", { type: "image/png" });
    const result = await resumeVideoAgentScene("task_1", "scene_04", file);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/video-agent/tasks/task_1/scenes/scene_04/resume",
      expect.objectContaining({ method: "POST" }),
    );
    const call = fetchMock.mock.calls[0][1] as { body: FormData };
    expect((call.body.get("file") as File).name).toBe("fixed.png");
    expect(result.resolved).toBe(true);
  });
});
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./api` does not exist yet

- [ ] **Step 3: Implement `api.ts`**

```ts
// frontend/src/video-agent/api.ts
import { buildResumeFormData, type ResumeResult } from "../resume-utils";
import type { MessageSendResponse, Task } from "./types";

const API_BASE_URL = "http://127.0.0.1:8000";

export async function createVideoAgentTask(message: string): Promise<MessageSendResponse> {
  const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) throw new Error(`video-agent task create failed: HTTP ${response.status}`);
  return response.json();
}

export async function getVideoAgentTask(taskId: string): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}`);
  if (!response.ok) throw new Error(`video-agent task fetch failed: HTTP ${response.status}`);
  const payload = await response.json();
  return payload.task as Task;
}

export async function cancelVideoAgentTask(taskId: string): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error(`video-agent task cancel failed: HTTP ${response.status}`);
  const payload = await response.json();
  return payload.task as Task;
}

export async function resumeVideoAgentScene(taskId: string, sceneId: string, file: File): Promise<ResumeResult> {
  const response = await fetch(
    `${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}/scenes/${encodeURIComponent(sceneId)}/resume`,
    { method: "POST", body: buildResumeFormData(file) },
  );
  if (!response.ok) throw new Error(`video-agent scene resume failed: HTTP ${response.status}`);
  return response.json();
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video-agent/types.ts frontend/src/video-agent/api.ts frontend/src/video-agent/api.test.ts
git commit -m "feat: add video-agent page wire types and API client"
```

---

### Task 5: `brief-compose.ts`

**Files:**
- Create: `frontend/src/video-agent/brief-compose.ts`, `frontend/src/video-agent/brief-compose.test.ts`

**Interfaces:**
- Produces: `composeStructuredBrief(fields: StructuredBriefFields): string`. Consumed by Task 9 (`FormComposer`).

- [ ] **Step 1: Write the failing tests**

These mirror `video_draft_pipeline/src/video_draft_pipeline/a2a_server/brief_intake.py`'s `_DURATION_RE = re.compile(r"(\d+)\s*초")` and `_BUDGET_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:달러|\$|usd)", re.IGNORECASE)`, plus its `_PRESET_KEYWORDS`/`_SCENE_TYPE_KEYWORDS` literal keyword sets — the composed sentence must satisfy the same patterns since video-agent only parses free text.

```ts
// frontend/src/video-agent/brief-compose.test.ts
import { describe, expect, it } from "vitest";
import { composeStructuredBrief } from "./brief-compose";

// Mirrors brief_intake.py's _DURATION_RE / _BUDGET_RE exactly.
const DURATION_RE = /(\d+)\s*초/;
const BUDGET_RE = /(\d+(?:\.\d+)?)\s*(?:달러|\$|usd)/i;

describe("composeStructuredBrief", () => {
  it("always includes the raw brief text", () => {
    const sentence = composeStructuredBrief({ brief: "할로윈 신규 캐릭터 공개" });
    expect(sentence).toContain("할로윈 신규 캐릭터 공개");
  });

  it("encodes duration so brief_intake.py's duration regex matches", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", durationSec: 15 });
    const match = sentence.match(DURATION_RE);
    expect(match?.[1]).toBe("15");
  });

  it("encodes budget so brief_intake.py's budget regex matches", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", maxBudgetUsd: 3.5 });
    const match = sentence.match(BUDGET_RE);
    expect(match?.[1]).toBe("3.5");
  });

  it("includes a literal preset keyword brief_intake.py recognizes", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", preset: "이벤트" });
    expect(sentence).toContain("이벤트");
  });

  it("includes a literal scene_type keyword brief_intake.py recognizes", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", sceneType: "인게임" });
    expect(sentence).toContain("인게임");
  });

  it("composes all fields together and every field still matches", () => {
    const sentence = composeStructuredBrief({
      brief: "할로윈 이벤트",
      durationSec: 20,
      preset: "공개",
      sceneType: "스튜디오",
      maxBudgetUsd: 4,
    });
    expect(sentence.match(DURATION_RE)?.[1]).toBe("20");
    expect(sentence.match(BUDGET_RE)?.[1]).toBe("4");
    expect(sentence).toContain("공개");
    expect(sentence).toContain("스튜디오");
  });

  it("omits optional fields entirely when not provided", () => {
    const sentence = composeStructuredBrief({ brief: "테스트" });
    expect(sentence.match(DURATION_RE)).toBeNull();
    expect(sentence.match(BUDGET_RE)).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./brief-compose` does not exist yet

- [ ] **Step 3: Implement `brief-compose.ts`**

```ts
// frontend/src/video-agent/brief-compose.ts
export type StructuredBriefFields = {
  brief: string;
  durationSec?: number;
  preset?: "이벤트" | "공개" | "커뮤니티";
  sceneType?: "인게임" | "스튜디오";
  maxBudgetUsd?: number;
};

export function composeStructuredBrief(fields: StructuredBriefFields): string {
  const parts = [fields.brief.trim()];
  if (fields.durationSec) parts.push(`${fields.durationSec}초로`);
  if (fields.preset) parts.push(`${fields.preset} 프리셋`);
  if (fields.sceneType) parts.push(`${fields.sceneType} 씬으로`);
  if (fields.maxBudgetUsd) parts.push(`예산 ${fields.maxBudgetUsd}달러로`);
  return `${parts.join(", ")} 만들어줘`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video-agent/brief-compose.ts frontend/src/video-agent/brief-compose.test.ts
git commit -m "feat: assemble FormComposer fields into a brief_intake.py-compatible sentence"
```

---

### Task 6: `use-video-task-polling.ts`

**Files:**
- Create: `frontend/src/video-agent/use-video-task-polling.ts`, `frontend/src/video-agent/use-video-task-polling.test.ts`

**Interfaces:**
- Consumes: `getVideoAgentTask` (Task 4), `Task`/`TaskState` types (Task 4).
- Produces: `useVideoTaskPolling(taskId: string | null) -> { task: Task | null; reconnecting: boolean; error: string | null; resumePolling: () => void }`. Consumed by Task 11 (`VideoAgentPage`).

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/video-agent/use-video-task-polling.test.ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVideoTaskPolling } from "./use-video-task-polling";
import * as api from "./api";
import type { Task } from "./types";

function task(state: Task["status"]["state"]): Task {
  return { id: "task_1", contextId: "ctx_1", status: { state } };
}

describe("useVideoTaskPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("does nothing when taskId is null", () => {
    const spy = vi.spyOn(api, "getVideoAgentTask");
    renderHook(() => useVideoTaskPolling(null));
    expect(spy).not.toHaveBeenCalled();
  });

  it("polls again 5s after a non-terminal response", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockResolvedValue(task("TASK_STATE_WORKING"));
    renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("stops polling once a terminal state is reached", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockResolvedValue(task("TASK_STATE_COMPLETED"));
    renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("pauses on INPUT_REQUIRED and resumes only after resumePolling() is called", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockResolvedValue(task("TASK_STATE_INPUT_REQUIRED"));
    const { result } = renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    spy.mockResolvedValue(task("TASK_STATE_WORKING"));
    act(() => result.current.resumePolling());
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it("shows a reconnecting banner on the first failures but not an error", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(result.current.reconnecting).toBe(true));
    expect(result.current.error).toBeNull();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("escalates to an error after 3 consecutive failures", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await waitFor(() => expect(result.current.error).toBe("network down"));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./use-video-task-polling` does not exist yet

- [ ] **Step 3: Implement the hook**

```ts
// frontend/src/video-agent/use-video-task-polling.ts
import { useEffect, useRef, useState } from "react";
import { getVideoAgentTask } from "./api";
import type { Task, TaskState } from "./types";

const POLL_INTERVAL_MS = 5000;
const MAX_CONSECUTIVE_FAILURES = 3;
const TERMINAL_STATES: TaskState[] = ["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"];

export type PollingState = {
  task: Task | null;
  reconnecting: boolean;
  error: string | null;
  resumePolling: () => void;
};

export function useVideoTaskPolling(taskId: string | null): PollingState {
  const [task, setTask] = useState<Task | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumeSignal, setResumeSignal] = useState(0);
  const failureCountRef = useRef(0);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setReconnecting(false);
      setError(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const result = await getVideoAgentTask(taskId as string);
        if (cancelled) return;
        failureCountRef.current = 0;
        setReconnecting(false);
        setError(null);
        setTask(result);
        const paused = TERMINAL_STATES.includes(result.status.state) || result.status.state === "TASK_STATE_INPUT_REQUIRED";
        if (!paused) timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        failureCountRef.current += 1;
        if (failureCountRef.current >= MAX_CONSECUTIVE_FAILURES) {
          setReconnecting(false);
          setError(err instanceof Error ? err.message : "video-agent polling failed");
        } else {
          setReconnecting(true);
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, resumeSignal]);

  function resumePolling() {
    failureCountRef.current = 0;
    setResumeSignal((n) => n + 1);
  }

  return { task, reconnecting, error, resumePolling };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video-agent/use-video-task-polling.ts frontend/src/video-agent/use-video-task-polling.test.ts
git commit -m "feat: add 5s live-proxy polling hook with INPUT_REQUIRED pause/resume"
```

---

### Task 7: UI primitives + `StatusBadge` + `ComposerTabs`

**Files:**
- Create: `frontend/src/video-agent/StatusBadge.tsx`, `frontend/src/video-agent/StatusBadge.test.tsx`, `frontend/src/video-agent/ComposerTabs.tsx`, `frontend/src/video-agent/ComposerTabs.test.tsx`

**Interfaces:**
- Consumes: `TaskState` (Task 4), `@radix-ui/react-tabs` (Task 3).
- Produces: `StatusBadge({ state, startedAt }: { state: TaskState; startedAt: number })`, `ComposerTabs({ chat, form }: { chat: ReactNode; form: ReactNode })`. Consumed by Task 11.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/video-agent/StatusBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the Korean label for the given state", () => {
    render(<StatusBadge state="TASK_STATE_WORKING" startedAt={Date.now()} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("생성 중");
  });

  it("ticks the elapsed-time counter every second", () => {
    const startedAt = Date.now();
    render(<StatusBadge state="TASK_STATE_WORKING" startedAt={startedAt} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("0s");

    vi.setSystemTime(startedAt + 3000);
    vi.advanceTimersByTime(3000);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("3s");
  });
});
```

```tsx
// frontend/src/video-agent/ComposerTabs.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ComposerTabs } from "./ComposerTabs";

describe("ComposerTabs", () => {
  it("shows the chat panel by default and switches to the form panel on click", async () => {
    render(<ComposerTabs chat={<div>채팅 패널</div>} form={<div>폼 패널</div>} />);

    expect(screen.getByText("채팅 패널")).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "폼" }));
    expect(screen.getByText("폼 패널")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./StatusBadge` and `./ComposerTabs` do not exist yet

- [ ] **Step 3: Implement both components**

```tsx
// frontend/src/video-agent/StatusBadge.tsx
import { useEffect, useState } from "react";
import type { TaskState } from "./types";

const LABELS: Record<TaskState, string> = {
  TASK_STATE_SUBMITTED: "제출됨",
  TASK_STATE_WORKING: "생성 중",
  TASK_STATE_INPUT_REQUIRED: "수동 수정 필요",
  TASK_STATE_AUTH_REQUIRED: "인증 필요",
  TASK_STATE_COMPLETED: "완료",
  TASK_STATE_FAILED: "실패",
  TASK_STATE_CANCELED: "취소됨",
  TASK_STATE_REJECTED: "거부됨",
};

export function StatusBadge({ state, startedAt }: { state: TaskState; startedAt: number }) {
  const [elapsedSec, setElapsedSec] = useState(() => Math.floor((Date.now() - startedAt) / 1000));

  useEffect(() => {
    const interval = setInterval(() => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  return (
    <div className="flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-sm" data-testid="status-badge">
      <span>{LABELS[state]}</span>
      <span className="text-slate-400">{elapsedSec}s</span>
    </div>
  );
}
```

```tsx
// frontend/src/video-agent/ComposerTabs.tsx
import * as Tabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

export function ComposerTabs({ chat, form }: { chat: ReactNode; form: ReactNode }) {
  return (
    <Tabs.Root defaultValue="chat" className="flex flex-col gap-3">
      <Tabs.List className="flex gap-2" aria-label="브리프 작성 방식">
        <Tabs.Trigger value="chat" className="rounded px-3 py-1 text-sm data-[state=active]:bg-slate-900 data-[state=active]:text-white">
          채팅
        </Tabs.Trigger>
        <Tabs.Trigger value="form" className="rounded px-3 py-1 text-sm data-[state=active]:bg-slate-900 data-[state=active]:text-white">
          폼
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="chat">{chat}</Tabs.Content>
      <Tabs.Content value="form">{form}</Tabs.Content>
    </Tabs.Root>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video-agent/StatusBadge.tsx frontend/src/video-agent/StatusBadge.test.tsx frontend/src/video-agent/ComposerTabs.tsx frontend/src/video-agent/ComposerTabs.test.tsx
git commit -m "feat: add StatusBadge and ComposerTabs components"
```

---

### Task 8: `ChatComposer` + `FormComposer`

**Files:**
- Create: `frontend/src/video-agent/ChatComposer.tsx`, `frontend/src/video-agent/ChatComposer.test.tsx`, `frontend/src/video-agent/FormComposer.tsx`, `frontend/src/video-agent/FormComposer.test.tsx`

**Interfaces:**
- Consumes: `composeStructuredBrief` (Task 5).
- Produces: `ChatComposer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (message: string) => void })`, `FormComposer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (message: string) => void })`. Consumed by Task 11.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/video-agent/ChatComposer.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatComposer } from "./ChatComposer";

describe("ChatComposer", () => {
  it("submits the trimmed message", async () => {
    const onSubmit = vi.fn();
    render(<ChatComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("영상 브리프"), "  할로윈 이벤트 영상 15초  ");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    expect(onSubmit).toHaveBeenCalledWith("할로윈 이벤트 영상 15초");
  });

  it("does not submit text shorter than 5 characters", async () => {
    const onSubmit = vi.fn();
    render(<ChatComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("영상 브리프"), "짧음");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables the submit button while a task is busy", () => {
    render(<ChatComposer disabled={true} onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "생성 요청" })).toBeDisabled();
  });
});
```

```tsx
// frontend/src/video-agent/FormComposer.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FormComposer } from "./FormComposer";

describe("FormComposer", () => {
  it("composes the structured fields into one message on submit", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "할로윈 이벤트");
    await userEvent.type(screen.getByLabelText("길이(초)"), "15");
    await userEvent.selectOptions(screen.getByLabelText("프리셋"), "이벤트");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    const message = onSubmit.mock.calls[0][0] as string;
    expect(message).toContain("할로윈 이벤트");
    expect(message).toMatch(/15\s*초/);
    expect(message).toContain("이벤트");
  });

  it("does not submit when the brief is shorter than 5 characters", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "짧음");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./ChatComposer` and `./FormComposer` do not exist yet

- [ ] **Step 3: Implement both components**

```tsx
// frontend/src/video-agent/ChatComposer.tsx
import { useState, type FormEvent } from "react";

export function ChatComposer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (message: string) => void }) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed.length < 5) return;
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="예: 할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"
        className="min-h-24 rounded border border-slate-300 p-2 text-sm"
        aria-label="영상 브리프"
      />
      <button
        type="submit"
        disabled={disabled || value.trim().length < 5}
        className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
```

```tsx
// frontend/src/video-agent/FormComposer.tsx
import { useState, type FormEvent } from "react";
import { composeStructuredBrief } from "./brief-compose";

export function FormComposer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (message: string) => void }) {
  const [brief, setBrief] = useState("");
  const [durationSec, setDurationSec] = useState("");
  const [preset, setPreset] = useState("");
  const [sceneType, setSceneType] = useState("");
  const [maxBudgetUsd, setMaxBudgetUsd] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (brief.trim().length < 5) return;
    const message = composeStructuredBrief({
      brief,
      durationSec: durationSec ? Number(durationSec) : undefined,
      preset: preset ? (preset as "이벤트" | "공개" | "커뮤니티") : undefined,
      sceneType: sceneType ? (sceneType as "인게임" | "스튜디오") : undefined,
      maxBudgetUsd: maxBudgetUsd ? Number(maxBudgetUsd) : undefined,
    });
    onSubmit(message);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <textarea
        value={brief}
        onChange={(event) => setBrief(event.target.value)}
        placeholder="브리프 (필수)"
        aria-label="브리프"
        className="min-h-16 rounded border border-slate-300 p-2 text-sm"
      />
      <input
        value={durationSec}
        onChange={(event) => setDurationSec(event.target.value)}
        placeholder="길이(초)"
        aria-label="길이(초)"
        inputMode="numeric"
        className="rounded border border-slate-300 p-2 text-sm"
      />
      <select value={preset} onChange={(event) => setPreset(event.target.value)} aria-label="프리셋" className="rounded border border-slate-300 p-2 text-sm">
        <option value="">프리셋 선택 안 함</option>
        <option value="이벤트">이벤트</option>
        <option value="공개">공개</option>
        <option value="커뮤니티">커뮤니티</option>
      </select>
      <select value={sceneType} onChange={(event) => setSceneType(event.target.value)} aria-label="씬 종류" className="rounded border border-slate-300 p-2 text-sm">
        <option value="">씬 종류 선택 안 함</option>
        <option value="인게임">인게임</option>
        <option value="스튜디오">스튜디오</option>
      </select>
      <input
        value={maxBudgetUsd}
        onChange={(event) => setMaxBudgetUsd(event.target.value)}
        placeholder="예산(달러)"
        aria-label="예산(달러)"
        inputMode="decimal"
        className="rounded border border-slate-300 p-2 text-sm"
      />
      <button
        type="submit"
        disabled={disabled || brief.trim().length < 5}
        className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video-agent/ChatComposer.tsx frontend/src/video-agent/ChatComposer.test.tsx frontend/src/video-agent/FormComposer.tsx frontend/src/video-agent/FormComposer.test.tsx
git commit -m "feat: add ChatComposer and FormComposer"
```

---

### Task 9: `TaskCanvas`

**Files:**
- Create: `frontend/src/video-agent/TaskCanvas.tsx`, `frontend/src/video-agent/TaskCanvas.test.tsx`

**Interfaces:**
- Consumes: `Task` (Task 4), `UnresolvedScene` from `../resume-utils` (existing).
- Produces: `TaskCanvas({ task, unresolvedScenes, onUploadScene, onRetry })`. Consumed by Task 11.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/video-agent/TaskCanvas.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskCanvas } from "./TaskCanvas";
import { buildUnresolvedScenes } from "../resume-utils";
import type { Task } from "./types";

describe("TaskCanvas", () => {
  it("shows an idle prompt when there is no task", () => {
    render(<TaskCanvas task={null} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId("canvas-idle")).toBeVisible();
  });

  it("shows a working spinner for SUBMITTED and WORKING", () => {
    const task: Task = { id: "t1", contextId: "c1", status: { state: "TASK_STATE_WORKING" } };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId("canvas-working")).toBeVisible();
  });

  it("renders the completed video from the artifact data part", () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "영상 초안 결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId("canvas-completed")).toHaveAttribute("src", "http://x/video.mp4");
  });

  it("renders one upload card per unresolved scene and calls onUploadScene independently", async () => {
    const task: Task = { id: "t1", contextId: "c1", status: { state: "TASK_STATE_INPUT_REQUIRED" } };
    const scenes = buildUnresolvedScenes([
      { sceneId: "scene_04", imageUrl: "http://x/s4.png", issues: ["too wide"] },
      { sceneId: "scene_05", imageUrl: "http://x/s5.png", issues: [] },
    ]);
    const onUploadScene = vi.fn();
    render(<TaskCanvas task={task} unresolvedScenes={scenes} onUploadScene={onUploadScene} onRetry={vi.fn()} />);

    const file = new File(["fake"], "fixed.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("scene_04 수정 이미지 업로드"), file);

    expect(onUploadScene).toHaveBeenCalledWith("scene_04", file);
    expect(onUploadScene).toHaveBeenCalledTimes(1);
  });

  it("shows an error view with a retry button for FAILED", async () => {
    const task: Task = { id: "t1", contextId: "c1", status: { state: "TASK_STATE_FAILED" } };
    const onRetry = vi.fn();
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={onRetry} />);

    expect(screen.getByTestId("canvas-error")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(onRetry).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./TaskCanvas` does not exist yet

- [ ] **Step 3: Implement `TaskCanvas.tsx`**

```tsx
// frontend/src/video-agent/TaskCanvas.tsx
import type { UnresolvedScene } from "../resume-utils";
import type { Task } from "./types";

type Props = {
  task: Task | null;
  unresolvedScenes: UnresolvedScene[];
  onUploadScene: (sceneId: string, file: File) => void;
  onRetry: () => void;
};

export function TaskCanvas({ task, unresolvedScenes, onUploadScene, onRetry }: Props) {
  if (!task) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400" data-testid="canvas-idle">
        브리프를 작성하고 생성 요청을 눌러주세요.
      </div>
    );
  }

  const state = task.status.state;

  if (state === "TASK_STATE_SUBMITTED" || state === "TASK_STATE_WORKING") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3" data-testid="canvas-working">
        <span className="h-10 w-10 animate-spin rounded-full border-4 border-slate-300 border-t-slate-900" />
        <p>영상 생성 중...</p>
      </div>
    );
  }

  if (state === "TASK_STATE_INPUT_REQUIRED") {
    return (
      <div className="flex flex-col gap-3" data-testid="canvas-input-required">
        {unresolvedScenes.map((scene) => (
          <div key={scene.sceneId} className="rounded border border-slate-300 p-3" data-testid={`scene-card-${scene.sceneId}`}>
            <img src={scene.imageUrl} alt={scene.sceneId} className="mb-2 max-h-32 rounded" />
            <ul className="mb-2 text-sm text-red-600">
              {scene.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
            <input
              type="file"
              accept="image/*"
              aria-label={`${scene.sceneId} 수정 이미지 업로드`}
              disabled={scene.status === "uploading"}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUploadScene(scene.sceneId, file);
              }}
            />
            {scene.status === "error" && <p className="text-sm text-red-600">업로드 실패, 다시 시도해주세요.</p>}
          </div>
        ))}
      </div>
    );
  }

  if (state === "TASK_STATE_COMPLETED") {
    const videoUrl = task.artifacts
      ?.flatMap((artifact) => artifact.parts)
      .find((part) => typeof part.data?.output_video_url === "string")?.data?.output_video_url as string | undefined;
    return videoUrl ? (
      <video src={videoUrl} controls className="max-h-full rounded" data-testid="canvas-completed" />
    ) : (
      <div data-testid="canvas-completed-no-video">완료되었지만 영상 URL을 찾을 수 없습니다.</div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3" data-testid="canvas-error">
      <p>{state === "TASK_STATE_CANCELED" ? "취소되었습니다." : "생성에 실패했습니다."}</p>
      <button type="button" onClick={onRetry} className="rounded bg-slate-900 px-3 py-2 text-sm text-white">
        다시 시도
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video-agent/TaskCanvas.tsx frontend/src/video-agent/TaskCanvas.test.tsx
git commit -m "feat: add TaskCanvas with per-state views and isolated scene upload cards"
```

---

### Task 10: `VideoAgentPage` — top-level composition

**Files:**
- Create: `frontend/src/video-agent/VideoAgentPage.tsx`, `frontend/src/video-agent/VideoAgentPage.test.tsx`
- Modify: `frontend/src/video-agent-main.tsx` (swap the placeholder for the real page)

**Interfaces:**
- Consumes: `ComposerTabs`, `ChatComposer`, `FormComposer`, `StatusBadge`, `TaskCanvas` (Tasks 7-9), `useVideoTaskPolling` (Task 6), `createVideoAgentTask`/`cancelVideoAgentTask`/`resumeVideoAgentScene` (Task 4), `buildUnresolvedScenes`/`markSceneStatus`/`mergeResumeResult` (existing `resume-utils.ts`).
- Produces: `VideoAgentPage()` — the full page. Mounted by `video-agent-main.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/video-agent/VideoAgentPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VideoAgentPage } from "./VideoAgentPage";
import * as api from "./api";

describe("VideoAgentPage", () => {
  it("submits a chat brief, creates a task, and shows it working then completed", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({
      task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } },
    });
    vi.spyOn(api, "getVideoAgentTask").mockResolvedValue({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "영상 초안 결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("canvas-completed")).toHaveAttribute("src", "http://x/video.mp4"));
  });

  it("shows the clarifying question inline instead of creating a task", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({ message: { parts: [{ text: "어떤 영상을 원하시나요?" }] } });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "안녕하세요 도와주세요");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("clarifying-question")).toHaveTextContent("어떤 영상을 원하시나요?"));
    expect(screen.getByTestId("canvas-idle")).toBeVisible();
  });

  it("shows an inline error and keeps the composer filled in when submission fails", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockRejectedValue(new Error("video-agent task create failed: HTTP 502"));

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("submit-error")).toBeVisible());
    expect(screen.getByLabelText("영상 브리프")).toHaveValue("할로윈 이벤트 영상 15초");
  });

  it("uploading a resolved scene resumes polling and shows the finished video", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({
      task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } },
    });
    const getTask = vi.spyOn(api, "getVideoAgentTask");
    getTask.mockResolvedValueOnce({
      id: "task_1",
      contextId: "ctx_1",
      status: {
        state: "TASK_STATE_INPUT_REQUIRED",
        unresolvedScenes: [{ sceneId: "scene_04", imageUrl: "http://x/s4.png", issues: ["too wide"] }],
      },
    });
    vi.spyOn(api, "resumeVideoAgentScene").mockResolvedValue({
      scene_id: "scene_04",
      resolved: true,
      remaining_unresolved: [],
      output_video_url: "http://x/video.mp4",
    });
    getTask.mockResolvedValueOnce({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "영상 초안 결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("scene-card-scene_04")).toBeVisible());
    const file = new File(["fake"], "fixed.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("scene_04 수정 이미지 업로드"), file);

    await waitFor(() => expect(screen.getByTestId("canvas-completed")).toHaveAttribute("src", "http://x/video.mp4"));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent`
Expected: FAIL — `./VideoAgentPage` does not exist yet

- [ ] **Step 3: Implement `VideoAgentPage.tsx`**

```tsx
// frontend/src/video-agent/VideoAgentPage.tsx
import { useEffect, useState } from "react";
import { ChatComposer } from "./ChatComposer";
import { ComposerTabs } from "./ComposerTabs";
import { FormComposer } from "./FormComposer";
import { StatusBadge } from "./StatusBadge";
import { TaskCanvas } from "./TaskCanvas";
import { cancelVideoAgentTask, createVideoAgentTask, resumeVideoAgentScene } from "./api";
import { useVideoTaskPolling } from "./use-video-task-polling";
import { buildUnresolvedScenes, markSceneStatus, mergeResumeResult, type UnresolvedScene } from "../resume-utils";

export function VideoAgentPage() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [clarifyingQuestion, setClarifyingQuestion] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [unresolvedScenes, setUnresolvedScenes] = useState<UnresolvedScene[]>([]);
  const { task, reconnecting, error, resumePolling } = useVideoTaskPolling(taskId);

  useEffect(() => {
    if (task?.status.state === "TASK_STATE_INPUT_REQUIRED" && task.status.unresolvedScenes) {
      setUnresolvedScenes((previous) => (previous.length === 0 ? buildUnresolvedScenes(task.status.unresolvedScenes!) : previous));
    }
  }, [task?.id, task?.status.state, task?.status.unresolvedScenes]);

  async function handleSubmit(message: string) {
    setSubmitError(null);
    setClarifyingQuestion(null);
    try {
      const response = await createVideoAgentTask(message);
      if ("task" in response) {
        setTaskId(response.task.id);
        setStartedAt(Date.now());
        setUnresolvedScenes([]);
      } else {
        setClarifyingQuestion(response.message.parts.map((part) => part.text).filter(Boolean).join("\n"));
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "요청 제출에 실패했습니다.");
    }
  }

  async function handleCancel() {
    if (!taskId) return;
    await cancelVideoAgentTask(taskId);
  }

  async function handleUploadScene(sceneId: string, file: File) {
    if (!taskId) return;
    setUnresolvedScenes((scenes) => markSceneStatus(scenes, sceneId, "uploading"));
    try {
      const result = await resumeVideoAgentScene(taskId, sceneId, file);
      setUnresolvedScenes((scenes) => mergeResumeResult(scenes, result));
      resumePolling();
    } catch {
      setUnresolvedScenes((scenes) => markSceneStatus(scenes, sceneId, "error"));
    }
  }

  function handleRetry() {
    setTaskId(null);
    setUnresolvedScenes([]);
    setClarifyingQuestion(null);
  }

  const isBusy = task?.status.state === "TASK_STATE_SUBMITTED" || task?.status.state === "TASK_STATE_WORKING";

  return (
    <div className="grid h-screen grid-cols-[minmax(280px,360px)_1fr] gap-4 bg-slate-50 p-4">
      <aside className="flex flex-col gap-3 rounded-lg bg-white p-4 shadow-sm">
        <h1 className="text-lg font-semibold">영상 생성</h1>
        <ComposerTabs
          chat={<ChatComposer disabled={isBusy} onSubmit={handleSubmit} />}
          form={<FormComposer disabled={isBusy} onSubmit={handleSubmit} />}
        />
        {clarifyingQuestion && (
          <p className="rounded bg-amber-50 p-2 text-sm text-amber-800" data-testid="clarifying-question">
            {clarifyingQuestion}
          </p>
        )}
        {submitError && (
          <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="submit-error">
            {submitError}
          </p>
        )}
        {task && <StatusBadge state={task.status.state} startedAt={startedAt} />}
        {reconnecting && (
          <p className="text-sm text-amber-600" data-testid="reconnecting-banner">
            재연결 중...
          </p>
        )}
        {error && (
          <p className="text-sm text-red-700" data-testid="polling-error">
            {error}
          </p>
        )}
        {isBusy && (
          <button type="button" onClick={handleCancel} className="rounded border border-slate-300 px-3 py-2 text-sm">
            취소
          </button>
        )}
      </aside>
      <main className="rounded-lg bg-white p-4 shadow-sm">
        <TaskCanvas task={task} unresolvedScenes={unresolvedScenes} onUploadScene={handleUploadScene} onRetry={handleRetry} />
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent`
Expected: PASS (4 tests)

- [ ] **Step 5: Mount the real page**

```tsx
// frontend/src/video-agent-main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { VideoAgentPage } from "./video-agent/VideoAgentPage";
import "./video-agent/styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VideoAgentPage />
  </StrictMode>,
);
```

- [ ] **Step 6: Run the full frontend test and build suites for regressions**

Run: `cd frontend && npm run test:video-agent && npm run build`
Expected: all Vitest tests PASS, build succeeds

Run each existing hand-rolled script to confirm no regressions: `npm run test:agent-routing && npm run test:preview && npm run test:preview-mode && npm run test:menu && npm run test:task && npm run test:command && npm run test:story && npm run test:resume && npm run test:story-import`
Expected: all PASS (unaffected — no shared files were touched)

- [ ] **Step 7: Manually verify in the browser**

Run: `cd frontend && npm run dev`, then open `http://localhost:5173/video-agent.html`
Expected: page renders with the Chat/Form tabs and an idle canvas; submitting a brief requires the MAIN backend running at `http://127.0.0.1:8000` (see Task 11 for an end-to-end check against a real video-agent stub).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/video-agent/VideoAgentPage.tsx frontend/src/video-agent/VideoAgentPage.test.tsx frontend/src/video-agent-main.tsx
git commit -m "feat: compose the full video-agent page"
```

---

### Task 11: Cross-repo integration smoke script

This is deliberately **not** a `pytest` test: `video_draft_pipeline` and `AI-agent_game_platform` are separate repos/venvs on this machine (siblings under `C:\Users\golgi\edu\`), and wiring one as an installable dependency of the other was never decided in the spec. Instead, this is a runnable script that starts video-agent's existing zero-cost stub server (`fake_video_agent_server.py`, already built during the A2A migration) and MAIN's backend side by side, then drives the full lifecycle over real HTTP.

**Files:**
- Create: `scripts/video_agent_smoke_test.sh` (in `AI-agent_game_platform`)

**Interfaces:**
- Consumes: `video_draft_pipeline/scripts/fake_video_agent_server.py` (existing, sibling repo), `AI-agent_game_platform`'s own `backend/app/main.py` (Task 2's routes).
- Produces: a pass/fail console report of SUBMITTED → INPUT_REQUIRED → resume → COMPLETED driven entirely through the new `/api/video-agent/*` routes.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# scripts/video_agent_smoke_test.sh
#
# Manual/local cross-repo smoke test. Drives the full video-agent task
# lifecycle through MAIN's new /api/video-agent/* routes, against
# video-agent's zero-cost fake server (no billing).
#
# Usage: scripts/video_agent_smoke_test.sh [path-to-video_draft_pipeline-checkout]
set -euo pipefail

VIDEO_DRAFT_PIPELINE_DIR="${1:-../proj}"
VIDEO_SERVICE_TOKEN="smoke-test-token"
MAIN_PORT=8000
VIDEO_AGENT_PORT=8002

if [ ! -f "$VIDEO_DRAFT_PIPELINE_DIR/scripts/fake_video_agent_server.py" ]; then
  echo "fake_video_agent_server.py not found under $VIDEO_DRAFT_PIPELINE_DIR — pass the checkout path as \$1" >&2
  exit 1
fi

echo "Starting video-agent fake server on :$VIDEO_AGENT_PORT..."
(
  cd "$VIDEO_DRAFT_PIPELINE_DIR"
  VIDEO_SERVICE_TOKEN="$VIDEO_SERVICE_TOKEN" python scripts/fake_video_agent_server.py --port "$VIDEO_AGENT_PORT" &
  echo $! > /tmp/video_agent_smoke_fake_server.pid
)
sleep 2

echo "Starting MAIN backend on :$MAIN_PORT..."
(
  cd backend
  VIDEO_AGENT_URL="http://127.0.0.1:$VIDEO_AGENT_PORT" VIDEO_AGENT_SERVICE_TOKEN="$VIDEO_SERVICE_TOKEN" \
    python -m uvicorn app.main:app --port "$MAIN_PORT" &
  echo $! > /tmp/video_agent_smoke_main_server.pid
)
sleep 2

cleanup() {
  echo "Stopping servers..."
  kill "$(cat /tmp/video_agent_smoke_fake_server.pid)" 2>/dev/null || true
  kill "$(cat /tmp/video_agent_smoke_main_server.pid)" 2>/dev/null || true
}
trap cleanup EXIT

echo "1. Creating a task via MAIN..."
CREATE_RESPONSE=$(curl -sf -X POST "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks" \
  -H "Content-Type: application/json" \
  -d '{"message": "할로윈 이벤트 영상 15초로 만들어줘"}')
echo "$CREATE_RESPONSE"
TASK_ID=$(echo "$CREATE_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['id'])")
echo "Task ID: $TASK_ID"

echo "2. Polling until INPUT_REQUIRED (fake server always needs a manual fix)..."
for _ in $(seq 1 10); do
  POLL_RESPONSE=$(curl -sf "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks/$TASK_ID")
  STATE=$(echo "$POLL_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['status']['state'])")
  echo "  state=$STATE"
  [ "$STATE" = "TASK_STATE_INPUT_REQUIRED" ] && break
  sleep 2
done
[ "$STATE" = "TASK_STATE_INPUT_REQUIRED" ] || { echo "FAIL: never reached INPUT_REQUIRED" >&2; exit 1; }

SCENE_ID=$(echo "$POLL_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['status']['unresolvedScenes'][0]['sceneId'])")
echo "3. Resuming scene $SCENE_ID with a fixed image..."
printf 'fake-image-bytes' > /tmp/video_agent_smoke_fixed.png
curl -sf -X POST "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks/$TASK_ID/scenes/$SCENE_ID/resume" \
  -F "file=@/tmp/video_agent_smoke_fixed.png;type=image/png"

echo "4. Polling until COMPLETED..."
for _ in $(seq 1 10); do
  POLL_RESPONSE=$(curl -sf "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks/$TASK_ID")
  STATE=$(echo "$POLL_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['status']['state'])")
  echo "  state=$STATE"
  [ "$STATE" = "TASK_STATE_COMPLETED" ] && break
  sleep 2
done
[ "$STATE" = "TASK_STATE_COMPLETED" ] || { echo "FAIL: never reached COMPLETED" >&2; exit 1; }

echo "PASS: full SUBMITTED -> INPUT_REQUIRED -> resume -> COMPLETED lifecycle verified through MAIN's proxy routes."
```

- [ ] **Step 2: Make it executable and run it**

Run: `chmod +x scripts/video_agent_smoke_test.sh && scripts/video_agent_smoke_test.sh ../proj`
Expected: prints `PASS: full SUBMITTED -> INPUT_REQUIRED -> resume -> COMPLETED lifecycle verified through MAIN's proxy routes.`

If `fake_video_agent_server.py` requires `ffmpeg` on `PATH` or other setup, resolve per its own docstring in `video_draft_pipeline/scripts/fake_video_agent_server.py` before rerunning — this is the same zero-cost stub already used for video-agent's own `a2a_server_smoke_test.py`.

- [ ] **Step 3: Commit**

```bash
git add scripts/video_agent_smoke_test.sh
git commit -m "test: add cross-repo smoke script driving the full lifecycle through MAIN's new routes"
```

---

## Self-Review Notes

- **Spec coverage:** all 3 backend routes (Task 2), the minimal client avoiding the 3 old `A2AClient` bugs (Task 1), the live-proxy polling design incl. INPUT_REQUIRED pause/resume (Task 6), Layout B composition with Chat/Form tabs (Tasks 7-10), the `brief_intake.py`-matching sentence assembly (Task 5), all error-handling cases from the spec (502/401/malformed/terminal-task, form validation, reconnect-after-3-failures, per-scene upload isolation — Tasks 2, 6, 8, 9, 10), Tailwind/Radix/Vitest scoped tooling (Task 3), and the integration smoke test (Task 11) each have a task. Sidebar routing and MAIN-side persistent task storage are correctly excluded per the spec's non-goals.
- **Placeholder scan:** no TODO/TBD/"handle it later" strings; every step has literal code or an exact runnable command.
- **Type consistency:** `Task`/`TaskState`/`MessageSendResponse` (Task 4) are the single source of type truth used identically in Tasks 6-10; `UnresolvedScene`/`ResumeResult`/`buildResumeFormData`/`buildUnresolvedScenes`/`markSceneStatus`/`mergeResumeResult` are imported from the existing `resume-utils.ts` everywhere rather than redefined; `composeStructuredBrief`'s field names (`durationSec`, `maxBudgetUsd`, `preset`, `sceneType`) match between Task 5's implementation and Task 8's `FormComposer` caller.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-14-video-agent-frontend.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
