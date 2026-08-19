# Surface Consistency Anchor During Manual Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the project's established consistency-anchor image (the first successfully-accepted scene) to a human resuming a manually-fixed scene, so they can match it instead of guessing blind.

**Architecture:** Backend (`video_draft_pipeline`) computes the anchor once per `build_unresolved_scenes()` call and adds it as `referenceImageUrl` on every unresolved-scene entry in the existing flat `list[dict]` wire shape (no restructuring). Frontend (`AI-agent_game_platform`) widens its type to match and renders the anchor once above the scene list in the existing upload card. A free local test harness (`fake_video_agent_server.py`) gets an opt-in second scenario so both states (anchor present / anchor absent) are visible live without any paid API calls.

**Tech Stack:** Python 3.11+ / FastAPI / pytest (`video_draft_pipeline`); TypeScript / React / Node's built-in test runner via `--experimental-strip-types` (`AI-agent_game_platform/frontend`).

## Global Constraints

- Do not restructure the `unresolvedScenes` / `unresolved_scenes` wire contract away from a flat `list[dict]` — the Main Agent backend passes it through untyped, and changing shape would require touching files outside this plan's scope. (Spec: "Wire shape note".)
- Do not auto-edit or auto-align a human's uploaded replacement image against the anchor — the resume endpoint must keep accepting whatever the human uploads verbatim (after the existing normalization-to-1280x720 step, which is unrelated to this feature and must not be touched).
- Do not change how the anchor is *selected* during automated generation (`orchestrator.py`'s `run_pipeline` loop) — only what's surfaced to humans during manual fixes.
- Korean UI copy for the two reference states is fixed by the spec (see Task 3) — use it verbatim, don't paraphrase.

---

### Task 1: Promote the anchor lookup and add `referenceImageUrl` to `build_unresolved_scenes`

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py:78-85` (rename `_first_accepted_image_url` → `first_accepted_image_url`), `src/video_draft_pipeline/orchestrator.py:169` (update call site)
- Modify: `src/video_draft_pipeline/a2a_server/render_runner.py:6` (import), `src/video_draft_pipeline/a2a_server/render_runner.py:44-56` (`build_unresolved_scenes`)
- Test: `tests/a2a_server/test_render_runner.py:93-99` and `tests/a2a_server/test_render_runner.py:131-139` (update two existing tests' expectations)

**Interfaces:**
- Produces: `first_accepted_image_url(scenes: list[Scene]) -> str | None` (public, in `orchestrator.py`, same behavior as the old private version — returns the first scene's `accepted_candidate_id`'s `image_url`, or `None` if no scene has been accepted yet).
- Produces: `build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]` now returns entries shaped `{"sceneId": str, "imageUrl": str, "issues": list[str], "referenceImageUrl": str | None}` — the new key, same value, on every entry in the list.

- [ ] **Step 1: Update the two existing tests to expect `referenceImageUrl` (RED)**

In `tests/a2a_server/test_render_runner.py`, update `test_build_unresolved_scenes_returns_only_unresolved_with_issues`'s final assertion (currently lines 133-139) to:

```python
    assert result == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": ["shot too wide", "prop diagonal"],
            "referenceImageUrl": "http://localhost:8002/media/cand_ok.png",
        }
    ]
```

(`ok_scene` in this test is already accepted with `image_url="media/cand_ok.png"` and appears before `bad_scene` in `project.scenes`, so it's the anchor.)

Update `test_run_render_task_marks_completed_with_unresolved_scenes_message`'s final assertion (currently lines 93-99) to:

```python
    assert updated.unresolved_scenes == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": [],
            "referenceImageUrl": None,
        }
    ]
```

(This test's `fake_render` only ever produces one scene, which is itself the failing one — nothing has been accepted, so there's no anchor.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/a2a_server/test_render_runner.py -v`
Expected: both `test_build_unresolved_scenes_returns_only_unresolved_with_issues` and `test_run_render_task_marks_completed_with_unresolved_scenes_message` FAIL, each with an assertion diff showing the actual dict is missing the `"referenceImageUrl"` key.

- [ ] **Step 3: Rename `_first_accepted_image_url` to `first_accepted_image_url` in `orchestrator.py`**

