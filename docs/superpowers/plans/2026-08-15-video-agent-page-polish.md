# Video-agent 페이지 시각적 정합성 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** video-agent 페이지의 제목, 패널 크기, 라우팅 챗봇을 다른 세 Agent(Workmate AI, Game Q&A, Development Assistant)와 동일한 시각적 관례로 맞춘다.

**Architecture:** 새 컴포넌트나 새 CSS 클래스를 만들지 않는다. 기존에 다른 Agent들이 이미 쓰고 있는 전역 클래스(`.eyebrow`, `.title-row`, `.chat-panel`/`.reset-chat` 패턴)를 그대로 재사용하고, `styles.css`의 기존 `Video Generation` 전용 셀렉터 규칙에 선언을 추가하는 방식으로 진행한다.

**Tech Stack:** React + TypeScript, Tailwind CSS(video-agent 서브트리, Preflight 비활성 상태로 전역 번들에 포함됨), Vitest + Testing Library.

## Global Constraints

- 오늘 브리핑에서 쓰이는 기본 `MainBriefingChatbot`(contextHint 없음)의 문구·헤더·크기·동작은 절대 변경하지 않는다 — `contextHint`가 있을 때만 새 동작이 적용된다.
- `ChatComposer.tsx`/`FormComposer.tsx`의 브리프 작성 필드, placeholder($5/30초 안내 포함)는 변경하지 않는다.
- `TaskCanvas.tsx`의 상태별 렌더링 로직은 변경하지 않는다 — 컨테이너 크기만 바뀐다.
- video-agent 백엔드/A2A 로직은 변경하지 않는다.
- 라우팅 챗봇의 `Reset chat`은 로컬 `messages` state만 초기화한다 — 백엔드 호출 없음.
- 새로 추가되는 범용 UI 문구(헤더, placeholder)는 영어, 이 페이지에서만 의미 있는 안내문(contextHint 자체)은 한국어 유지.

---

### Task 1: 페이지 타이틀 추가 + 패널 크기 정상화

**Files:**
- Modify: `frontend/src/video-agent/VideoAgentPage.tsx`
- Modify: `frontend/src/styles.css:45`
- Test: `frontend/src/video-agent/VideoAgentPage.test.tsx`

**Interfaces:**
- Consumes: 전역 CSS 클래스 `.title-row`, `.eyebrow`(둘 다 `frontend/src/styles.css:1`에 이미 정의됨, 이 태스크에서 새로 만들지 않음).
- Produces: 없음 (마크업/스타일 변경만, 새 export 없음). Task 2와 파일이 겹치지 않으므로 순서 무관하게 독립 실행 가능.

- [ ] **Step 1: 실패하는 테스트 작성 — 페이지 타이틀 + 패널 최소 높이**

`frontend/src/video-agent/VideoAgentPage.test.tsx`의 `describe("VideoAgentPage", ...)` 블록 안, 기존 테스트들 뒤에 추가:

```tsx
  it("shows the Main Agent page title above the two-panel layout", () => {
    render(<VideoAgentPage />);
    expect(screen.getByText("MAIN AGENT / VIDEO GENERATION")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "영상 생성" })).toBeInTheDocument();
  });

  it("does not stretch the two-panel layout to the full viewport height", () => {
    const { container } = render(<VideoAgentPage />);
    const grid = container.querySelector(".grid");
    expect(grid).not.toHaveClass("h-full");
    expect(container.querySelector("aside")).toHaveClass("min-h-[520px]");
    expect(container.querySelector("main")).toHaveClass("min-h-[520px]");
  });
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/video-agent/VideoAgentPage.test.tsx`
Expected: 새로 추가한 2개 테스트 FAIL (`"MAIN AGENT / VIDEO GENERATION"` 텍스트 없음, `h-full` 클래스가 존재함).

- [ ] **Step 3: `VideoAgentPage.tsx` 수정 — 타이틀 블록 추가, `h-full` 제거, `min-h-[520px]` 추가**

`frontend/src/video-agent/VideoAgentPage.tsx`의 `return (...)` 블록을 다음으로 교체 (기존 `<h1 className="text-lg font-semibold text-brief-text">영상 생성</h1>`는 페이지 레벨 타이틀과 중복되므로 제거):

