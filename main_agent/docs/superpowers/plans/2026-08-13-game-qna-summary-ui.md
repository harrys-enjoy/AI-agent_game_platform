# Game Q&A 작업 요약 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Game Q&A 본문의 Task 표를 작업 요약 대시보드로 교체하고 기존 TXT/스토리 입력 흐름을 유지한다.

**Architecture:** `App.tsx`에서 Game Q&A일 때만 기존 Task 표 대신 요약 패널을 렌더링한다. 요약 UI는 별도 컴포넌트로 분리하고, 현재 저장된 스토리 검토 상태와 정적 안내 상태를 표시한다. 기존 다른 Agent 화면과 API는 건드리지 않는다.

**Tech Stack:** React, TypeScript, CSS, existing story review API.

## Global Constraints

- Game Q&A 본문 Task 표와 `+ Add task`만 제거한다.
- 사이드바 Agent Work와 다른 Agent의 Task는 유지한다.
- 실제 TXT/Catalog API가 확인하지 않은 상태를 성공으로 표시하지 않는다.
- RPG 스토리 검토 흐름은 유지한다.

### Task 1: 요약 패널 컴포넌트 추가

**Files:**
- Create: `frontend/src/GameQnaSummary.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/scripts/game-qna-summary-test.mjs`

- [ ] **Step 1: Add a focused test for summary section labels and attention states.**
- [ ] **Step 2: Run the test and verify the new component contract fails.**
- [ ] **Step 3: Implement the component with four summary cards, TXT status, story review status, and recent work rows.**
- [ ] **Step 4: Render it only when `activeChat === "Game Q&A"`; preserve the existing Task table for other chats.**
- [ ] **Step 5: Run the focused test.**

### Task 2: Game Q&A layout styling

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add responsive grid styles for the summary dashboard.**
- [ ] **Step 2: Add styles for TXT status, story review status, and recent work rows.**
- [ ] **Step 3: Verify the existing chat panel and other Agent layouts retain their selectors and behavior.**

### Task 3: Verification

**Files:**
- Modify: `frontend/scripts/game-qna-summary-test.mjs` only if assertions need adjustment.

- [ ] **Step 1: Run all backend tests.**
- [ ] **Step 2: Run all frontend utility tests including the new summary test.**
- [ ] **Step 3: Run the production frontend build.**
- [ ] **Step 4: Run `git diff --check` and inspect the final diff.**