Change (around line 78):

```python
def _first_accepted_image_url(scenes: list[Scene]) -> str | None:
```

to:

```python
def first_accepted_image_url(scenes: list[Scene]) -> str | None:
```

(body unchanged). Update the one call site (around line 169), inside `run_pipeline`:

```python
        reference_image_url = _first_accepted_image_url(project.scenes)
```

to:

```python
        reference_image_url = first_accepted_image_url(project.scenes)
```

- [ ] **Step 4: Wire the anchor into `build_unresolved_scenes` in `render_runner.py`**

Change the import line (currently line 6):

```python
from ..orchestrator import PipelineError, format_candidate_diagnostics, run_pipeline
```

to:

```python
from ..orchestrator import PipelineError, first_accepted_image_url, format_candidate_diagnostics, run_pipeline
```

Replace `build_unresolved_scenes` (currently lines 44-56):

```python
def build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]:
    entries = []
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_candidate = scene.candidates[-1]
        review = last_candidate.consistency_review
        entries.append({
            "sceneId": scene.scene_id,
            "imageUrl": f"{media_public_base_url}/{last_candidate.image_url}",
            "issues": review.issues if review else [],
        })
    return entries
```

with:

```python
def build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]:
    anchor_image_url = first_accepted_image_url(project.scenes)
    reference_image_url = f"{media_public_base_url}/{anchor_image_url}" if anchor_image_url else None
    entries = []
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_candidate = scene.candidates[-1]
        review = last_candidate.consistency_review
        entries.append({
            "sceneId": scene.scene_id,
            "imageUrl": f"{media_public_base_url}/{last_candidate.image_url}",
            "issues": review.issues if review else [],
            "referenceImageUrl": reference_image_url,
        })
    return entries
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/a2a_server/test_render_runner.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `python -m pytest`
Expected: all tests pass, same total count as before this task plus no failures (the rename has only one call site and no test references `_first_accepted_image_url` by name — confirmed via `grep -rn "_first_accepted_image_url" src/ tests/` returning no matches after this change).

- [ ] **Step 7: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py src/video_draft_pipeline/a2a_server/render_runner.py tests/a2a_server/test_render_runner.py
git commit -m "feat: surface the consistency anchor image in unresolved-scene payloads"
```

---

### Task 2: Widen the frontend's `RawUnresolvedScene` type and add `getReferenceImageUrl`

**Files:**
- Modify: `frontend/src/resume-utils.ts`
- Test: `frontend/scripts/resume-utils-test.mjs`

