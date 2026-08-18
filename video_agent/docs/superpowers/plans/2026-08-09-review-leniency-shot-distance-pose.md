# Review Leniency for Shot Distance and Prop Orientation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `GeminiReviewAgent` from rejecting scenes over imprecise-but-reasonable shot distance or prop orientation, while keeping POV-mixing and physical/anatomical-integrity rejections exactly as strict as they are today.

**Architecture:** Insert one new instruction block into `GeminiReviewAgent`'s existing review prompt (`gemini_review_agent.py`), between the current hard-requirements list and the defect-category classification instructions. No schema, orchestrator, or other-agent changes.

**Tech Stack:** Python, pytest, `unittest.mock.MagicMock` (existing test conventions in this codebase — no new dependencies).

## Global Constraints

- The new instruction block's wording must appear verbatim as specified in this plan — later tests assert on exact substrings.
- The existing hard-requirements text (perspective consistency, physical integrity) and the existing `defect_category` classification instructions must remain byte-for-byte unchanged.
- No changes outside `src/video_draft_pipeline/agents/gemini_review_agent.py` and its test file.
- Spec: `docs/superpowers/specs/2026-08-09-review-leniency-shot-distance-pose-design.md`.

---

### Task 1: Add the leniency instruction block to `GeminiReviewAgent`'s prompt

**Files:**
- Modify: `src/video_draft_pipeline/agents/gemini_review_agent.py:44-75` (the `input_content` text block inside `GeminiReviewAgent.run`)
- Test: `tests/agents/test_gemini_review_agent.py`

**Interfaces:**
- Consumes: `GeminiReviewAgent(client=...)`, `Candidate`, `Prompts` (all existing, unchanged signatures)
- Produces: no new public interface — this task only changes prompt text sent to the SDK; `ConsistencyReview`'s shape and `GeminiReviewAgent.run()`'s signature are unchanged

- [ ] **Step 1: Write the failing tests**

