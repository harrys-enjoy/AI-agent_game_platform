# Video-agent 페이지 사이드바 통합 및 리스킨 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the standalone video-agent page into MAIN's single React app (reachable via the existing "Video Generation" sidebar entry) and restyle it to match the "오늘 브리핑" panel's sage-green visual language.

**Architecture:** Drop the second Vite entry; import the video-agent page's Tailwind stylesheet from a component reachable by the single `main.tsx` bundle instead. Wire `App.tsx` to conditionally render `VideoAgentPage` (and skip rendering the generic chat panel) when `activeChat === "Video Generation"`, mirroring the existing `activeSection === "Today Briefing"` short-circuit pattern already used for `ReferenceBriefingPanel`. Reskin the existing components' Tailwind classNames only — no logic/prop changes.

**Tech Stack:** React, TypeScript (strict), Tailwind CSS, Vite, Vitest + React Testing Library — all already in place from the original video-agent build.

## Global Constraints

- No behavior/logic changes to composer submission, polling, error handling, or manual-fix upload — this plan is routing integration + visual restyle only.
- No backend changes.
- `frontend/src/App.tsx` and `frontend/src/styles.css` may be edited (unlike the original video-agent-frontend plan, which explicitly excluded them) — this plan's whole point is integrating into them.
- Existing `frontend/src/video-agent/*.test.tsx` files must all still pass unmodified after the restyle (Task 3) — they assert on `data-testid`/`aria-label`/text content, never on className, so a pure className change must not require touching them.
- TypeScript `strict: true` — new/changed code must type-check under it.

---

## File Structure

- `frontend/video-agent.html`, `frontend/src/video-agent-main.tsx` — DELETE (standalone entry, superseded by sidebar integration).
- `frontend/vite.config.ts` — MODIFY (drop the second build entry, broaden Vitest's `test.include`).
- `frontend/tailwind.config.js` — MODIFY (drop `video-agent.html` from `content`, disable Preflight, add sage-green color tokens).
- `frontend/src/video-agent/VideoAgentPage.tsx` — MODIFY (import its own stylesheet directly; restyle in Task 3).
- `frontend/src/App.tsx` — MODIFY (render `VideoAgentPage` for the "Video Generation" chat, skip two side effects for that chat name).
- `frontend/src/styles.css` — MODIFY (one new grid-column rule for the video-agent host).
- `frontend/src/App.test.tsx` — CREATE (new — no App-level test exists today).
- `frontend/src/video-agent/StatusBadge.tsx`, `ComposerTabs.tsx`, `ChatComposer.tsx`, `FormComposer.tsx`, `TaskCanvas.tsx` — MODIFY (className-only restyle, Task 3).

---

### Task 1: Remove the standalone entry, prep Tailwind for the merged bundle

**Files:**
- Delete: `frontend/video-agent.html`, `frontend/src/video-agent-main.tsx`
- Modify: `frontend/vite.config.ts`, `frontend/tailwind.config.js`, `frontend/src/video-agent/VideoAgentPage.tsx`

**Interfaces:**
- Produces: a single-entry Vite build (`dist/index.html` only) with Tailwind's sage-green tokens (`brief-bg`, `brief-accent`, `brief-accent-dark`, `brief-border`, `brief-text`, `brief-muted`) available to any component in `src/video-agent/**`. Consumed by Task 2 (App.tsx wiring) and Task 3 (restyle).

- [ ] **Step 1: Delete the standalone entry files**

Run: `cd frontend && rm video-agent.html src/video-agent-main.tsx`

- [ ] **Step 2: Update `vite.config.ts`**

```ts
// frontend/vite.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/video-agent/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

(Drops the `build.rollupOptions.input` override entirely — Vite defaults to `index.html` as the single entry. Broadens `test.include` from `src/video-agent/**/*.test.{ts,tsx}` to `src/**/*.test.{ts,tsx}` so Task 2's new `src/App.test.tsx` gets picked up too — no other test files exist outside `src/video-agent/` today, so this is safe.)

- [ ] **Step 3: Update `tailwind.config.js`**

```js
// frontend/tailwind.config.js
export default {
  content: ["./src/video-agent/**/*.{ts,tsx}"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        "brief-bg": "#f7f9f6",
        "brief-accent": "#397454",
        "brief-accent-dark": "#2f624b",
        "brief-border": "#dfe7e1",
        "brief-text": "#19352c",
        "brief-muted": "#75867f",
      },
    },
  },
  plugins: [],
};
```

(`content` drops the now-deleted `video-agent.html`. `corePlugins.preflight: false` stops Tailwind's global CSS reset from touching the legacy plain-CSS app now that both share one bundle — the utility classes this page uses don't depend on Preflight.)

- [ ] **Step 4: Import the stylesheet from `VideoAgentPage.tsx`**

Add as the first import line (the file currently starts with a `// frontend/src/video-agent/VideoAgentPage.tsx` comment then `import { useEffect, useState } from "react";`):