**Interfaces:**
- Consumes: the `referenceImageUrl` field name from Task 1's backend output.
- Produces: `RawUnresolvedScene = { sceneId: string; imageUrl: string; issues: string[]; referenceImageUrl: string | null }` (and `UnresolvedScene`, which extends it with `status`, picks this up automatically since it's defined as `RawUnresolvedScene & { status: UnresolvedSceneStatus }`). Also produces `getReferenceImageUrl(scenes: RawUnresolvedScene[]): string | null` — reads the shared reference off the first scene in a list, or `null` if there isn't one. Task 3 calls this instead of inlining the same lookup in JSX.

Note on scope: `buildUnresolvedScenes`, `mergeResumeResult`, and `buildTaskFixChatMessage` are spread-based passthroughs (e.g. `{ ...scene, status: "pending" }`) that already carry any extra field on a raw scene object through with zero code changes — widening the type alone doesn't drive new behavior in them. `getReferenceImageUrl` is the one piece of genuinely new logic in this task, and it gets a real TDD cycle below. The fixture updates for the passthrough functions (Step 5) are characterization tests that document the contract for this field; they're expected to pass without further implementation changes once the type is widened, which is correct for pure passthroughs, not a red flag.

- [ ] **Step 1: Write the failing test for `getReferenceImageUrl` (RED)**

In `frontend/scripts/resume-utils-test.mjs`, change the `import` line (currently line 3):

```javascript
import { buildUnresolvedScenes, markSceneStatus, mergeResumeResult, buildResumeFormData, finalVideoMessageText, buildTaskFixChatMessage } from "../src/resume-utils.ts";
```

to:

```javascript
import { buildUnresolvedScenes, markSceneStatus, mergeResumeResult, buildResumeFormData, finalVideoMessageText, buildTaskFixChatMessage, getReferenceImageUrl } from "../src/resume-utils.ts";
```

Then add these three tests anywhere after the import line (e.g. right before the `"builds pending scenes from raw server data"` test):

```javascript
test("getReferenceImageUrl returns the shared reference from the first scene", () => {
  const scenes = [
    { sceneId: "scene_01", imageUrl: "u1", issues: [], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png", status: "pending" },
    { sceneId: "scene_02", imageUrl: "u2", issues: [], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png", status: "pending" },
  ];

  assert.equal(getReferenceImageUrl(scenes), "http://localhost:8002/media/cand_anchor.png");
});

test("getReferenceImageUrl returns null when no scene has an established reference yet", () => {
  const scenes = [
    { sceneId: "scene_01", imageUrl: "u1", issues: [], referenceImageUrl: null, status: "pending" },
  ];

  assert.equal(getReferenceImageUrl(scenes), null);
});

test("getReferenceImageUrl returns null for an empty scene list", () => {
  assert.equal(getReferenceImageUrl([]), null);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm run test:resume`
Expected: FAIL — `getReferenceImageUrl is not a function` (or `is not defined` / `undefined`), since it doesn't exist yet in `resume-utils.ts`. The three new tests fail; do not proceed until you've confirmed the failure is this specific missing-export error, not a syntax error elsewhere in the file.

- [ ] **Step 3: Widen the type and implement `getReferenceImageUrl`**

In `frontend/src/resume-utils.ts`, change line 2:

```ts
export type RawUnresolvedScene = { sceneId: string; imageUrl: string; issues: string[] };
```

to:

```ts
export type RawUnresolvedScene = { sceneId: string; imageUrl: string; issues: string[]; referenceImageUrl: string | null };
```

Then add this function — place it directly after `buildUnresolvedScenes`:

```ts
export function getReferenceImageUrl(scenes: RawUnresolvedScene[]): string | null {
  return scenes[0]?.referenceImageUrl ?? null;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm run test:resume`
Expected: the three `getReferenceImageUrl` tests PASS. The other existing tests will now fail — that's expected and addressed in the next step, since their fixtures don't yet include the new required field.

- [ ] **Step 5: Update the remaining test fixtures to include `referenceImageUrl`**

In `frontend/scripts/resume-utils-test.mjs`, update every inline raw-scene object literal (both inputs and expected outputs) in the *other* tests to include `referenceImageUrl`. Replace the full file's remaining test bodies as follows — keep the `import` line (already updated in Step 1) and `test(...)` wrapper structure identical, only the object literals inside change:

```javascript
test("builds pending scenes from raw server data", () => {
  const raw = [
    { sceneId: "scene_04", imageUrl: "http://localhost:8002/media/cand_1.png", issues: ["too wide"], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png" },
    { sceneId: "scene_05", imageUrl: "http://localhost:8002/media/cand_2.png", issues: [], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png" },
  ];

  assert.deepEqual(buildUnresolvedScenes(raw), [
    { sceneId: "scene_04", imageUrl: "http://localhost:8002/media/cand_1.png", issues: ["too wide"], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png", status: "pending" },
    { sceneId: "scene_05", imageUrl: "http://localhost:8002/media/cand_2.png", issues: [], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png", status: "pending" },
  ]);
});

test("builds pending scenes from raw server data with no reference image yet", () => {
  const raw = [
    { sceneId: "scene_01", imageUrl: "http://localhost:8002/media/cand_1.png", issues: ["too wide"], referenceImageUrl: null },
  ];

  assert.deepEqual(buildUnresolvedScenes(raw), [
    { sceneId: "scene_01", imageUrl: "http://localhost:8002/media/cand_1.png", issues: ["too wide"], referenceImageUrl: null, status: "pending" },
  ]);
});
```

Replace the `"marks only the matching scene's status..."` test's fixtures:

```javascript
test("marks only the matching scene's status, leaving others untouched", () => {
  const scenes = buildUnresolvedScenes([
    { sceneId: "scene_04", imageUrl: "u1", issues: [], referenceImageUrl: null },
    { sceneId: "scene_05", imageUrl: "u2", issues: [], referenceImageUrl: null },
  ]);

  const updated = markSceneStatus(scenes, "scene_04", "uploading");

  assert.equal(updated[0].status, "uploading");
  assert.equal(updated[1].status, "pending");
});
```

Replace the `"merges a resume response..."` test:

```javascript
test("merges a resume response, preserving each remaining scene's own prior status", () => {
  const previous = [
    { sceneId: "scene_04", imageUrl: "u1", issues: [], referenceImageUrl: null, status: "uploading" },
    { sceneId: "scene_05", imageUrl: "u2", issues: ["still off"], referenceImageUrl: null, status: "pending" },
  ];
  const result = {
    scene_id: "scene_06",
    resolved: true,
    remaining_unresolved: [
      { sceneId: "scene_04", imageUrl: "u1", issues: [], referenceImageUrl: null },
      { sceneId: "scene_05", imageUrl: "u2", issues: ["still off"], referenceImageUrl: null },
    ],
    output_video_url: null,
  };

  const merged = mergeResumeResult(previous, result);

  assert.deepEqual(merged, [
    { sceneId: "scene_04", imageUrl: "u1", issues: [], referenceImageUrl: null, status: "uploading" },
    { sceneId: "scene_05", imageUrl: "u2", issues: ["still off"], referenceImageUrl: null, status: "pending" },
  ]);
});
```

Replace the `"a scene appearing in remaining_unresolved for the first time..."` test:

```javascript
test("a scene appearing in remaining_unresolved for the first time defaults to pending", () => {
  const result = {
    scene_id: "scene_04",
    resolved: true,
    remaining_unresolved: [{ sceneId: "scene_05", imageUrl: "u2", issues: ["still off"], referenceImageUrl: null }],
    output_video_url: null,
  };

  assert.deepEqual(mergeResumeResult([], result), [
    { sceneId: "scene_05", imageUrl: "u2", issues: ["still off"], referenceImageUrl: null, status: "pending" },
  ]);
});
```

Leave `"an empty remaining_unresolved produces an empty scene list"`, `"wraps a file in FormData..."`, and `"formats a message announcing the finished video"` unchanged (they don't construct scene objects with the affected fields).

Replace the final `"reconstructs an unresolved-scenes chat card..."` test:

```javascript
test("reconstructs an unresolved-scenes chat card from stored task data", () => {
  const rawScenes = [
    { sceneId: "scene_04", imageUrl: "http://localhost:8002/media/cand_1.png", issues: ["too wide"], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png" },
    { sceneId: "scene_05", imageUrl: "http://localhost:8002/media/cand_2.png", issues: [], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png" },
  ];

  const message = buildTaskFixChatMessage("task_abc123", rawScenes);

  assert.equal(message.kind, "unresolved-scenes");
  assert.equal(message.taskId, "task_abc123");
  assert.deepEqual(message.scenes, [
    { sceneId: "scene_04", imageUrl: "http://localhost:8002/media/cand_1.png", issues: ["too wide"], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png", status: "pending" },
    { sceneId: "scene_05", imageUrl: "http://localhost:8002/media/cand_2.png", issues: [], referenceImageUrl: "http://localhost:8002/media/cand_anchor.png", status: "pending" },
  ]);
  assert.match(message.id, /^unresolved-/);
});
```

- [ ] **Step 6: Run the full test file to verify everything passes together**

Run (from `frontend/`): `npm run test:resume`
Expected: all tests PASS — the three `getReferenceImageUrl` tests from Step 1, and every other test with its fixtures now including `referenceImageUrl`.

- [ ] **Step 7: Verify the type-check builds clean**

Run (from `frontend/`): `npm run build`
Expected: no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/resume-utils.ts frontend/scripts/resume-utils-test.mjs
git commit -m "feat: add getReferenceImageUrl and widen RawUnresolvedScene with referenceImageUrl"
```

---

### Task 3: Render the reference image (or explanatory note) in the upload card

**Files:**
- Modify: `frontend/src/App.tsx:238`
- Modify: `frontend/src/task-form.css`

**Interfaces:**
- Consumes: `getReferenceImageUrl(scenes: RawUnresolvedScene[]): string | null` and `UnresolvedScene.referenceImageUrl: string | null` (from Task 2).
- Produces: no new exported interface — purely a rendering change inside `renderChatMessage`.

There is no component/DOM test harness anywhere in this frontend (all existing frontend tests are pure-function tests via Node's test runner) — introducing one for a single small rendering change would be disproportionate scope creep. This task's verification gate is `npm run build` (type-check) plus live visual confirmation, which happens in Task 4 once the test harness can produce both states.

- [ ] **Step 1: Import `getReferenceImageUrl`**

In `frontend/src/App.tsx`, change the `resume-utils` import (currently line 9):

```tsx
import { buildResumeFormData, buildTaskFixChatMessage, buildUnresolvedScenes, finalVideoMessageText, markSceneStatus, mergeResumeResult, RawUnresolvedScene, ResumeResult, UnresolvedScene } from "./resume-utils";
```

to:

```tsx
import { buildResumeFormData, buildTaskFixChatMessage, buildUnresolvedScenes, finalVideoMessageText, getReferenceImageUrl, markSceneStatus, mergeResumeResult, RawUnresolvedScene, ResumeResult, UnresolvedScene } from "./resume-utils";
```

- [ ] **Step 2: Add the reference-image block to the unresolved-scenes card**

In `frontend/src/App.tsx`, the entire `unresolved-scenes` branch is currently a single line (line 238):

```tsx
    if (item.kind === "unresolved-scenes") { const anyUploading = item.scenes.some((s) => s.status === "uploading"); return <div className="proposal-card unresolved-scenes-card" key={item.id}><strong>수동 수정이 필요한 장면</strong>{item.scenes.map((scene) => <div className="unresolved-scene-row" key={scene.sceneId}><img className="unresolved-scene-thumb" src={scene.imageUrl} alt={scene.sceneId} /><div className="unresolved-scene-info"><b>{scene.sceneId}</b><ul>{scene.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>{(scene.status === "pending" || scene.status === "error") && !anyUploading && <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadSceneFix(item.id, item.taskId, scene.sceneId, file); event.target.value = ""; }} />}{scene.status === "uploading" && <small>업로드 중...</small>}{scene.status === "error" && <small className="unresolved-scene-error">업로드 실패. 다시 시도해 주세요.</small>}</div></div>)}</div>; }
```

Replace it with (following the file's existing single-line-per-branch style — only the new reference block is inserted, right after the `<strong>` heading and before `{item.scenes.map(...)}`):

```tsx
    if (item.kind === "unresolved-scenes") { const anyUploading = item.scenes.some((s) => s.status === "uploading"); const referenceImageUrl = getReferenceImageUrl(item.scenes); return <div className="proposal-card unresolved-scenes-card" key={item.id}><strong>수동 수정이 필요한 장면</strong>{referenceImageUrl ? <div className="unresolved-scene-reference"><small>기존에 확립된 룩 (참고용)</small><img className="unresolved-scene-reference-thumb" src={referenceImageUrl} alt="reference" /></div> : <div className="unresolved-scene-reference"><small>아직 참고할 확립된 이미지가 없습니다. 이 업로드가 이후 장면들의 기준이 됩니다.</small></div>}{item.scenes.map((scene) => <div className="unresolved-scene-row" key={scene.sceneId}><img className="unresolved-scene-thumb" src={scene.imageUrl} alt={scene.sceneId} /><div className="unresolved-scene-info"><b>{scene.sceneId}</b><ul>{scene.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>{(scene.status === "pending" || scene.status === "error") && !anyUploading && <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadSceneFix(item.id, item.taskId, scene.sceneId, file); event.target.value = ""; }} />}{scene.status === "uploading" && <small>업로드 중...</small>}{scene.status === "error" && <small className="unresolved-scene-error">업로드 실패. 다시 시도해 주세요.</small>}</div></div>)}</div>; }