Append to `tests/agents/test_gemini_review_agent.py` (uses the file's existing `_fake_interaction` helper, already defined above the existing hard-requirement tests):

```python
def test_run_calls_sdk_with_lenient_shot_distance_and_prop_orientation_guidance(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"passed": true, "issues": []}')
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prior_candidates=[], prompts=prompts)

    _, kwargs = client.interactions.create.call_args
    text = kwargs["input"][0]["text"]
    assert "approximate, not exact" in text
    assert "Shot distance" in text
    assert "Prop/weapon orientation" in text


def test_run_calls_sdk_with_lenient_section_kept_separate_from_hard_requirements(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"passed": true, "issues": []}')
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prior_candidates=[], prompts=prompts)

    _, kwargs = client.interactions.create.call_args
    text = kwargs["input"][0]["text"]
    assert "hard requirements" in text
    assert "approximate, not exact" in text
    assert text.index("hard requirements") < text.index("approximate, not exact")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_gemini_review_agent.py::test_run_calls_sdk_with_lenient_shot_distance_and_prop_orientation_guidance tests/agents/test_gemini_review_agent.py::test_run_calls_sdk_with_lenient_section_kept_separate_from_hard_requirements -v`
Expected: FAIL — `AssertionError: assert 'approximate, not exact' in ...` (the current prompt text has no such phrase yet)

- [ ] **Step 3: Insert the leniency instruction block into the prompt**

In `src/video_draft_pipeline/agents/gemini_review_agent.py`, the `run()` method currently builds `input_content` with this text block (lines 44-75):

```python
                "text": (
                    "You are reviewing an AI-generated image for a game marketing video scene. "
                    f"The image was generated from this prompt: {prompts.image_prompt}\n"
                    "Judge whether the image faithfully matches the prompt. Respond with passed=true "
                    "only if the image clearly matches; otherwise passed=false and list concrete issues.\n\n"
                    "Two things below are hard requirements, not a matter of degree — treat "
                    "either one as a blocking failure even if it seems partial or 'slight', and "
                    "never pass an image with a known instance of either just because it is "
                    "otherwise a strong match for the prompt.\n\n"
                    "1. Perspective consistency: if the prompt specifies a first-person/"
                    "point-of-view shot, any visible face, helmet, or full body of the subject "
                    "that would not be visible from their own eyes is a blocking issue.\n\n"
                    "2. Physical integrity: any equipment, weapon, vehicle, or other rigid "
                    "object must read as one coherent, continuous physical object — reject it if "
                    "it appears bent, kinked, melted, or disconnected in a way that would not "
                    "hold together in reality. Likewise reject malformed anatomy — extra or "
                    "missing fingers, warped joints, or limbs merging unnaturally into held "
                    "objects or equipment.\n\n"
                    "If passed=false, also classify what kind of fix the defect needs, as "
                    "defect_category:\n"
                    "- 'localized_artifact': the image is otherwise correct and the problem is "
                    "confined to one small, isolated region (a stray mark, a texture glitch, a "
                    "small wrong detail) that could be fixed by editing just that region without "
                    "touching the rest of the image.\n"
                    "- 'structural_geometry': the defect is load-bearing on how the whole image "
                    "was composed — a bent or kinked or disconnected object, malformed anatomy, "
                    "perspective/POV mixing, or a subject/setting mismatch. Editing one region "
                    "cannot fix this; the image needs to be regenerated from scratch.\n"
                    "If passed=true, use defect_category='none'. When genuinely unsure whether an "
                    "issue is localized or structural, choose 'structural_geometry' — it is the "
                    "safer default."
                ),
```

Replace it with (the only change is the new block inserted after the physical-integrity paragraph and before "If passed=false, also classify..."):

```python
                "text": (
                    "You are reviewing an AI-generated image for a game marketing video scene. "
                    f"The image was generated from this prompt: {prompts.image_prompt}\n"
                    "Judge whether the image faithfully matches the prompt. Respond with passed=true "
                    "only if the image clearly matches; otherwise passed=false and list concrete issues.\n\n"
                    "Two things below are hard requirements, not a matter of degree — treat "
                    "either one as a blocking failure even if it seems partial or 'slight', and "
                    "never pass an image with a known instance of either just because it is "
                    "otherwise a strong match for the prompt.\n\n"
                    "1. Perspective consistency: if the prompt specifies a first-person/"
                    "point-of-view shot, any visible face, helmet, or full body of the subject "
                    "that would not be visible from their own eyes is a blocking issue.\n\n"
                    "2. Physical integrity: any equipment, weapon, vehicle, or other rigid "
                    "object must read as one coherent, continuous physical object — reject it if "
                    "it appears bent, kinked, melted, or disconnected in a way that would not "
                    "hold together in reality. Likewise reject malformed anatomy — extra or "
                    "missing fingers, warped joints, or limbs merging unnaturally into held "
                    "objects or equipment.\n\n"
                    "Two things above are hard requirements, not a matter of degree. Two "
                    "things below are approximate, not exact — evaluate them more leniently "
                    "than everything else.\n\n"
                    "1. Shot distance (e.g. extreme close-up vs. medium vs. wide): pass as "
                    "long as the image is in the same broad category as requested — any "
                    "tight/close framing satisfies an extreme-close-up or close-up request, "
                    "any mid-range framing satisfies a medium-shot request, and so on. Reject "
                    "only for a clearly different category (e.g. a wide establishing shot "
                    "when a close-up was requested), not for a shot that is merely tighter or "
                    "looser than the exact label implies.\n\n"
                    "2. Prop/weapon orientation (e.g. held vertically vs. resting on a "
                    "shoulder): pass as long as the pose is a reasonable, physically coherent "
                    "execution of the general idea — reject only for a starkly wrong "
                    "orientation (e.g. upside-down, pointed at the character, or a pose that "
                    "contradicts the described action), not for an angle that simply doesn't "
                    "match the exact description.\n\n"
                    "These two are evaluated separately from — and more leniently than — "
                    "every other aspect of prompt fidelity (subject appearance, color "
                    "palette, setting, everything else), which still needs to clearly match "
                    "as before.\n\n"
                    "If passed=false, also classify what kind of fix the defect needs, as "
                    "defect_category:\n"
                    "- 'localized_artifact': the image is otherwise correct and the problem is "
                    "confined to one small, isolated region (a stray mark, a texture glitch, a "
                    "small wrong detail) that could be fixed by editing just that region without "
                    "touching the rest of the image.\n"
                    "- 'structural_geometry': the defect is load-bearing on how the whole image "
                    "was composed — a bent or kinked or disconnected object, malformed anatomy, "
                    "perspective/POV mixing, or a subject/setting mismatch. Editing one region "
                    "cannot fix this; the image needs to be regenerated from scratch.\n"
                    "If passed=true, use defect_category='none'. When genuinely unsure whether an "
                    "issue is localized or structural, choose 'structural_geometry' — it is the "
                    "safer default."
                ),
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/agents/test_gemini_review_agent.py::test_run_calls_sdk_with_lenient_shot_distance_and_prop_orientation_guidance tests/agents/test_gemini_review_agent.py::test_run_calls_sdk_with_lenient_section_kept_separate_from_hard_requirements -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the existing hard-requirement tests to confirm no regression**

Run: `pytest tests/agents/test_gemini_review_agent.py -v`
Expected: PASS (all tests in the file, including `test_run_calls_sdk_with_hard_perspective_consistency_requirement`, `test_run_calls_sdk_with_hard_physical_integrity_requirement`, and `test_run_calls_sdk_with_defect_category_classification_instructions` — unchanged since their asserted substrings are still present verbatim in the new text)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS (every test in `tests/`, no regressions anywhere else — this change only touches one prompt string)

- [ ] **Step 7: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_review_agent.py tests/agents/test_gemini_review_agent.py
git commit -m "fix: let review agent pass reasonable-but-imprecise shot distance and prop orientation"
```

## Self-Review

**Spec coverage:**
- Three-tier review strictness (hard requirements unchanged, new lenient middle tier, general strictness for everything else) → Task 1, Step 3. ✓
- Exact insertion placement (after hard requirements, before defect_category instructions) → Task 1, Step 3, and verified by Step 1's ordering test. ✓
- Non-goals (no `GeminiPromptAgent` changes, no `defect_category`/orchestrator changes, no schema changes) → not touched anywhere in this plan. ✓
- Testing per spec (new substring tests matching existing test-file conventions, existing hard-requirement tests still pass, full suite passes) → Steps 1, 2, 4, 5, 6. ✓
- Real-model validation explicitly called out in the spec as optional/non-blocking → correctly not included as a plan step.

**Placeholder scan:** no TBD/TODO; the full before/after prompt text is written out verbatim in Step 3, not summarized.

**Type consistency:** no new types or signatures introduced — `GeminiReviewAgent.run()`, `ConsistencyReview`, `Candidate`, `Prompts` are all used exactly as they exist today, matching every other test in the file.