```tsx
import "./styles.css";
import { useEffect, useState } from "react";
```

(Vite bundles CSS imports into the chunk regardless of which component imports them — since `VideoAgentPage` will be imported by `App.tsx` → `main.tsx` in Task 2, this makes Tailwind's output part of the single bundle without needing a second HTML entry.)

- [ ] **Step 5: Verify the build**

Run: `cd frontend && npm run build`
Expected: succeeds; `dist/index.html` is produced, `dist/video-agent.html` is NOT produced (confirm with `ls dist/`).

- [ ] **Step 6: Commit**

```bash
git add -u frontend/video-agent.html frontend/src/video-agent-main.tsx
git add frontend/vite.config.ts frontend/tailwind.config.js frontend/src/video-agent/VideoAgentPage.tsx
git commit -m "chore: fold video-agent's Tailwind build into the single-entry bundle"
```

---

### Task 2: Wire `App.tsx` to render VideoAgentPage for the "Video Generation" chat

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/styles.css`
- Create: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `VideoAgentPage` (from Task 1, `./video-agent/VideoAgentPage`).
- Produces: clicking the existing "Video Generation" sidebar entry renders `VideoAgentPage` in place of the generic chat panel; the generic chat panel and task-table workspace are not rendered at all while that chat is active.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/App.test.tsx
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App - Video Generation sidebar entry", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders VideoAgentPage instead of the generic chat panel when Video Generation is selected", async () => {
    render(<App />);

    await userEvent.click(screen.getByText("Video Generation"));

    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Type a message...")).not.toBeInTheDocument();
  });
});
```

(`readUiVariant` defaults to `"legacy"` when `localStorage` is empty, which jsdom's test environment always is — the legacy sidebar renders "Video Generation" as a single nested-link button under the "Works" toggle, which starts expanded (`worksOpen` initial state is `true`), so `getByText("Video Generation")` finds exactly that one button. The task table's `{task.agent} ↗` text is "Video Generation ↗" — a different string — so it doesn't collide.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:video-agent`
Expected: `App.test.tsx` FAILS — clicking "Video Generation" currently shows the generic chat panel, not a "영상 브리프" label.

- [ ] **Step 3: Add the `VideoAgentPage` import**

Find this line near the top of `App.tsx`:

```tsx
import { AssigneeSwitcher } from "./AssigneeSwitcher";
```

Add directly after it:

```tsx
import { AssigneeSwitcher } from "./AssigneeSwitcher";
import { VideoAgentPage } from "./video-agent/VideoAgentPage";
```

- [ ] **Step 4: Skip the session-fetch effect for "Video Generation"**

Find this `useEffect` (it fetches `/api/chats/${currentChat}/session` on every `currentChat` change):

```tsx
  useEffect(() => {
    activeChatRef.current = currentChat;
    let cancelled = false;
    setChat([]);
    fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/session`)
```

Change the start of it to:

```tsx
  useEffect(() => {
    activeChatRef.current = currentChat;
    if (currentChat === "Video Generation") { setChat([]); return; }
    let cancelled = false;
    setChat([]);
    fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/session`)
```

(`VideoAgentPage` manages its own state and never reads `chat`/`chatSessions` — this session fetch would be a wasted network call to a response nothing consumes.)

- [ ] **Step 5: Skip `activateChatTask` for "Video Generation" in `handleChatClick`**

Find:

```tsx
  function handleChatClick(chatName: string) { activateChatTask(chatName); const state = selectMenu({ type: "chat", id: chatName }, activeSection); activeChatRef.current = state.activeChat ?? "Workmate AI"; setActiveSection(state.activeSection); setActiveChat(state.activeChat); }
```

Replace with:

```tsx
  function handleChatClick(chatName: string) { if (chatName !== "Video Generation") activateChatTask(chatName); const state = selectMenu({ type: "chat", id: chatName }, activeSection); activeChatRef.current = state.activeChat ?? "Workmate AI"; setActiveSection(state.activeSection); setActiveChat(state.activeChat); }
```

(`activateChatTask` creates/updates an entry in the sidebar's "Agent Work" task list for the generic chat flow — not relevant to `VideoAgentPage`, which has no such task-list concept.)

- [ ] **Step 6: Insert the `VideoAgentPage` conditional and wrap the generic panels**

This is two separate edits on the same return statement — do them as two distinct find/replace operations, not one, since the file uses very long single-line JSX and getting a large multi-line match exactly right is error-prone. Both anchors below are unique in the file (verify with a search before editing if unsure).

**6a.** Find (this is a substring inside the giant `return <div className="shell ...">...` line — search for it, don't try to match the whole line):

```
<TaskQuickActions variant={agentContentVariant} currentChat={activeChat} onSelect={selectQuickAction} />{activeSection === "Today Briefing" && !activeChat
```

Replace with:

```
<TaskQuickActions variant={agentContentVariant} currentChat={activeChat} onSelect={selectQuickAction} />{activeChat === "Video Generation" && <div className="video-agent-host"><VideoAgentPage /></div>}{activeSection === "Today Briefing" && !activeChat
```

(Inserts a new conditional sibling, exactly mirroring how `ReferenceBriefingPanel`/`WeeklyReportPanel` already short-circuit based on `activeSection`.)

**6b.** Find (the opening of the `<main>` element — appears exactly once):

```
    <main className="workspace">
```

Replace with:

```
    {activeChat !== "Video Generation" && <>
    <main className="workspace">
```

**6c.** Find (the end of the generic chat composer's submit button, immediately followed by the closing `</aside>` of `.chat-panel` — this exact sequence appears exactly once; a similar-looking submit button exists in `MainUiPanels.tsx`'s `briefing-chatbot` but that one is followed by `</form></section>`, not `</form></aside>`):

```
<button type="submit">➤</button></form></aside>
```

Replace with:

```
<button type="submit">➤</button></form></aside></>}
```

(6b + 6c together wrap the entire `<main className="workspace">...</main><aside className="chat-panel">...</aside>` pair — unchanged internally — in `{activeChat !== "Video Generation" && <>...</>}`, so neither renders at all while the video-agent page is active.)

- [ ] **Step 7: Add the grid-column rule for `.video-agent-host`**

`.video-agent-host` needs to span the same two grid columns that `.workspace` + `.chat-panel` together would have occupied. Find the existing per-chat rule for `Game Q&A` in `styles.css`:

```css
.agent-content-updated[data-active-chat="Game Q&A"] .table-card{display:none}.agent-content-updated[data-active-chat="Game Q&A"] .workspace{grid-column:2}.agent-content-updated[data-active-chat="Game Q&A"] .chat-panel{grid-column:3}
```

Add a new rule directly after it (same file, new line):

```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2 / 4}
```

(`.agent-content-updated` is the class `.shell` gets whenever `activeChat` is truthy — matches the existing convention used for `Workmate AI` and `Game Q&A`'s per-chat overrides above it. `2 / 4` spans both content columns, matching the existing full-width pattern already used at `.section-active .workspace{grid-column:2 / 4}`.)

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npm run test:video-agent`
Expected: `App.test.tsx` PASSES.

- [ ] **Step 9: Run the full frontend suite for regressions**

Run: `cd frontend && npm run test:agent-routing && npm run test:preview && npm run test:preview-mode && npm run test:menu && npm run test:task && npm run test:command && npm run test:story && npm run test:resume && npm run test:story-import`
Expected: all PASS (unaffected — no shared utility files were touched).

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/src/App.test.tsx
git commit -m "feat: render VideoAgentPage from the existing Video Generation sidebar entry"
```

---

### Task 3: Restyle to match 오늘 브리핑

**Files:**
- Modify: `frontend/src/video-agent/VideoAgentPage.tsx`, `StatusBadge.tsx`, `ComposerTabs.tsx`, `ChatComposer.tsx`, `FormComposer.tsx`, `TaskCanvas.tsx`

**Interfaces:**
- Consumes: the `brief-*` Tailwind tokens from Task 1.
- Produces: no prop/behavior changes — purely className edits. Every existing test in `video-agent/*.test.tsx` must still pass unmodified (they assert `data-testid`/`aria-label`/text content, never className).

- [ ] **Step 1: Restyle `StatusBadge.tsx`**

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

const DOT_COLORS: Record<TaskState, string> = {
  TASK_STATE_SUBMITTED: "text-brief-accent",
  TASK_STATE_WORKING: "text-brief-accent",
  TASK_STATE_INPUT_REQUIRED: "text-amber-600",
  TASK_STATE_AUTH_REQUIRED: "text-amber-600",
  TASK_STATE_COMPLETED: "text-brief-accent-dark",
  TASK_STATE_FAILED: "text-red-600",
  TASK_STATE_CANCELED: "text-brief-muted",
  TASK_STATE_REJECTED: "text-red-600",
};

export function StatusBadge({ state, startedAt }: { state: TaskState; startedAt: number }) {
  const [elapsedSec, setElapsedSec] = useState(() => Math.floor((Date.now() - startedAt) / 1000));

  useEffect(() => {
    const interval = setInterval(() => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-brief-border bg-white px-3 py-1 text-sm text-brief-text"
      data-testid="status-badge"
    >
      <span aria-hidden className={DOT_COLORS[state]}>●</span>
      <span>{LABELS[state]}</span>
      <span className="text-brief-muted">{elapsedSec}s</span>
    </div>
  );
}
```

(Matches the `.signal-strip`'s `● Task 최신` dot-plus-label pattern. `LABELS`/`data-testid` unchanged, so the existing `StatusBadge.test.tsx` assertions — which check text content via `toHaveTextContent` — still pass.)

- [ ] **Step 2: Restyle `ComposerTabs.tsx`**

```tsx
// frontend/src/video-agent/ComposerTabs.tsx
import * as Tabs from "@radix-ui/react-tabs";
import { useState, type ReactNode } from "react";

export function ComposerTabs({ chat, form }: { chat: ReactNode; form: ReactNode }) {
  const [value, setValue] = useState("chat");

  return (
    <Tabs.Root value={value} onValueChange={setValue} className="flex flex-col gap-3">
      <Tabs.List className="flex gap-2" aria-label="브리프 작성 방식">
        <Tabs.Trigger
          value="chat"
          className="rounded-[8px] px-3 py-1 text-sm text-brief-text data-[state=active]:bg-brief-accent data-[state=active]:text-white"
        >
          채팅
        </Tabs.Trigger>
        <Tabs.Trigger
          value="form"
          className="rounded-[8px] px-3 py-1 text-sm text-brief-text data-[state=active]:bg-brief-accent data-[state=active]:text-white"
        >
          폼
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="chat" forceMount hidden={value !== "chat"}>
        {chat}
      </Tabs.Content>
      <Tabs.Content value="form" forceMount hidden={value !== "form"}>
        {form}
      </Tabs.Content>
    </Tabs.Root>
  );
}
```

(Only the two `Tabs.Trigger` classNames changed — active-tab color now `brief-accent` instead of `slate-900`, radius matches `.refresh-report`'s 8px. `forceMount`/`hidden` logic from the earlier fix round is untouched.)

- [ ] **Step 3: Restyle `ChatComposer.tsx`**

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
        className="min-h-24 rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
        aria-label="영상 브리프"
      />
      <button
        type="submit"
        disabled={disabled || value.trim().length < 5}
        className="rounded-[8px] bg-brief-accent px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
```

- [ ] **Step 4: Restyle `FormComposer.tsx`**

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
        className="min-h-16 rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
      />
      <input
        value={durationSec}
        onChange={(event) => setDurationSec(event.target.value)}
        placeholder="길이(초)"
        aria-label="길이(초)"
        inputMode="numeric"
        className="rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
      />
      <select
        value={preset}
        onChange={(event) => setPreset(event.target.value)}
        aria-label="프리셋"
        className="rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
      >
        <option value="">프리셋 선택 안 함</option>
        <option value="이벤트">이벤트</option>
        <option value="공개">공개</option>
        <option value="커뮤니티">커뮤니티</option>
      </select>
      <select
        value={sceneType}
        onChange={(event) => setSceneType(event.target.value)}
        aria-label="씬 종류"
        className="rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
      >
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
        className="rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
      />
      <button
        type="submit"
        disabled={disabled || brief.trim().length < 5}
        className="rounded-[8px] bg-brief-accent px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
```

- [ ] **Step 5: Restyle `TaskCanvas.tsx`**

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
      <div className="flex h-full items-center justify-center text-brief-muted" data-testid="canvas-idle">
        브리프를 작성하고 생성 요청을 눌러주세요.
      </div>
    );
  }

  const state = task.status.state;

  if (state === "TASK_STATE_SUBMITTED" || state === "TASK_STATE_WORKING") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3" data-testid="canvas-working">
        <span className="h-10 w-10 animate-spin rounded-full border-4 border-brief-border border-t-brief-accent" />
        <p className="text-brief-text">영상 생성 중...</p>
      </div>
    );
  }

  if (state === "TASK_STATE_INPUT_REQUIRED") {
    return (
      <div className="flex flex-col gap-3" data-testid="canvas-input-required">
        {unresolvedScenes.map((scene) => (
          <div
            key={scene.sceneId}
            className="rounded-[15px] border border-brief-border bg-white p-3"
            data-testid={`scene-card-${scene.sceneId}`}
          >
            <img src={scene.imageUrl} alt={scene.sceneId} className="mb-2 max-h-32 rounded-[8px]" />
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
      <video src={videoUrl} controls className="max-h-full rounded-[15px]" data-testid="canvas-completed" />
    ) : (
      <div data-testid="canvas-completed-no-video">완료되었지만 영상 URL을 찾을 수 없습니다.</div>
    );
  }

  const failureReason = task.status.message?.parts
    .map((part) => part.text)
    .filter(Boolean)
    .join("\n");

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3" data-testid="canvas-error">
      {failureReason && (
        <p className="text-brief-text" data-testid="canvas-error-reason">
          {failureReason}
        </p>
      )}
      <p className="text-brief-text">{state === "TASK_STATE_CANCELED" ? "취소되었습니다." : "생성에 실패했습니다."}</p>
      <button type="button" onClick={onRetry} className="rounded-[8px] bg-brief-accent px-3 py-2 text-sm text-white">
        다시 시도
      </button>
    </div>
  );
}
```

- [ ] **Step 6: Restyle `VideoAgentPage.tsx` and fix its height for the merged layout**

```tsx
// frontend/src/video-agent/VideoAgentPage.tsx
import "./styles.css";
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
  const [submitting, setSubmitting] = useState(false);
  const { task, reconnecting, error, resumePolling } = useVideoTaskPolling(taskId);

  useEffect(() => {
    if (task?.status.state === "TASK_STATE_INPUT_REQUIRED" && task.status.unresolvedScenes) {
      setUnresolvedScenes((previous) => (previous.length === 0 ? buildUnresolvedScenes(task.status.unresolvedScenes!) : previous));
    }
  }, [task?.id, task?.status.state, task?.status.unresolvedScenes]);

  async function handleSubmit(message: string) {
    setSubmitError(null);
    setClarifyingQuestion(null);
    setSubmitting(true);
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
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel() {
    if (!taskId) return;
    try {
      await cancelVideoAgentTask(taskId);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "취소 요청에 실패했습니다.");
    }
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
    <div className="grid h-full grid-cols-[minmax(280px,360px)_1fr] gap-4 bg-brief-bg p-4">
      <aside className="flex flex-col gap-3 rounded-[15px] border border-brief-border bg-white p-4">
        <h1 className="text-lg font-semibold text-brief-text">영상 생성</h1>
        <ComposerTabs
          chat={<ChatComposer disabled={isBusy || submitting} onSubmit={handleSubmit} />}
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
      <main className="rounded-[15px] border border-brief-border bg-white p-4">
        <TaskCanvas task={task} unresolvedScenes={unresolvedScenes} onUploadScene={handleUploadScene} onRetry={handleRetry} />
      </main>
    </div>
  );
}
```

(Two changes beyond restyle: `h-screen` → `h-full` — functionally required, not just cosmetic, since the page is now a grid child inside `App.tsx`'s layout rather than a full standalone document, and `h-screen` would force it to 100vh regardless of its actual grid cell height. Card panels drop `shadow-sm` in favor of a flat border + 15px radius, matching `.priority-card`/`.briefing-list`'s flat-card look — 오늘 브리핑 uses no box-shadow anywhere.)

- [ ] **Step 7: Run the full video-agent test suite to confirm nothing broke**

Run: `cd frontend && npm run test:video-agent`
Expected: all tests PASS with zero changes to any `*.test.tsx` file — confirms the restyle didn't touch anything a test actually asserts on.

- [ ] **Step 8: Manual visual check**

Run: `cd frontend && npm run dev`, open `http://localhost:5173/`, click "Video Generation" in the sidebar.
Expected: the page renders inline (no separate URL), sage-green/white card styling visible, composer and canvas both usable.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/video-agent/VideoAgentPage.tsx frontend/src/video-agent/StatusBadge.tsx frontend/src/video-agent/ComposerTabs.tsx frontend/src/video-agent/ChatComposer.tsx frontend/src/video-agent/FormComposer.tsx frontend/src/video-agent/TaskCanvas.tsx
git commit -m "style: restyle video-agent page to match 오늘 브리핑's sage-green look"
```

---

## Self-Review Notes

- **Spec coverage:** standalone-entry removal + Preflight isolation (Task 1), sidebar integration via the existing "Video Generation" entry + side-effect skips + true DOM removal of the generic panels (not just CSS-hidden, so it's actually testable) (Task 2), full sage-green restyle across every component including the functionally-required `h-screen`→`h-full` fix (Task 3) — every spec section has a task.
- **Placeholder scan:** no TODO/TBD; every step has literal code, exact find/replace anchors, or an exact runnable command.
- **Type consistency:** no new types introduced; all prop signatures (`ComposerTabs`, `ChatComposer`, `FormComposer`, `StatusBadge`, `TaskCanvas`) are unchanged from the already-shipped version — verified against the actual current file contents, not assumed from memory.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-14-video-agent-sidebar-merge.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
