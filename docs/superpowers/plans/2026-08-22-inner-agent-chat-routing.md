# 내부 Agent Chat 상호 라우팅 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 어느 전문 Agent Chat에서 입력해도 적절한 Agent 화면으로 자동 전환·전달하고, 모호한 요청은 실행 전에 Agent 선택을 요구한다.

**Architecture:** Main Agent 백엔드는 원래 Chat 이름을 출처로만 취급하고, 명시적 Game Q&A 명령어·확정 선택·공통 라우터 순으로 실제 담당 Agent를 결정한다. 프론트엔드는 실제 담당 Agent를 응답에서 받아 해당 내부 UI로 전환하고, 원문·응답을 대상 Chat의 이력으로 저장한다. Project Task 자동 제안은 명시적인 Task 의도만 처리해 Workmate의 일정·회의 경로를 가로채지 않는다.

**Tech Stack:** FastAPI/Pydantic/pytest, React/TypeScript/Vitest, Vite.

**Spec:** `docs/superpowers/specs/2026-08-22-inner-agent-chat-routing-design.md`

## Global Constraints

- `workmate-agent/`, `video_agent/`, `dev_agent/`, `qna_agent/`의 소스·API·DB 마이그레이션을 수정하지 않는다.
- Main Agent는 Workmate의 일정·회의·Task 저장 API를 직접 호출하지 않는다.
- Game Q&A의 명시적 슬래시 명령어는 기존 모드와 동작을 유지한다.
- 자동 전환은 실제 담당 Agent Chat으로 이동하며, 모호한 요청은 선택 전 외부 Agent를 호출하지 않는다.

---

### Task 1: 백엔드의 내부 Chat 라우팅 결정 계약

**Files:**
- Modify: `main_agent/backend/app/main.py:68-96, 246-280, 356-427`
- Test: `main_agent/backend/tests/test_api.py:168-260`

**Interfaces:**
- Consumes: `ChatReplyRequest.content`, `ChatReplyRequest.owner`, 기존 `RouterLLM.select()` 결과.
- Produces: `resolve_chat_route(agent_name, content, selected_agent=None) -> dict[str, Any]` 및 `chat_reply()`의 `status`, `agent`, `target_chat`, `agent_options` 응답 필드.

- [ ] **Step 1: 실패하는 API 테스트를 추가한다**

```python
def test_internal_game_chat_routes_schedule_to_workmate(monkeypatch):
    class FakeRouter:
        async def select(self, request):
            return {"selected_agents": ["workmate-agent"], "confidence": 0.97}
    monkeypatch.setattr(main, "router", FakeRouter())
    response = TestClient(app).post("/api/chats/Game Q&A/reply", json={"content": "다음 주 회의 일정 잡아줘"})
    assert response.status_code == 200
    assert response.json()["agent"] == "workmate-agent"
    assert response.json()["target_chat"] == "Workmate AI"

def test_ambiguous_internal_chat_requires_agent_selection(monkeypatch):
    class FakeRouter:
        async def select(self, request):
            return None
    monkeypatch.setattr(main, "router", FakeRouter())
    response = TestClient(app).post("/api/chats/Game Q&A/reply", json={"content": "이거 만들어줘"})
    assert response.status_code == 200
    assert response.json()["status"] == "needs_agent_selection"
    assert response.json()["agent_options"] == ["Workmate AI", "Video Generation", "Development Assistant", "Game Q&A"]

def test_explicit_game_command_bypasses_common_routing(monkeypatch):
    class FailIfCalled:
        async def select(self, request):
            raise AssertionError("explicit command must not be rerouted")
    monkeypatch.setattr(main, "router", FailIfCalled())
    response = TestClient(app).post("/api/chats/Workmate AI/reply", json={"content": "/lore 홍길동"})
    assert response.json()["agent"] == "game-qna-agent"
    assert response.json()["mode"] == "lore"
```

- [ ] **Step 2: 테스트가 현재 실패함을 확인한다**

Run: `python -m pytest tests/test_api.py -k "internal_game_chat_routes_schedule or ambiguous_internal_chat or explicit_game_command" -q`

Expected: FAIL because an internal Chat is fixed by `CHAT_AGENT_NAMES` and no ambiguity response exists.

- [ ] **Step 3: 최소 라우팅 계약을 구현한다**

```python
class ChatReplyRequest(BaseModel):
    content: str
    owner: str = "미지정"
    selected_agent: str | None = None
    confirmed_skill_id: str | None = None
    confirmed_arguments: dict[str, Any] | None = None

async def resolve_chat_route(agent_name: str, content: str, selected_agent: str | None = None) -> dict[str, Any]:
    if selected_agent in AGENT_CHAT_NAMES:
        return {"agent": selected_agent, "needs_selection": False}
    command = parse_game_qna_command(content)
    if content.strip().startswith("/") and command["kind"] in {"help", "request"}:
        return {"agent": "game-qna-agent", "needs_selection": False}
    routed = await router.select(f"사용자 요청:\n{content}")
    if routed and len(routed["selected_agents"]) == 1:
        return {"agent": routed["selected_agents"][0], "needs_selection": False}
    return {"agent": None, "needs_selection": True}
```

