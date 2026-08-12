# Main UI Variants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep the current Main UI as one selectable variant and add a second UI variant with only `Home / Policies` in the Main menu, while placing four Workmate AI quick-action cards inside the chat panel.

**Architecture:** Reuse the existing `App.tsx` state, task table, chat session API, and PreviewPanel. Add a small client-side UI variant state persisted in `localStorage`, render shared sidebar/chat behavior for both variants, and switch only the central workspace presentation. Quick actions update the Workmate AI input without creating separate routes or backend APIs.

**Tech Stack:** React, TypeScript, Vite, CSS, existing frontend test scripts.

## Global Constraints

- Main menu contains only `Home` and `Policies` in both variants.
- `Skills`, `Meetings`, `My Tasks`, and `More` must not appear in the left Main menu.
- Four quick-action cards appear only inside the Workmate AI chat area, not in the central workspace.
- Existing chat, task, and Preview functionality must remain available.
- The UI variant selection persists through refresh using browser-local storage.
- `Policies` uses the English labels `Policies` and `Company Policies`.

### Task 1: Add UI variant and quick-action models

**Files:**
- Create: `frontend/src/ui-variant.ts`
- Test: `frontend/scripts/ui-variant-test.mjs`
- Modify: `frontend/src/menu-utils.ts`

**Interfaces:**
- `UiVariant = "legacy" | "updated"`
- `readUiVariant(value: string | null): UiVariant`
- `quickActions: readonly { id: string; label: string; prompt: string }[]`
- `selectMenu` accepts only `Home` and `Policies` for section selections.

- [ ] Add tests for valid/invalid stored variant values, the four exact prompts, and section selection.
- [ ] Run `node --experimental-strip-types scripts/ui-variant-test.mjs` and verify the new tests fail before implementation.
- [ ] Implement the small pure helpers and preserve chat selection behavior.
- [ ] Run the focused test again and verify it passes.
- [ ] Commit with `feat: add main ui variant models`.

### Task 2: Update App state and menu behavior

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Add `uiVariant` state initialized from `localStorage` key `main-ui-variant`.
- Add `selectQuickAction(prompt: string): void` that activates `Workmate AI` and puts `prompt` into the composer input.

- [ ] Replace the six-item `sections` constant with `Home` and `Policies`.
- [ ] Add the variant switcher near the workspace title and persist changes using `localStorage.setItem("main-ui-variant", variant)`.
- [ ] Render a `Policies` view when `activeSection === "Policies"` and no chat is active.
- [ ] Render the four quick-action cards immediately inside the Workmate AI chat panel, before the message list; do not render them in the central workspace.
- [ ] Make each card call `selectQuickAction` and keep the prompt editable before submission.
- [ ] Run the existing menu test and TypeScript build to catch integration errors.
- [ ] Commit with `feat: connect main ui variants and workmate actions`.

### Task 3: Build the two central workspace presentations

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Legacy variant keeps the existing table and PreviewPanel composition.
- Updated variant renders a compact overview header, the existing task table, recent activity summary, and the shared chat panel.

- [ ] Keep the legacy 3-column structure and remove any central today-briefing or weekly-report content if present.
- [ ] Add updated-variant classes for the overview header, summary metrics, recent activity, and active variant styling.
- [ ] Add `Company Policies` content with category cards and a search input when `Policies` is active.
- [ ] Ensure mobile layout collapses the sidebar, workspace, and chat panel vertically.
- [ ] Verify keyboard focus, button labels, and visible active states for menus, cards, and the variant switcher.
- [ ] Commit with `feat: add legacy and updated main ui layouts`.

### Task 4: Verify behavior and build

**Files:**
- Modify only files needed to resolve actual test or build failures.

- [ ] Run `node --experimental-strip-types scripts/ui-variant-test.mjs`.
- [ ] Run `node --experimental-strip-types scripts/menu-utils-test.mjs`.
- [ ] Run the existing frontend utility tests: `test:preview`, `test:preview-mode`, `test:task`, `test:command`, `test:story`, `test:resume`, and `test:story-import`.
- [ ] Run `npm run build` from `frontend`.
- [ ] Confirm the left Main menu contains only `Home` and `Policies` in both variants.
- [ ] Confirm the four quick-action cards are visible only within Workmate AI and populate the composer.
- [ ] Confirm the variant switch persists after refresh and existing task/chat functionality still compiles.
- [ ] Commit any narrowly scoped verification fix with a descriptive message.
