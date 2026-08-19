# Design: Surface the consistency anchor image during manual scene fixes

## Context

`916586e` (`feat: pass first accepted scene's image as a reference for later scenes`) fixed visual drift across scenes (e.g. a character's helmet design changing scene-to-scene) by passing the project's first successfully-accepted scene's image as a Gemini reference for every later scene's *automated* generation.

That anchor is never surfaced when a scene needs a **human** manual fix, though. `orchestrator.resume_scene_with_image()` accepts whatever image a human uploads verbatim, with no reference, no consistency check, nothing. If scene 1 fails and gets manually fixed *after* scene 2 has already succeeded (and become the anchor for scene 3+), the human fixing scene 1 has zero visibility into what the established look actually is — risking making cross-scene consistency worse, not better, exactly the problem `916586e` was meant to solve.

This spec covers surfacing that anchor image to the human at fix-time, so they can see it and manually match it. It deliberately does **not** cover auto-correcting or auto-editing what the human uploads against the anchor — the manual-fix flow is an intentional human-in-control escape hatch, and silently modifying their upload would undermine that.

## Goals

- When a scene needs a manual fix and a project-level consistency anchor exists (some other scene has already been accepted), surface that anchor's image URL to whoever is fixing it.
- When no anchor exists yet (e.g. the failing scene is the first one, nothing has succeeded), make that explicit rather than silently showing nothing, so the human isn't left guessing whether something is missing or broken.
- Keep the existing wire contract (`unresolvedScenes` as a flat `list[dict]`, passed through Main Agent's `unresolved_scenes: list[dict]` unmodified) intact — no restructuring into a wrapper object.

## Non-goals

- Auto-aligning or auto-editing a human's uploaded replacement image against the anchor.
- Retroactively regenerating already-accepted scenes if a later manual fix changes what "the anchor" should have been. (Discussed and explicitly rejected — real API cost and risk of new failures, for a cosmetic benefit on an already-rare edge case.)
- Any change to how the anchor is *selected* during automated generation (`orchestrator.py`'s `run_pipeline` loop) — this spec only affects what's surfaced to humans during manual fixes, not the generation algorithm itself.
- Reducing the cross-repo (`video_draft_pipeline` / `AI-agent_game_platform`) wiring duplication this pattern relies on. Real friction, explicitly out of scope for this change.

## Architecture

### Backend (`video_draft_pipeline`)

- `orchestrator.py`: rename `_first_accepted_image_url(scenes)` → `first_accepted_image_url(scenes)` (drop the leading underscore — it's now a genuinely shared utility, not private to this module). Update the one internal call site in `run_pipeline`. No behavior change; only one call site and no tests reference the old name, confirmed via `grep -rn "_first_accepted_image_url" src/ tests/`.
- `a2a_server/render_runner.py`'s `build_unresolved_scenes(project, media_public_base_url)`: compute the anchor once per call — `first_accepted_image_url(project.scenes)` — not once per scene entry, since it's identical for the whole project. If not `None`, prefix it with `media_public_base_url` the same way `imageUrl` already is built. Add it as `referenceImageUrl: str | None` on **every** entry in the returned list (deliberately redundant across entries — see "wire shape" note below).
- This function already backs both the initial "needs manual fix" response and the resume endpoint's `remaining_unresolved` field, so `referenceImageUrl` is present in both automatically — no separate wiring needed for the resume response path.

**Wire shape note:** the existing contract is a flat `list[dict]`, threaded unmodified through `AI-agent_game_platform`'s `TaskRecord.unresolved_scenes: list[dict]` passthrough (untyped on that side — a new key requires zero changes in the Main Agent backend). Restructuring into `{referenceImageUrl, scenes: [...]}` would touch significantly more files (`TaskStore`, multiple routes, the Main Agent's dict passthrough, frontend types) for the sole benefit of not repeating a short URL string 1-3 times per response. Repeating it is the cheaper, lower-risk choice and is what this spec does.

### Frontend (`AI-agent_game_platform`)

- `resume-utils.ts`: extend `RawUnresolvedScene` to `{ sceneId: string; imageUrl: string; issues: string[]; referenceImageUrl: string | null }`. `UnresolvedScene` (which extends it with `status`) picks this up with no separate change.
- `App.tsx`'s `renderChatMessage`, in the `unresolved-scenes` card branch: read `item.scenes[0]?.referenceImageUrl` once (every entry in the list carries the same value for a given card) and render it a single time above the per-scene rows, not repeated per row:
  - **Anchor exists**: a small thumbnail with a label such as "기존에 확립된 룩 (참고용)" ("established look, for reference").
  - **No anchor yet**: an explanatory note, e.g. "아직 참고할 확립된 이미지가 없습니다. 이 업로드가 이후 장면들의 기준이 됩니다" ("No established look yet — this upload will become the reference for later scenes").
- `mergeResumeResult` requires no changes: since the resume endpoint's `remaining_unresolved` reuses `build_unresolved_scenes`, `referenceImageUrl` flows through automatically, so the card stays correct if the human fixes one scene while others remain unresolved.
- New CSS for the reference-thumbnail block, following the existing `.unresolved-scene-thumb` pattern (e.g. `.unresolved-scene-reference`).

## Testing strategy

- Backend: unit tests for `build_unresolved_scenes()` in `tests/a2a_server/test_render_runner.py` — assert `referenceImageUrl` is populated (and correctly prefixed with `media_public_base_url`) when an earlier scene has been accepted, and is `null` when none has.
- Frontend: extend `resume-utils-test.mjs` fixtures to cover both states (`referenceImageUrl` present / `null`), matching the existing test style in that file.
- Live verification gap: `scripts/fake_video_agent_server.py` (the free local test harness) currently always builds a single-scene project that fails immediately, so an anchor never exists in that harness today — the "anchor present" thumbnail can never actually be seen through the running UI without a change. This spec includes extending the harness's canned scenario to two scenes (scene 1 succeeds normally and becomes the anchor; scene 2 needs manual fix) so both states — anchor present and anchor absent — are genuinely visible and clickable in a live run, not only unit-tested.

## Success criteria

- A human resuming a scene that needs a manual fix, in a project where some other scene has already succeeded, sees that scene's image before uploading a replacement.
- A human resuming the first scene of a project (no anchor yet) sees an explicit note rather than nothing.
- All existing `unresolvedScenes` / `remaining_unresolved` consumers (Main Agent backend passthrough, frontend types) continue to work unmodified aside from the new optional field.
- The free local test harness demonstrates both states live, without any real Gemini/Veo API cost.

## Follow-ups (explicitly out of scope here)

- Reducing cross-repo wire-contract duplication (raised and deferred during brainstorming).
- Any mechanism for retroactively improving already-accepted scenes after a later manual fix.