```

- [ ] **Step 3: Add CSS for the reference block**

In `frontend/src/task-form.css`, after the existing `.unresolved-scene-error{color:#c34f5d}` line, add:

```css
.unresolved-scene-reference{padding:8px 0 10px;border-bottom:1px solid #e4e7ef;margin-bottom:4px}
.unresolved-scene-reference small{display:block;color:#7c879c;margin-bottom:6px}
.unresolved-scene-reference-thumb{width:96px;height:96px;object-fit:cover;border-radius:6px}
```

- [ ] **Step 4: Verify the type-check builds clean**

Run (from `frontend/`): `npm run build`
Expected: no TypeScript errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/task-form.css
git commit -m "feat: show the established reference image on the manual-fix upload card"
```

---

### Task 4: Extend the free test harness with an opt-in anchor scenario, verify both states live

**Files:**
- Modify: `scripts/fake_video_agent_server.py`

**Interfaces:**
- Consumes: Task 1's `referenceImageUrl` field in `build_unresolved_scenes`'s output (exercised indirectly through the real A2A server code, not called directly).
- Produces: `FAKE_SCENARIO` environment variable (`"no_anchor"` default, `"with_anchor"` opt-in) and `build_fake_project_with_anchor(...)`, a new function alongside the existing `build_fake_project(...)`.

The default scenario (`FAKE_SCENARIO` unset or `"no_anchor"`) must remain byte-for-byte identical to today's behavior — every run instruction already given this session assumed the single-scene, no-anchor scenario, and it must keep working unchanged.

- [ ] **Step 1: Add a `color` parameter to `_generate_placeholder_image`**

Change (near the top of `scripts/fake_video_agent_server.py`):

```python
def _generate_placeholder_image(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=slateblue:s=512x512", "-frames:v", "1", "-update", "1", str(path)],
        check=True,
    )
```

to:

```python
def _generate_placeholder_image(path: Path, color: str = "slateblue") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=512x512", "-frames:v", "1", "-update", "1", str(path)],
        check=True,
    )