`chat_reply()`는 `needs_selection`일 때 Agent 클라이언트를 만들거나 호출하지 않고 `status="needs_agent_selection"`, `agent_options=list(AGENT_CHAT_NAMES.values())`를 반환한다. 선택값은 `AGENT_CHAT_NAMES` 키만 허용하고 그 외는 422로 거부한다. 일반 성공 응답에는 `target_chat=AGENT_CHAT_NAMES[card_name]`를 추가한다.

- [ ] **Step 4: 백엔드 라우팅 테스트를 통과시킨다**

Run: `python -m pytest tests/test_api.py -k "chat_reply or main_route or internal_game_chat_routes_schedule or ambiguous_internal_chat or explicit_game_command" -q`

Expected: PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add main_agent/backend/app/main.py main_agent/backend/tests/test_api.py
git commit -m "feat: route requests from internal agent chats"
```

### Task 2: Project Task 자동 감지에서 일정·회의를 분리한다

**Files:**
- Modify: `main_agent/frontend/src/task-utils.ts:14-20`
- Test: `main_agent/frontend/scripts/task-utils-test.mjs:25-52`

**Interfaces:**
- Consumes: 자연어 `request: string`.
- Produces: `isTaskRequest(request): boolean`; `getTaskAction(request): "chat" | "confirm"`.

- [ ] **Step 1: 실패하는 Task 의도 테스트를 추가한다**

```javascript
test("does not intercept schedule or meeting requests as Project Tasks", () => {
  assert.equal(getTaskAction("다음 주 회의 일정 추가해줘"), "chat");
  assert.equal(getTaskAction("캘린더에 일정 등록해줘"), "chat");
});

test("keeps explicit Project Task requests in confirmation flow", () => {
  assert.equal(getTaskAction("이 내용을 Task로 추가해줘"), "confirm");
  assert.equal(getTaskAction("이 작업을 할 일로 등록해줘"), "confirm");
});
```

- [ ] **Step 2: 테스트가 현재 실패함을 확인한다**

Run: `npm run test:task`

Expected: FAIL because `일정` alone is a Task trigger.

- [ ] **Step 3: 명시적인 Task 용어만 허용하도록 구현한다**

```typescript
export function isTaskRequest(request: string): boolean {
  return /(?:추가|등록|할당|만들)/i.test(request)
    && /(?:\btask\b|작업|할\s*일)/i.test(request);
}
```

`일정`, `회의`, `캘린더`는 Task 판별 정규식에 넣지 않는다.

- [ ] **Step 4: Task 유틸리티 테스트를 통과시킨다**

Run: `npm run test:task`

Expected: PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add main_agent/frontend/src/task-utils.ts main_agent/frontend/scripts/task-utils-test.mjs
git commit -m "fix: keep schedule requests out of project task proposals"
```

### Task 3: 일반 내부 Chat의 자동 전환과 Agent 선택 UI

**Files:**
- Modify: `main_agent/frontend/src/App.tsx:29, 235-255, 421-507, 509-513`
- Test: `main_agent/frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: reply JSON `{ answer?, agent?, target_chat?, status?, agent_options?, pending_action? }`.
- Produces: `AgentSelectionMessage` ChatMessage와 `handoffAgentChat(targetChat, sourceChat, request)` UI 전환 함수.

- [ ] **Step 1: 실패하는 UI 테스트를 추가한다**

```tsx
it("switches from Game Q&A to Workmate when the reply names Workmate as the target chat", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.includes("/api/chats/Game%20Q%26A/reply")) {
      return Promise.resolve({ ok: true, json: async () => ({
        answer: "회의 시간을 알려주세요.", agent: "workmate-agent", target_chat: "Workmate AI", status: "succeeded",
      }) });
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  }));
  render(<App />);
  await userEvent.click(screen.getByText("Game Q&A"));
  await userEvent.type(screen.getByPlaceholderText("Type /? for Game Q&A commands..."), "다음 주 회의 일정 잡아줘");
  await userEvent.click(screen.getByRole("button", { name: "➤" }));
  expect(await screen.findByText(/AI Chat · Workmate AI/)).toBeInTheDocument();
  expect(screen.getByText(/Game Q&A에서 전달됨/)).toBeInTheDocument();
});

it("shows agent choices and does not switch until the user selects one", async () => {
  // reply status is needs_agent_selection with four agent_options
  // verify the selection buttons are visible and no specialist reply endpoint was called
});
```

- [ ] **Step 2: 테스트가 현재 실패함을 확인한다**

Run: `npx vitest run src/App.test.tsx`

Expected: FAIL because reply data has no target Chat handling or agent selection card.

- [ ] **Step 3: 자동 전환과 선택 카드를 구현한다**

```typescript
type AgentSelectionMessage = {
  id: string;
  kind: "agent-selection";
  sourceChat: string;
  request: string;
  options: string[];
  state: "pending" | "selecting" | "error";
};

