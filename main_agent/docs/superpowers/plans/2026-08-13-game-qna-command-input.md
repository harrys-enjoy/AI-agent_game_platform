# Game Q&A Command Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Game Q&A command selection compact by placing only the command in the chat input.

**Architecture:** `selectGameQaCommand` is the single UI boundary from the command-help panel to the controlled chat input. Change that boundary to use the resolved command token rather than the detailed template; command interpretation remains unchanged.

**Tech Stack:** React, TypeScript, Node test runner, Vite.

## Global Constraints

- Do not change Game Q&A backend command contracts.
- Keep `/art` template behavior when a user submits only `/art`.
- Do not modify unrelated UI layout.

---

### Task 1: Compact command selection

**Files:**
- Modify: `frontend/scripts/command-utils-test.mjs`
- Modify: `frontend/src/App.tsx:272-276`

**Interfaces:**
- Consumes: `resolveChatCommand(command)` returning `{ kind: "request", command: string | null }`.
- Produces: input state containing `"/art "` after the Art command is selected.

- [ ] **Step 1: Write the failing test**

Add a small exported helper or testable callback assertion demonstrating that selecting `/art` produces `/art `, not the art template.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `node frontend/scripts/command-utils-test.mjs`

Expected: the new selection behavior assertion fails because the UI currently stores the full template.

- [ ] **Step 3: Write minimal implementation**

Change `selectGameQaCommand` from:

```ts
setMessage(`${resolved.command} ${resolved.content}`);
```

to:

```ts
setMessage(`${resolved.command} `);
```

- [ ] **Step 4: Run verification**

Run: `node frontend/scripts/command-utils-test.mjs && npm run build`

Expected: command tests and the TypeScript/Vite build pass.