```

- [ ] **Step 2: Add the `FAKE_SCENARIO` module-level constant**

`os` is not currently imported in this file. Add `import os` as the first line of the existing import block, so:

```python
import subprocess
import uuid
from pathlib import Path
```

becomes:

```python
import os
import subprocess
import uuid
from pathlib import Path
```

Then add, near the top of the file, alongside the existing `MEDIA_DIR`/`SUBDIR_NAME`/`FS_OUTPUT_DIR` constants:

```python
FAKE_SCENARIO = os.environ.get("FAKE_SCENARIO", "no_anchor")  # "no_anchor" | "with_anchor"
```

- [ ] **Step 3: Add `build_fake_project_with_anchor`**

Add this function directly after the existing `build_fake_project` function:

```python
def build_fake_project_with_anchor(anchor_image_url_relative_to_media_dir: str, image_url_relative_to_media_dir: str) -> Project:
    project_id = f"proj_fake_{uuid.uuid4().hex[:8]}"
    anchor_scene = Scene(
        scene_id="scene_00",
        beat_id="setup",
        order=0,
        duration_sec=4.0,
        storyboard=Storyboard(
            camera="wide establishing shot",
            subject="cyberpunk operative",
            action="stands still under neon signage",
            setting="rain-slicked alley",
        ),
        accepted_candidate_id="cand_anchor01",
        candidates=[
            Candidate(
                candidate_id="cand_anchor01",
                image_url=anchor_image_url_relative_to_media_dir,
                generated_by="fake_harness",
                consistency_review=ConsistencyReview(
                    reviewed_by="fake_harness", passed=True, issues=[], defect_category="none",
                ),
            )
        ],
    )
    failing_scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=4.0,
        storyboard=Storyboard(
            camera="tight close-up",
            subject="cyberpunk operative",
            action="tilts head up toward camera",
            setting="rain-slicked alley",
        ),
        candidates=[
            Candidate(
                candidate_id="cand_fake01",
                image_url=image_url_relative_to_media_dir,
                generated_by="fake_harness",
                consistency_review=ConsistencyReview(
                    reviewed_by="fake_harness",
                    passed=False,
                    issues=["헬멧 디자인이 이전 씬과 일치하지 않음 (테스트용 고정 사유)"],
                    defect_category="localized_artifact",
                ),
            )
        ],
        needs_manual_fix=True,
        retry_count=3,
        max_retries=3,
    )
    return Project(
        project_id=project_id,
        input=ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=8, brief="테스트용 고정 시나리오 (앵커 포함)"),
        scenes=[anchor_scene, failing_scene],
    )