function handoffAgentChat(targetChat: string, sourceChat: string, request: string) {
  activeChatRef.current = targetChat;
  setActiveSection("Home");
  setActiveChat(targetChat);
  persistMessage("user", `[${sourceChat}에서 전달됨] ${request}`, undefined, targetChat);
}
```

`needs_agent_selection` 응답은 선택 카드만 추가한다. 선택 버튼은 원래 요청과 `selected_agent`를 같은 Chat reply API에 재전송한다. 성공 응답의 `target_chat`이 원래 Chat과 다르면 대상 Chat으로 전환하고, 대상 Chat 이력에 전달 출처를 저장한다. 명시적 Game Q&A Story Review의 기존 화면 이동은 변경하지 않는다.

- [ ] **Step 4: 프론트엔드 단위 테스트와 빌드를 통과시킨다**

Run: `npx vitest run src/App.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add main_agent/frontend/src/App.tsx main_agent/frontend/src/App.test.tsx
git commit -m "feat: switch chats after agent handoff"
```

### Task 4: Video Generation 내부 입력에서 공통 라우팅을 거친다

**Files:**
- Modify: `main_agent/frontend/src/video-agent/VideoAgentPage.tsx:27-79`
- Modify: `main_agent/frontend/src/App.tsx:526`
- Test: `main_agent/frontend/src/App.test.tsx:50-90`

**Interfaces:**
- Consumes: `VideoAgentPage.onRouteAway?: (targetChat: string, request: string) => void`.
- Produces: Video ChatComposer 입력의 공통 Chat reply 라우팅 및 대상 Agent 전환 콜백.

- [ ] **Step 1: 실패하는 Video UI 테스트를 수정·추가한다**

```tsx
it("moves Video Generation to Development Assistant for a development request", async () => {
  // mock /api/chats/Video%20Generation/reply with target_chat: "Development Assistant"
  render(<App />);
  await userEvent.click(screen.getByText("Video Generation"));
  await userEvent.type(screen.getByPlaceholderText("Type a message..."), "코드 버그 확인해줘");
  await userEvent.click(screen.getByRole("button", { name: "전송" }));
  expect(await screen.findByText(/AI Chat · Development Assistant/)).toBeInTheDocument();
});
```

Replace the existing tests that assert Video Generation must remain open for development/story requests; those assertions contradict the approved routing contract.

- [ ] **Step 2: 테스트가 현재 실패함을 확인한다**

Run: `npx vitest run src/App.test.tsx`

Expected: FAIL because `VideoAgentPage` directly starts a video task for every ChatComposer message.

- [ ] **Step 3: Video ChatComposer를 공통 라우팅 경계에 연결한다**

```typescript
export function VideoAgentPage({ initialBrief, owner, onRouteAway }: {
  initialBrief?: string;
  owner?: string;
  onRouteAway?: (targetChat: string, request: string) => void;
} = {}) {
  async function handleSubmit(message: string) {
    const routed = await routeInternalChat("Video Generation", message, owner);
    if (routed.target_chat !== "Video Generation") {
      onRouteAway?.(routed.target_chat, message);
      return;
    }
    // Existing createVideoAgentTask(message, owner) flow remains unchanged.
  }
}
```

Main `App`은 `onRouteAway`에서 Task 3의 동일한 전환·이력 저장 함수를 전달한다. 대상이 Video Generation일 때만 기존 비디오 Task 생성 경로를 실행한다. 모호한 응답은 Video 화면에서 선택 카드를 표시할 수 있도록 App의 공통 선택 상태로 올린다.

- [ ] **Step 4: Video 전환 회귀 테스트와 빌드를 통과시킨다**

Run: `npx vitest run src/App.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add main_agent/frontend/src/video-agent/VideoAgentPage.tsx main_agent/frontend/src/App.tsx main_agent/frontend/src/App.test.tsx
git commit -m "feat: route video chat requests to specialist agents"
```

### Task 5: 통합 검증 및 전문 Agent 비변경 확인

**Files:**
- Test: `main_agent/backend/tests/test_api.py`
- Test: `main_agent/frontend/src/App.test.tsx`
- Test: `main_agent/frontend/scripts/task-utils-test.mjs`

**Interfaces:**
- Consumes: Tasks 1-4의 라우팅·전환·Task 의도 계약.
- Produces: 검증된 Main Agent 기능과 전문 Agent 비변경 Git diff.

- [ ] **Step 1: 백엔드 전체 테스트를 실행한다**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 2: 프론트엔드 관련 테스트와 빌드를 실행한다**

Run: `npm run test:task && npx vitest run src/App.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 3: 전문 Agent 경로가 변경되지 않았는지 확인한다**

Run: `git diff --name-only HEAD~4..HEAD`

Expected: 출력에 `workmate-agent/`, `video_agent/`, `dev_agent/`, `qna_agent/` 경로가 없음.

- [ ] **Step 4: 최종 변경을 검토하고 커밋한다**

```bash
git status --short
git diff --check
git add main_agent
git commit -m "test: verify cross-agent chat handoff"
```