```tsx
  return (
    <>
      <div className="title-row">
        <div>
          <p className="eyebrow">MAIN AGENT / VIDEO GENERATION</p>
          <h1>영상 생성</h1>
        </div>
      </div>
      <div className="grid grid-cols-[minmax(280px,360px)_1fr] gap-4 bg-brief-bg">
        <aside className="flex min-h-[520px] flex-col gap-3 rounded-[15px] border border-brief-border bg-white p-4">
          <ComposerTabs
            chat={<ChatComposer disabled={isBusy || submitting} onSubmit={handleSubmit} initialValue={initialBrief} />}
            form={<FormComposer disabled={isBusy || submitting} onSubmit={handleSubmit} />}
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
            <button
              type="button"
              onClick={handleCancel}
              className="rounded-[8px] border border-brief-border px-3 py-2 text-sm text-brief-text"
            >
              취소
            </button>
          )}
        </aside>
        <main className="min-h-[520px] rounded-[15px] border border-brief-border bg-white p-4">
          <TaskCanvas task={task} unresolvedScenes={unresolvedScenes} onUploadScene={handleUploadScene} onRetry={handleRetry} />
        </main>
      </div>
    </>
  );
```

- [ ] **Step 4: `styles.css`에 `.video-agent-host` 패딩 추가**

`frontend/src/styles.css:45`의 기존 규칙:
```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2;grid-row:1}
```
다음으로 교체 (`padding` 추가, 나머지 동일):
```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2;grid-row:1;padding:45px 32px}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd frontend && npx vitest run src/video-agent/VideoAgentPage.test.tsx`
Expected: 전체 PASS (기존 6개 + 신규 2개 = 8개).

- [ ] **Step 6: 빌드 및 CSS 반영 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공. 이어서 아래 명령으로 생성된 CSS에 padding 선언이 실제로 포함됐는지 확인:
Run (PowerShell): `Select-String -Path frontend/dist/assets/*.css -Pattern 'data-active-chat="Video Generation"\] \.video-agent-host\{grid-column:2;grid-row:1;padding:45px 32px' -Quiet`
Expected: `True`

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/video-agent/VideoAgentPage.tsx frontend/src/styles.css frontend/src/video-agent/VideoAgentPage.test.tsx
git commit -m "feat: add page title and fix oversized panels on video-agent page"
```

---

### Task 2: 라우팅 챗봇 — 크기/타이틀/Reset 버튼 + 영어 placeholder

**Files:**
- Modify: `frontend/src/MainUiPanels.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.test.tsx:46,55,69` (기존 3개 테스트가 참조하는 옛 한국어 placeholder를 새 영어 placeholder로 갱신)
- Test: `frontend/src/MainUiPanels.test.tsx`

**Interfaces:**
- Consumes: `MainBriefingChatbot({ contextHint }: { contextHint?: string })` — 기존 시그니처 그대로, 새 파라미터 없음. 전역 CSS 클래스 `.reset-chat`(`frontend/src/chat-answer.css:16`에 이미 정의됨).
- Produces: 없음. Task 1과 파일이 겹치지 않으므로 독립 실행 가능.

- [ ] **Step 1: 실패하는 테스트 작성 — 헤더/Reset/placeholder**

`frontend/src/MainUiPanels.test.tsx`를 다음으로 교체 (기존 테스트 2개 중 placeholder 값을 새 영어 문구로 갱신하고, 헤더/Reset 테스트 3개 추가):

```tsx
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MainBriefingChatbot } from "./MainUiPanels";