```

- [ ] **Step 4: Generate the anchor placeholder image and wire scenario selection into `main()`**

In `main()`, after the existing `image_path`/`clip_path`/`image_url_relative_to_media_dir` setup and before `project_store = ProjectStore(...)`, add:

```python
    anchor_image_path = FS_OUTPUT_DIR / "placeholder_anchor_scene.png"
    anchor_image_url_relative_to_media_dir = f"{MEDIA_DIR.name}/{SUBDIR_NAME}/placeholder_anchor_scene.png"
    if FAKE_SCENARIO == "with_anchor":
        _generate_placeholder_image(anchor_image_path, color="orange")
```

Replace the existing `fake_render_fn`:

```python
    def fake_render_fn(project_input: ProjectInput) -> Project:
        project = build_fake_project(image_url_relative_to_media_dir)
        project_store.save(project)
        return project
```

with:

```python
    def fake_render_fn(project_input: ProjectInput) -> Project:
        if FAKE_SCENARIO == "with_anchor":
            project = build_fake_project_with_anchor(anchor_image_url_relative_to_media_dir, image_url_relative_to_media_dir)
        else:
            project = build_fake_project(image_url_relative_to_media_dir)
        project_store.save(project)
        return project
```

Also update the two `print(...)` lines near the end of `main()` to mention the scenario, e.g. change:

```python
    print("Fake video-agent server ready on http://localhost:8002 (zero API cost).")
    print("Every chat request returns the same fixed 'needs manual fix' scenario.")
