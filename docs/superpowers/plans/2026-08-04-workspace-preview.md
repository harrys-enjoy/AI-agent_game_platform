# Workspace Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsible full-width bottom workspace preview for local image and code files under the Add code area.

**Architecture:** Keep the current Vite React app structure, extract file classification and preview state into a focused `PreviewPanel` component, and render it below the task table in the main workspace. Use browser-only `File.text()` and `URL.createObjectURL()` so no paid service or backend upload is required.

**Tech Stack:** React, TypeScript, Vite, CSS, Node built-in test runner for the pure file classification helper.

## Global Constraints

- No external paid service or file upload is required.
- Local files must remain in the browser and must not be persisted by the Main Agent backend.
- Existing task table and AI Chat behavior must remain available.
- Supported image formats are PNG, JPG, JPEG, GIF, and WebP.

---

### Task 1: File classification helper

**Files:**
- Create: `frontend/src/preview-utils.ts`
- Create: `frontend/scripts/preview-utils-test.mjs`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces `getPreviewKind(fileName: string): "image" | "code" | "unsupported"`.

- [ ] Write a failing Node test for image, code, and unsupported extensions.
- [ ] Run the test and confirm it fails because the helper is missing.
- [ ] Implement the minimal extension classifier.
- [ ] Run the test and confirm it passes.

### Task 2: Preview panel component

**Files:**
- Create: `frontend/src/PreviewPanel.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- `PreviewPanel` renders the panel and accepts no required props.
- It exposes user-visible controls named `Add file`, `Image`, `Code`, and `Workspace Preview`.

- [ ] Add component behavior tests through the existing browser build surface, covering empty state, file selection, and collapse control.
- [ ] Implement file state, object URL cleanup, text loading, and active-file selection.
- [ ] Connect the panel below the task table without changing chat submission behavior.

### Task 3: Styling and responsive layout

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] Add styles for the full-width preview card, file tabs, image canvas, code surface, and empty/error states.
- [ ] Add responsive behavior so the preview remains usable below 760px.
- [ ] Run the production build and confirm TypeScript and Vite both pass.

### Task 4: UI verification

**Files:**
- No source changes expected.

- [ ] Start the Vite dev server on port 4173.
- [ ] Verify the page renders, the preview panel opens, and the existing table/chat remain visible.
- [ ] Verify at least one image file and one code file locally through the browser.
