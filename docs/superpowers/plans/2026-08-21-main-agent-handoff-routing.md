# Main Agent Handoff Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Main Chat route and switch to exactly one Agent Chat without generating an answer or executing Agent work itself; automatically hand off requests except Video Generation, which requires user confirmation.

**Architecture:** Add a Main-only routing contract that returns the selected backend Agent, UI chat name, and untouched request. Make the Main frontend consume that contract and invoke the existing selected Agent Chat reply flow after navigation. Agent Chat reply endpoints use their explicit chat label as the fixed Agent, preventing content-based cross-Agent rerouting.

**Tech Stack:** FastAPI/Pydantic/pytest, React/TypeScript/Vite/Vitest/Testing Library, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-21-main-agent-handoff-routing-design.md`

## Global Constraints

- Modify only `main_agent/backend` and `main_agent/frontend`; do not change Agent-owned work schemas or execution APIs.
- Preserve the user request exactly except for the existing UI `trim()` used to reject blank input.
- Main Chat must not call an Agent endpoint, create a task, or show an Agent answer.
- Workmate AI, Development Assistant, and Game Q&A must automatically submit the handed-off request once and display the response there.
- Video Generation must receive the untouched request in its video brief input but must not create a video until the user submits it.
- Do not re-route an explicit Agent Chat request based on its text.
- Preserve Game Q&A commands, Story Review Workspace navigation, Video Generation page behavior, and pending-action handling.

---

### Task 1: Define and verify the backend Main-routing contract

**Files:**
- Modify: `main_agent/backend/app/main.py:55-70, 239-252, 326-368, 434-438`
- Modify: `main_agent/backend/tests/test_api.py:168-207`

**Interfaces:**
- Consumes: `RouterLLM.select(request: str) -> dict | None`, `CHAT_AGENT_NAMES`.
- Produces: `POST /api/main-route` with request body `{ "content": str }` and response `{ "targetAgent": str, "targetChat": str, "originalRequest": str, "handoff": "automatic" | "confirmation_required" }`.
- Produces: `route_main_chat_request(content: str) -> dict[str, str | bool]` as the endpoint’s testable routing helper.

- [ ] **Step 1: Write the failing backend contract tests**

```python
def test_main_route_returns_handoff_without_calling_an_agent(monkeypatch):
    from app import main

    class FakeRouter:
        async def select(self, request):
            assert request == "사용자 요청:\n오늘 브리핑 해줘"
            return {"selected_agents": ["workmate-agent"], "confidence": 0.97}

    monkeypatch.setattr(main, "router", FakeRouter())
    response = TestClient(app).post("/api/main-route", json={"content": "오늘 브리핑 해줘"})

    assert response.status_code == 200
    assert response.json() == {
        "targetAgent": "workmate-agent",
        "targetChat": "Workmate AI",
        "originalRequest": "오늘 브리핑 해줘",
        "handoff": "automatic",
    }