```

to:

```python
    print("Fake video-agent server ready on http://localhost:8002 (zero API cost).")
    print(f"Scenario: {FAKE_SCENARIO} (set FAKE_SCENARIO=with_anchor or =no_anchor to switch).")
```

- [ ] **Step 5: Verify the default (`no_anchor`) scenario is unchanged**

Kill any already-running `fake_video_agent_server.py` process first (check with the same `Get-CimInstance Win32_Process` pattern used earlier this session), then run:

Run: `python scripts/fake_video_agent_server.py` (no env var set)

In a second terminal, send a message and confirm the response still matches today's single-scene shape:

```bash
curl -s -X POST http://localhost:8002/message:send -H "Content-Type: application/json" -d '{"message":{"role":"user","parts":[{"type":"text","text":"test"}]}}'
```

Poll the returned task ID via `curl -s http://localhost:8002/tasks/<task_id>` and confirm the JSON's `unresolvedScenes` has exactly one entry for `scene_01` with `"referenceImageUrl": null`.

- [ ] **Step 6: Verify the `with_anchor` scenario produces both states correctly**

Stop the server, restart with:

Run: `FAKE_SCENARIO=with_anchor python scripts/fake_video_agent_server.py`

Send a message the same way, poll the task, and confirm the JSON's `unresolvedScenes` has exactly one entry (for `scene_01` — `scene_00` succeeded and isn't unresolved), with `"referenceImageUrl"` set to a URL ending in `/media/fake_video_agent_server/placeholder_anchor_scene.png`. Fetch that URL directly with `curl -s -o /dev/null -w "%{http_code}"` and confirm it returns `200`.

- [ ] **Step 7: Clean up test artifacts**

```bash
rm -rf media/fake_video_agent_server media/proj_fake_*.mp4 media/proj_fake_*.txt
```

(Only run this after stopping the server process — deleting its working directory while it's still running breaks subsequent renders, as happened earlier this session.)

- [ ] **Step 8: Commit**

```bash
git add scripts/fake_video_agent_server.py
git commit -m "feat: add opt-in with_anchor scenario to the free video-agent test harness"
```

- [ ] **Step 9: Hand off for live UI verification**

Tell the user: restart the fake server with `FAKE_SCENARIO=with_anchor python scripts/fake_video_agent_server.py` (and restart the Main Agent backend/frontend if not already running), submit a fresh "영상" request through the UI, and confirm the upload card shows the orange anchor thumbnail above the scene list. Then restart the fake server with `FAKE_SCENARIO=no_anchor` (or unset) and confirm a fresh request shows the "아직 참고할 확립된 이미지가 없습니다..." note instead. This is the final visual confirmation this plan can't verify by itself (no browser automation in this session).
