# Video-agent 라우팅 챗봇 및 브리프 안내 문구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Main Agent's existing routing chatbot to the video-agent page (scoped with a context-specific hint) and improve the video brief composer's placeholder to state the real server limits.

**Architecture:** Reuse `MainBriefingChatbot` as-is via a new optional `contextHint` prop rather than building anything new; extend `UpdatedReportNav`'s existing render-condition pattern with one more case; narrow the CSS grid column the video-agent page occupies so the chatbot's fixed overlay doesn't cover it.

**Tech Stack:** React, TypeScript (strict), Vitest + React Testing Library — all already in place.

## Global Constraints

- No changes to `VideoAgentPage.tsx`'s own logic/props, or to `MainBriefingChatbot`'s existing behavior when `contextHint` is not passed (오늘 브리핑 usage stays byte-identical).
- No backend changes — video-agent's real limits (`duration_sec` ≤ 30, `SERVER_MAX_BUDGET_USD` = 5.00) are stated in UI copy as-is, not changed.
- TypeScript `strict: true`.

---

## File Structure

- `frontend/src/MainUiPanels.tsx` — MODIFY (`MainBriefingChatbot` gains `contextHint?: string`; `UpdatedReportNav` gains a second render condition).
- `frontend/src/MainUiPanels.test.tsx` — CREATE (no test file exists for this module today).
- `frontend/src/styles.css` — MODIFY (`.video-agent-host` grid-column narrowed).
- `frontend/src/App.test.tsx` — MODIFY (one new integration test case, existing `describe` block).
- `frontend/src/video-agent/ChatComposer.tsx` — MODIFY (placeholder copy only).
- `frontend/src/video-agent/ChatComposer.test.tsx` — MODIFY (one new test case).

---

### Task 1: `MainBriefingChatbot` gains a `contextHint` prop

**Files:**
- Modify: `frontend/src/MainUiPanels.tsx`
- Create: `frontend/src/MainUiPanels.test.tsx`

**Interfaces:**
- Produces: `MainBriefingChatbot({ contextHint }: { contextHint?: string } = {})` — when `contextHint` is omitted, behavior is unchanged from today; when provided, it replaces both the empty-state message and the input placeholder. Consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/MainUiPanels.test.tsx
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MainBriefingChatbot } from "./MainUiPanels";