describe("MainBriefingChatbot", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the default empty-state text, placeholder, and header when no contextHint is given", () => {
    render(<MainBriefingChatbot />);
    expect(screen.getByText("간단한 질문이나 업무 내용을 입력하세요.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("무엇을 도와드릴까요?")).toBeInTheDocument();
    expect(screen.getByText("Main Chatbot")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset chat" })).not.toBeInTheDocument();
  });

  it("shows the contextHint as the empty-state text and an English placeholder when provided", () => {
    render(
      <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />,
    );
    expect(
      screen.getByText("다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요."),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Type a message...")).toBeInTheDocument();
  });

  it("shows the AI Chat · Video Generation header and Reset chat button when contextHint is given", () => {
    render(<MainBriefingChatbot contextHint="영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />);
    expect(screen.getByText("AI Chat · Video Generation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset chat" })).toBeInTheDocument();
  });

  it("Reset chat clears the local conversation without any network calls", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<MainBriefingChatbot contextHint="영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />);

    await userEvent.type(screen.getByPlaceholderText("Type a message..."), "영상 관련 질문");
    await userEvent.click(screen.getByRole("button", { name: "➤" }));
    expect(screen.getByText("영상 관련 질문")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reset chat" }));

    expect(screen.queryByText("영상 관련 질문")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/MainUiPanels.test.tsx`
Expected: 신규/갱신된 테스트들 FAIL (헤더 텍스트 없음, placeholder가 아직 한국어, Reset 버튼 없음).

- [ ] **Step 3: `MainUiPanels.tsx`의 `MainBriefingChatbot` 수정**

`frontend/src/MainUiPanels.tsx`의 `MainBriefingChatbot` 함수(현재 36-64번째 줄) 중 `return` 문을 다음으로 교체:

```tsx
  return (
    <section className="briefing-chatbot">
      {contextHint ? (
        <h3>
          AI Chat · Video Generation
          <button className="reset-chat" type="button" onClick={() => setMessages([])}>
            Reset chat
          </button>
        </h3>
      ) : (
        <h3>
          Main Chatbot <span>업무 라우터</span>
        </h3>
      )}
      <div className="briefing-chat-messages">
        {messages.length === 0 && <p className="briefing-chat-empty">{contextHint ?? "간단한 질문이나 업무 내용을 입력하세요."}</p>}
        {messages.map((item, index) => (
          <p className={item.role === "user" ? "briefing-chat-user" : "briefing-chat-answer"} key={`${item.role}-${index}`}>
            {item.text}
          </p>
        ))}
        {busy && <p className="briefing-chat-answer">답변을 준비 중입니다…</p>}
      </div>
      <form className="briefing-chat-composer" onSubmit={submit}>
        <input
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder={contextHint ? "Type a message..." : "무엇을 도와드릴까요?"}
        />
        <button type="submit">➤</button>
      </form>
    </section>
  );
```

- [ ] **Step 4: `styles.css`에 Video Generation 전용 `.briefing-chatbot` 크기/위치 오버라이드 추가**

`frontend/src/styles.css:45`(Task 1에서 이미 padding을 추가한 바로 그 줄) 끝에 이어서 새 규칙 추가:

```css
.agent-content-updated[data-active-chat="Video Generation"] .briefing-chatbot{position:static;grid-column:3;grid-row:1;width:auto;height:calc(100vh - 120px);margin:90px 32px 32px 0}
```

- [ ] **Step 5: `App.test.tsx`의 옛 한국어 placeholder 참조 갱신**

`frontend/src/App.test.tsx`에서 `"다른 업무나 질문을 입력하세요"` 문자열이 나오는 3곳(46번째 줄 근처의 `findByPlaceholderText`, 55번째 줄 근처와 69번째 줄 근처의 `getByPlaceholderText`)을 모두 `"Type a message..."`로 교체. 예:

```tsx
    expect(await screen.findByPlaceholderText("다른 업무나 질문을 입력하세요")).toBeInTheDocument();
```
→
```tsx
    expect(await screen.findByPlaceholderText("Type a message...")).toBeInTheDocument();
```

나머지 2곳(`const chatbotInput = screen.getByPlaceholderText("다른 업무나 질문을 입력하세요");`)도 동일하게 `"Type a message..."`로 교체.

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd frontend && npx vitest run src/MainUiPanels.test.tsx src/App.test.tsx`
Expected: 전체 PASS.

- [ ] **Step 7: 빌드 및 CSS 반영 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공. 이어서:
Run (PowerShell): `Select-String -Path frontend/dist/assets/*.css -Pattern 'data-active-chat="Video Generation"\] \.briefing-chatbot\{position:static;grid-column:3' -Quiet`
Expected: `True`

- [ ] **Step 8: 전체 프론트엔드 테스트 스위트 통과 확인**

Run: `cd frontend && npx vitest run`
Expected: 전체 PASS, 회귀 없음.

- [ ] **Step 9: 커밋**

```bash
git add frontend/src/MainUiPanels.tsx frontend/src/styles.css frontend/src/MainUiPanels.test.tsx frontend/src/App.test.tsx
git commit -m "feat: match routing chatbot size, header, and reset button to other agents"
```