def test_agent_chat_uses_its_explicit_agent_instead_of_rerouting(monkeypatch):
    from app import main

    class FakeRouter:
        async def select(self, request):
            return {"selected_agents": ["dev-agent"], "confidence": 0.99}

    monkeypatch.setattr(main, "router", FakeRouter())
    response = TestClient(app).post(
        "/api/chats/Video%20Generation/reply",
        json={"content": "이 코드의 오류를 찾아줘"},
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "video-agent"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest -q tests/test_api.py -k "main_route or explicit_agent"`

Expected: FAIL because `/api/main-route` does not exist and `chat_reply()` still calls `resolve_chat_agent()` for an explicit Agent Chat.

- [ ] **Step 3: Add the minimal Main-routing implementation**

Add a `MainRouteRequest` Pydantic model and an `AGENT_CHAT_NAMES` reverse map. Implement the helper and endpoint:

```python
async def route_main_chat_request(content: str) -> dict[str, str | bool]:
    card_name = await resolve_chat_agent("Main Chatbot", content)
    target_chat = AGENT_CHAT_NAMES[card_name]
    return {
        "targetAgent": card_name,
        "targetChat": target_chat,
        "originalRequest": content,
        "handoff": "automatic",
    }


@app.post("/api/main-route")
async def main_route(payload: MainRouteRequest) -> dict[str, str | bool]:
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    return await route_main_chat_request(payload.content)
```

In `chat_reply()`, replace unconditional `resolve_chat_agent(agent_name, payload.content)` with fixed-card selection for names in `CHAT_AGENT_NAMES`; retain `resolve_chat_agent()` only for the legacy `Main Chatbot`/`Cat AI Chat` entry points. Remove the post-response `router.review()` replacement execution path so an Agent Chat cannot be moved after it has begun execution.

- [ ] **Step 4: Run the focused backend tests to verify they pass**

Run: `python -m pytest -q tests/test_api.py -k "main_route or explicit_agent or codexbook_chat_reply"`

Expected: PASS. The handoff JSON is exact; a Video Generation request remains `video-agent`; Game Q&A command mode remains `codex`.

- [ ] **Step 5: Commit the backend routing contract**

```bash
git add main_agent/backend/app/main.py main_agent/backend/tests/test_api.py
git commit -m "feat: add main chat handoff routing"
```

### Task 2: Make Main Chat consume the handoff contract and auto-submit once

**Files:**
- Modify: `main_agent/frontend/src/MainUiPanels.tsx:78-138`
- Modify: `main_agent/frontend/src/MainUiPanels.test.tsx:1-55`
- Modify: `main_agent/frontend/src/App.tsx:195-210, 430-555`
- Modify: `main_agent/frontend/src/App.test.tsx:1-91`

**Interfaces:**
- Consumes: `POST http://127.0.0.1:8000/api/main-route` response `{ targetAgent: string; targetChat: AgentName; originalRequest: string; handoff: "automatic" | "confirmation_required" }` from Task 1.
- Consumes: existing Agent reply endpoint `POST /api/chats/{targetChat}/reply`.
- Produces: `MainBriefingChatbot` route event with `{ chat, message, handoff }`; `App` automatically invokes its shared Agent reply flow only for `handoff === "automatic"`.

- [ ] **Step 1: Write the failing Main Chat handoff test**

Replace the global `fetch` mock in `App.test.tsx` with a URL-aware mock and add:

```tsx
it("hands a Main Chat request to the selected Agent Chat and keeps the answer out of Main Chat", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        targetAgent: "workmate-agent",
        targetChat: "Workmate AI",
        originalRequest: "오늘 브리핑 해줘",
        handoff: "automatic",
      }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ answer: "Workmate 브리핑 결과" }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  const input = screen.getByPlaceholderText("무엇을 도와드릴까요?");
  await userEvent.type(input, "오늘 브리핑 해줘");
  await userEvent.click(input.closest("form")!.querySelector("button[type='submit']")!);

  expect(await screen.findByText("AI Chat · Workmate AI")).toBeInTheDocument();
  expect(await screen.findByText("Workmate 브리핑 결과")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:8000/api/main-route",
    expect.objectContaining({ body: JSON.stringify({ content: "오늘 브리핑 해줘" }) }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:8000/api/chats/Workmate%20AI/reply",
    expect.objectContaining({ body: expect.stringContaining("오늘 브리핑 해줘") }),
  );
  expect(screen.queryByText("Workmate 브리핑 결과", { selector: ".main-chat" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend test to verify it fails**

Run: `npm run test:video-agent -- --run src/App.test.tsx`

Expected: FAIL because `MainBriefingChatbot` currently uses the local keyword route and does not call `/api/main-route`.

- [ ] **Step 3: Extract a shared Agent submission helper and route Main through it**

Create a local `MainRoute` type in `MainUiPanels.tsx` and replace `routeMainRequest()` plus the Main reply fallback with a call to `/api/main-route`. On success, append only `${targetChat}로 연결합니다.` to Main Chat, then dispatch:

```ts
window.dispatchEvent(new CustomEvent("main-chat-route", {
  detail: { chat: route.targetChat, message: route.originalRequest, handoff: route.handoff },
}));
```

In `App.tsx`, change the event detail type to include `handoff`. Create a shared helper by extracting the network-and-state portion of `submit()` into:

```ts
async function submitAgentRequest(targetChat: AgentName, request: string): Promise<void>
```

The helper must set `activeChatRef`, `activeSection`, and `activeChat` to `targetChat`; call `startChatTask(targetChat)`; persist the user message under `targetChat`; call the existing Agent reply endpoint for `targetChat`; and append only that Agent’s response to the target chat state.

When `handoff === "automatic"`, the `App.tsx` event handler calls `submitAgentRequest(targetChat, originalRequest)`. When `handoff === "confirmation_required"`, it only activates the selected chat and calls `setMessage(originalRequest)`; VideoAgentPage receives that text as its existing `initialBrief` and waits for the user to press `생성 요청`. On route API error, `MainBriefingChatbot` appends `담당 Agent를 판단하지 못했습니다. 다시 요청해 주세요.` and does not dispatch an event.

Remove the `requestedAgent` and `responseChat` cross-Chat rerouting branches from `submit()` so manually opened Agent Chats stay with their selected Agent. Keep the existing Game Q&A help, Story Review Workspace, pending action, unresolved scene, and art-prompt branches inside the shared helper.

- [ ] **Step 4: Run focused frontend tests to verify they pass**

Run: `npm run test:video-agent -- --run src/App.test.tsx`

Expected: PASS. Main Chat switches to Workmate AI, sends the untouched request once, and shows the result only in Workmate AI Chat. A Video route opens Video Generation with the original brief filled but does not call a create or reply endpoint. Existing Video and Game Q&A screen tests remain green after updating the expectations that previously required cross-Agent routing.

- [ ] **Step 5: Commit the Main frontend handoff flow**

```bash
git add main_agent/frontend/src/App.tsx main_agent/frontend/src/App.test.tsx
git commit -m "feat: hand off main chat requests to agent chats"
```

### Task 3: Run integration regression checks and rebuild the Main stack

**Files:**
- Verify only: `main_agent/backend/tests/test_api.py`
- Verify only: `main_agent/backend/tests/test_router.py`
- Verify only: `main_agent/frontend/src/App.test.tsx`
- Verify only: `main_agent/frontend/package.json`
- Verify only: `main_agent/docker-compose.yml`

**Interfaces:**
- Consumes: completed backend routing API from Task 1 and frontend automatic handoff from Task 2.
- Produces: verified Main Agent image exposing the routing contract and UI behavior.

- [ ] **Step 1: Run the complete backend routing and API suite**

Run: `python -m pytest -q tests/test_router.py tests/test_api.py`

Expected: PASS. No test expects Main Chat to execute an Agent request or an explicit Agent Chat to be replaced by router review.

- [ ] **Step 2: Run the frontend test suite and production build**

Run: `npm run test:video-agent && npm run build`

Expected: PASS and TypeScript/Vite build exits with status 0.

- [ ] **Step 3: Rebuild and start only the Main stack**

Run: `docker compose -f main_agent/docker-compose.yml up -d --build main-agent frontend`

Expected: `main-agent` and `frontend` start successfully; existing Agent containers remain available.

- [ ] **Step 4: Verify the routing API and browser flow**

Run:

```powershell
$payload = @{ content = "오늘 브리핑 해줘" } | ConvertTo-Json -Compress
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/main-route" -Method Post -ContentType "application/json" -Body $payload
```

Expected: HTTP 200 with `targetAgent: "workmate-agent"`, `targetChat: "Workmate AI"`, the same `originalRequest`, and `handoff: "automatic"`. Then submit the same phrase from Main Chat at `http://127.0.0.1:5173`; verify the displayed answer appears under `AI Chat · Workmate AI`, not Main Chat. Submit a video request and verify Video Generation opens with the brief prefilled but no generation begins before the user selects `생성 요청`.

- [ ] **Step 5: Commit verification-only changes only if any test fixtures required updates**

```bash
git status --short
```

Expected: no unintended files are staged; do not modify or stage unrelated existing changes.

## Plan Self-Review

- Spec coverage: Task 1 implements the routing contract and the no-rerouting backend boundary; Task 2 implements navigation, exact-text automatic handoff, and Main-only status; Task 3 verifies API, UI, build, Docker, and regressions.
- Placeholder scan: no incomplete implementation steps or unspecified interfaces remain.
- Type consistency: `targetAgent`, `targetChat`, `originalRequest`, and the `automatic`/`confirmation_required` `handoff` mode use the same names in the contract, backend tests, frontend type, and verification request.
