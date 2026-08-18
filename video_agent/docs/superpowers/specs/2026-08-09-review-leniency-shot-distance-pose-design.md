# Review leniency for shot distance and prop orientation

## Context

Running the A2A server end-to-end for real (2026-08-08) produced a real failure: `scene_04` (the `resolution` beat) was rejected after all 3 retries and the whole render failed, even though the other 3 scenes almost certainly passed. Reading the real `agent_log.jsonl` for that run showed the same two complaints on every attempt:

- "Framing shows a full-body/medium shot instead of the requested extreme low-angle close-up."
- "The scythe is held diagonally rather than vertically by her side."

Each retry's `GeminiPromptAgent` output got progressively more explicit about these two points (per the director's feedback loop), and `gemini-3.1-flash-image` still didn't hit them by attempt 4. That pattern — increasingly explicit wording, same failure — points to a model steerability limit on shot-distance and prop-orientation precision, not sloppy prompt wording.

This is unrelated to the POV-mixing and physical/anatomical-integrity fixes shipped 2026-08-04/05 (`9bb9428`, `2941438`, `2292181`) — those addressed a different defect class (images that look objectively broken) and are working as intended. Shot distance and prop orientation were never called out as their own category; they were being judged under `GeminiReviewAgent`'s general "passed=true only if the image clearly matches" instruction, as strictly as everything else.

## Goals

- Stop scenes from failing review over imprecise-but-reasonable shot distance or prop orientation, while keeping POV-mixing and physical/anatomical-integrity rejections exactly as strict as they are today.
- Keep the fix scoped to `GeminiReviewAgent`'s prompt text — no schema changes, no orchestrator/retry-routing changes.

## Non-goals

- Not changing `GeminiPromptAgent`'s wording — it can keep asking for precise framing/pose; only what counts as *passing* review changes, not what's requested.
- Not changing `defect_category` values or the orchestrator's retry-routing logic (`_generate_candidate` in `orchestrator.py`) — these two axes simply won't produce a rejection anymore, so that machinery is exercised less often, not differently.
- Not partial-scene resumability or a video-clip review loop — those are separate, already-identified follow-ups, deliberately out of scope here.
- Not switching image-generation models or adding generation parameters (seed, reference image, etc.) to `GeminiImageAgent` — this fix works entirely on the review side.

## Design

### Three-tier review strictness, up from two

`GeminiReviewAgent`'s prompt (`gemini_review_agent.py`) currently has two tiers: two explicit hard-blocking requirements (perspective/POV consistency, physical/anatomical integrity), and a general "clearly matches the prompt" strictness that everything else — including shot distance and prop orientation — falls under by default.

Add a third, middle tier, inserted immediately after the existing hard-requirements list (see "Placement in the prompt" below for exact position):

```
Two things above are hard requirements, not a matter of degree. Two things
below are approximate, not exact — evaluate them more leniently than
everything else:

1. Shot distance (e.g. extreme close-up vs. medium vs. wide): pass as long
   as the image is in the same broad category as requested — any
   tight/close framing satisfies an extreme-close-up or close-up request,
   any mid-range framing satisfies a medium-shot request, and so on. Reject
   only for a clearly different category (e.g. a wide establishing shot
   when a close-up was requested), not for a shot that is merely tighter
   or looser than the exact label implies.

2. Prop/weapon orientation (e.g. held vertically vs. resting on a
   shoulder): pass as long as the pose is a reasonable, physically
   coherent execution of the general idea — reject only for a starkly
   wrong orientation (e.g. upside-down, pointed at the character, or a
   pose that contradicts the described action), not for an angle that
   simply doesn't match the exact description.

These two are evaluated separately from — and more leniently than — every
other aspect of prompt fidelity (subject appearance, color palette,
setting, everything else), which still needs to clearly match as before.
```

This keeps the existing hard-requirements text (`perspective consistency`, `physical integrity`) and the existing `defect_category` classification instructions completely unchanged — this is a pure insertion, not a rewrite of the surrounding prompt.

### Placement in the prompt

Inserted immediately after the existing "Two things below are hard requirements..." block and before the `defect_category` classification instructions, so the model reads: hard requirements → lenient requirements → general strictness reminder (implicit, via the existing "clearly matches" framing at the top) → defect classification. This ordering mirrors how the hard-requirements block already reads, keeping the prompt's structure consistent rather than introducing a new pattern.

## Testing

Following the existing pattern in `tests/agents/test_gemini_review_agent.py` (e.g. `test_run_calls_sdk_with_hard_perspective_consistency_requirement`, `test_run_calls_sdk_with_hard_physical_integrity_requirement`), which assert specific substrings appear in the prompt text sent to the SDK — not real model output:

- New test asserting the leniency instruction text is present in the prompt (e.g. checks for `"approximate, not exact"`, `"Shot distance"`, `"Prop/weapon orientation"`).
- New test asserting the leniency section explicitly scopes itself as separate from the hard requirements (e.g. checks that both `"hard requirements"` and `"approximate, not exact"` appear, confirming the insertion didn't overwrite or blend into the existing hard-requirements text).
- Existing hard-requirement tests (`test_run_calls_sdk_with_hard_perspective_consistency_requirement`, `test_run_calls_sdk_with_hard_physical_integrity_requirement`, `test_run_calls_sdk_with_defect_category_classification_instructions`) must still pass unchanged — confirms no regression to POV/physical-integrity strictness or defect-category instructions.
- Full existing test suite must still pass (`pytest -v`).

## Open questions / follow-ups (not blocking this spec)

- Whether `gemini-3.1-flash-image`'s actual output is now accepted more often is a real-model question a unit test can't answer either way — optional manual confirmation via a real re-render (same billed-call caveat as every other real-pipeline verification in this project), not a blocking part of this plan.
- If this leniency turns out to be too loose in practice (e.g. shots come back so far off they don't serve the scene despite passing), that's future-tuning work, not something to guess at preemptively here.