describe("MainBriefingChatbot", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the default empty-state text and placeholder when no contextHint is given", () => {
    render(<MainBriefingChatbot />);
    expect(screen.getByText("간단한 질문이나 업무 내용을 입력하세요.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("무엇을 도와드릴까요?")).toBeInTheDocument();
  });

  it("shows the contextHint as the empty-state text and a scoped placeholder when provided", () => {
    render(
      <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />,
    );
    expect(
      screen.getByText("다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요."),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("다른 업무나 질문을 입력하세요")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test:video-agent -- MainUiPanels`
Expected: FAIL — `MainBriefingChatbot` doesn't accept/apply a `contextHint` prop yet (second test fails; first test may pass by coincidence since the default text already matches, but confirm both are exercised).

- [ ] **Step 3: Update `MainBriefingChatbot`**

Find this in `frontend/src/MainUiPanels.tsx` (the exact current function, lines 36-63):

```tsx
export function MainBriefingChatbot() {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    const request = message.trim();
    if (!request || busy) return;
    setMessage("");
    setMessages((items) => [...items, { role: "user", text: request }]);
    const target = routeMainRequest(request);
    if (target) {
      setMessages((items) => [...items, { role: "assistant", text: `${target}로 연결합니다.` }]);
      window.dispatchEvent(new CustomEvent("main-chat-route", { detail: { chat: target, message: request } }));
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("http://127.0.0.1:8000/api/chats/Main Chatbot/reply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: request }) });
      const data = response.ok ? await response.json() as { answer?: string } : {};
      setMessages((items) => [...items, { role: "assistant", text: data.answer ?? "질문을 확인했습니다. 업무와 관련된 내용이면 담당 Agent로 연결해 드립니다." }]);
    } catch {
      setMessages((items) => [...items, { role: "assistant", text: "질문을 확인했습니다. 업무와 관련된 내용이면 담당 Agent로 연결해 드립니다." }]);
    } finally { setBusy(false); }
  }

  return <section className="briefing-chatbot"><h3>Main Chatbot <span>업무 라우터</span></h3><div className="briefing-chat-messages">{messages.length === 0 && <p className="briefing-chat-empty">간단한 질문이나 업무 내용을 입력하세요.</p>}{messages.map((item, index) => <p className={item.role === "user" ? "briefing-chat-user" : "briefing-chat-answer"} key={`${item.role}-${index}`}>{item.text}</p>)}{busy && <p className="briefing-chat-answer">답변을 준비 중입니다…</p>}</div><form className="briefing-chat-composer" onSubmit={submit}><input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="무엇을 도와드릴까요?" /><button type="submit">➤</button></form></section>;
}
```

Replace with:

```tsx
export function MainBriefingChatbot({ contextHint }: { contextHint?: string } = {}) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    const request = message.trim();
    if (!request || busy) return;
    setMessage("");
    setMessages((items) => [...items, { role: "user", text: request }]);
    const target = routeMainRequest(request);
    if (target) {
      setMessages((items) => [...items, { role: "assistant", text: `${target}로 연결합니다.` }]);
      window.dispatchEvent(new CustomEvent("main-chat-route", { detail: { chat: target, message: request } }));
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("http://127.0.0.1:8000/api/chats/Main Chatbot/reply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: request }) });
      const data = response.ok ? await response.json() as { answer?: string } : {};
      setMessages((items) => [...items, { role: "assistant", text: data.answer ?? "질문을 확인했습니다. 업무와 관련된 내용이면 담당 Agent로 연결해 드립니다." }]);
    } catch {
      setMessages((items) => [...items, { role: "assistant", text: "질문을 확인했습니다. 업무와 관련된 내용이면 담당 Agent로 연결해 드립니다." }]);
    } finally { setBusy(false); }
  }

  return <section className="briefing-chatbot"><h3>Main Chatbot <span>업무 라우터</span></h3><div className="briefing-chat-messages">{messages.length === 0 && <p className="briefing-chat-empty">{contextHint ?? "간단한 질문이나 업무 내용을 입력하세요."}</p>}{messages.map((item, index) => <p className={item.role === "user" ? "briefing-chat-user" : "briefing-chat-answer"} key={`${item.role}-${index}`}>{item.text}</p>)}{busy && <p className="briefing-chat-answer">답변을 준비 중입니다…</p>}</div><form className="briefing-chat-composer" onSubmit={submit}><input value={message} onChange={(event) => setMessage(event.target.value)} placeholder={contextHint ? "다른 업무나 질문을 입력하세요" : "무엇을 도와드릴까요?"} /><button type="submit">➤</button></form></section>;
}
```

(Only the function signature and the two lines inside the returned JSX that read `contextHint` changed — `submit`'s body, `routeMainRequest` usage, and the `main-chat-route` event dispatch are untouched.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent -- MainUiPanels`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/MainUiPanels.tsx frontend/src/MainUiPanels.test.tsx
git commit -m "feat: add contextHint prop to MainBriefingChatbot"
```

---

### Task 2: Render the chatbot for Video Generation, narrow its grid column

**Files:**
- Modify: `frontend/src/MainUiPanels.tsx`, `frontend/src/styles.css`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `MainBriefingChatbot`'s `contextHint` prop (Task 1).
- Produces: `activeChat === "Video Generation"` renders `MainBriefingChatbot` with a scoped hint, and `.video-agent-host` leaves grid column 3 free so the chatbot's fixed overlay doesn't cover the canvas.

- [ ] **Step 1: Write the failing test**

Add this test case inside the existing `describe("App - Video Generation sidebar entry", ...)` block in `frontend/src/App.test.tsx` (the file already has a `beforeEach` stubbing `fetch` and an `afterEach` cleaning up — this test goes alongside the two existing `it(...)` blocks, no new imports needed):

```tsx
  it("shows the scoped routing chatbot instead of the default one when Video Generation is selected", async () => {
    render(<App />);

    await userEvent.click(screen.getByText("Video Generation"));

    expect(await screen.findByPlaceholderText("다른 업무나 질문을 입력하세요")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("무엇을 도와드릴까요?")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:video-agent -- App.test`
Expected: FAIL — `UpdatedReportNav` doesn't render `MainBriefingChatbot` for this chat yet.

- [ ] **Step 3: Update `UpdatedReportNav`**

Find this in `frontend/src/MainUiPanels.tsx` (the exact current function):

```tsx
export function UpdatedReportNav({ variant, activeSection, activeChat, onSelect }: { variant: UiVariant; activeSection: string; activeChat: string | null; onSelect: (section: string) => void }) {
  return <>{variant === "updated" && <div className="updated-report-nav" aria-label="업무 보고 메뉴"><button className={activeSection === "Today Briefing" ? "active" : ""} type="button" onClick={() => onSelect("Today Briefing")}>◇ 오늘 브리핑</button><button className={activeSection === "Weekly Report" ? "active" : ""} type="button" onClick={() => onSelect("Weekly Report")}>◇ 주간 업무 보고</button></div>}{activeSection === "Today Briefing" && !activeChat && <MainBriefingChatbot />}</>;
}
```

Replace with:

```tsx
export function UpdatedReportNav({ variant, activeSection, activeChat, onSelect }: { variant: UiVariant; activeSection: string; activeChat: string | null; onSelect: (section: string) => void }) {
  return <>{variant === "updated" && <div className="updated-report-nav" aria-label="업무 보고 메뉴"><button className={activeSection === "Today Briefing" ? "active" : ""} type="button" onClick={() => onSelect("Today Briefing")}>◇ 오늘 브리핑</button><button className={activeSection === "Weekly Report" ? "active" : ""} type="button" onClick={() => onSelect("Weekly Report")}>◇ 주간 업무 보고</button></div>}{activeSection === "Today Briefing" && !activeChat && <MainBriefingChatbot />}{activeChat === "Video Generation" && <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />}</>;
}
```

- [ ] **Step 4: Narrow `.video-agent-host`'s grid column**

Find this in `frontend/src/styles.css`:

```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2 / 4;grid-row:1}
```

Replace with:

```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2;grid-row:1}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test:video-agent -- App.test`
Expected: PASS (3 tests in this file — the 2 pre-existing plus the new one)

- [ ] **Step 6: Run the full video-agent suite to confirm nothing broke**

Run: `cd frontend && npm run test:video-agent`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/MainUiPanels.tsx frontend/src/styles.css frontend/src/App.test.tsx
git commit -m "feat: show the routing chatbot on the video-agent page, narrow its grid column"
```

---

### Task 3: Improve `ChatComposer`'s placeholder copy

**Files:**
- Modify: `frontend/src/video-agent/ChatComposer.tsx`, `frontend/src/video-agent/ChatComposer.test.tsx`

**Interfaces:**
- No prop/behavior changes — copy only. Existing consumers (`VideoAgentPage.tsx`) are unaffected.

- [ ] **Step 1: Write the failing test**

Add this test case to the existing `describe("ChatComposer", ...)` block in `frontend/src/video-agent/ChatComposer.test.tsx` (no new imports needed):

```tsx
  it("states the real duration and budget limits in the placeholder", () => {
    render(<ChatComposer disabled={false} onSubmit={vi.fn()} />);
    expect(
      screen.getByPlaceholderText(
        "무엇을 홍보할지 구체적으로 적어주세요 (캐릭터/이벤트/게임 장면 등, 30초 이하, 예산 $5 이하). 예: 할로윈 신규 캐릭터 '루멘' 공개 이벤트, 15초로",
      ),
    ).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:video-agent -- ChatComposer`
Expected: FAIL — current placeholder is `"예: 할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"`.

- [ ] **Step 3: Update the placeholder**

In `frontend/src/video-agent/ChatComposer.tsx`, find:

```tsx
        placeholder="예: 할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"
```

Replace with:

```tsx
        placeholder="무엇을 홍보할지 구체적으로 적어주세요 (캐릭터/이벤트/게임 장면 등, 30초 이하, 예산 $5 이하). 예: 할로윈 신규 캐릭터 '루멘' 공개 이벤트, 15초로"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test:video-agent -- ChatComposer`
Expected: PASS (4 tests in this file — the 3 pre-existing plus the new one)

- [ ] **Step 5: Run the full video-agent suite and build for regressions**

Run: `cd frontend && npm run test:video-agent`
Expected: all PASS

Run: `cd frontend && npm run build`
Expected: succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/video-agent/ChatComposer.tsx frontend/src/video-agent/ChatComposer.test.tsx
git commit -m "feat: state real duration/budget limits in the brief composer placeholder"
```

---

## Self-Review Notes

- **Spec coverage:** `contextHint` prop + reuse of `MainBriefingChatbot` (Task 1), `UpdatedReportNav`'s new render condition + grid narrowing (Task 2), placeholder copy with real $5/30s limits (Task 3) — every spec section has a task. The spec's non-goals (no backend changes, no `MainBriefingChatbot` restyle, no `VideoAgentPage` logic changes, no `FormComposer` changes) are respected — none of the three tasks touch those.
- **Placeholder scan:** no TODO/TBD; every step has literal code, exact find/replace text, or an exact runnable command.
- **Type consistency:** `contextHint?: string` is used identically in Task 1's definition and Task 2's two call sites (the existing no-arg call stays unchanged, the new call passes the literal hint string) — no signature drift.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-14-video-agent-routing-chatbot.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
