# Wiring video assembly into run_pipeline — design spec

## Context

`src/video_draft_pipeline/assembly.py` already has real ffmpeg-based concatenation logic (`assemble(clip_paths, output_path)`, `build_ffmpeg_concat_command`, `write_concat_list`) — built early (Task list in the original scaffold plan) but never wired into `run_pipeline`. Today the pipeline generates and renders each scene's clip individually (`scene.render.clip_url`) and returns without ever combining them; `Project.output_video_url` is never set anywhere, always `None`.

`assemble()` uses ffmpeg's concat demuxer with stream copy (`ffmpeg -f concat -c copy`) — a pure hard-cut concatenation, no crossfades/blending. This matches this project's actual purpose: per the original project pitch (project #64, "게임 레퍼런스 영상 시안 자동 생성"), this tool generates **시안** (draft/proposal mockups) for internal stakeholder review, replacing a traditional process costing 300-500만원 and 2-3 weeks per video, targeting 90%+ cost/time reduction. It is not a final-cut production tool. Hard cuts between independently-generated clips are both technically simpler and genre-appropriate (marketing trailers are conventionally built from short discontinuous shots) — investing in smooth transitions would over-build relative to what this tool needs to do.

`assemble()` requires a real `ffmpeg` binary on `PATH` and real local clip files, and has essentially no test coverage today (only its two pure helper functions are tested, not `assemble()` itself, which shells out via `subprocess.run`). Wiring it into `run_pipeline` unconditionally would repeat the exact mistake this project already caught and fixed once this session with `VeoBackend`: a fully offline/stubbed pipeline run would try to run real `ffmpeg` against fake `stub://veo/...mp4` paths and crash, breaking the "runs offline unless real agents are explicitly injected" guarantee.

## Goals

- `run_pipeline` can optionally assemble all of a project's rendered scene clips into one final video via ffmpeg concatenation, setting `Project.output_video_url`.
- Assembly is opt-in and off by default — a stubbed/offline `run_pipeline()` call never touches ffmpeg or the filesystem for assembly, exactly like every other real capability in this pipeline.
- The output path has a sensible auto-derived default (under the existing `media/` convention) but is overridable.
- ffmpeg failures (missing binary, bad input) are wrapped into the existing `PipelineError` convention, not left as raw `subprocess` exceptions.

## Non-goals

- Any transition beyond a hard cut (crossfades, wipes, etc.) — explicitly out of scope per the project's own draft-mockup purpose; not needed and not designed here.
- Cross-clip audio treatment (a continuous music bed, ducking, etc.) — each clip's Veo-native baked-in audio just gets concatenated along with the video, exactly as ffmpeg's stream-copy concat already does. A known limitation (audio jump-cuts at each hard cut), not solved here.
- Any change to `assembly.py`'s core ffmpeg command shape (`build_ffmpeg_concat_command`, `write_concat_list`) — only a directory-creation addition to `assemble()` itself.
- Retrying or falling back to an alternate assembly strategy if ffmpeg fails — a failure is a failure, surfaced as `PipelineError`.

## Design

### `assembly.assemble()` — one addition

```python
def assemble(clip_paths: list[str], output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    concat_list_path = str(Path(output_path).with_suffix(".txt"))
    write_concat_list(clip_paths, concat_list_path)
    command = build_ffmpeg_concat_command(clip_paths, output_path)
    subprocess.run(command, check=True)
    return output_path
```

One line added at the top (`Path(output_path).parent.mkdir(parents=True, exist_ok=True)`), matching the same convention `OpenAIImageAgent`/`VeoBackend` already use for their own output directories — `assemble()` no longer assumes its output directory already exists.

### `run_pipeline` threading

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    render_backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
    director_agent: DirectorAgentProtocol | None = None,
    assemble: bool = False,
    assembly_output_path: str | Path | None = None,
) -> Project:
    ...
    # existing scene loop, unchanged, ending with `project.scenes.append(scene)`

    if assemble:
        output_path = str(assembly_output_path) if assembly_output_path else f"media/{project.project_id}.mp4"
        ordered_clip_paths = [
            scene.render.clip_url for scene in sorted(project.scenes, key=lambda s: s.order)
        ]
        try:
            project.output_video_url = assembly.assemble(ordered_clip_paths, output_path)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise PipelineError(
                f"Video assembly failed: {exc}. Is ffmpeg installed and on PATH?"
            ) from exc

    return project
```

`assembly` here is `orchestrator.py`'s new `from . import assembly` module import — distinct from the `assemble: bool` parameter, no naming collision. `assemble` defaults `False`. Clips are explicitly sorted by `scene.order` before concatenation — a cheap robustness measure removing a fragile assumption that `project.scenes`'s append order always matches narrative order (it does today, by construction of the sequential scene loop, but sorting removes the dependency on that always remaining true). Both realistic ffmpeg failure modes are caught: `subprocess.CalledProcessError` (ffmpeg ran, exited non-zero — e.g. a corrupt clip) and `FileNotFoundError` (ffmpeg itself isn't installed), both wrapped into `PipelineError` with a hint about the missing-binary case, since that's the failure someone new to this feature is most likely to hit.

## Testing

- `tests/test_assembly.py`: `assemble()` itself gains coverage for the first time (`monkeypatch` on `subprocess.run` — no real ffmpeg needed): output directory created if missing, `write_concat_list` called with the right content, `subprocess.run` invoked with the exact command `build_ffmpeg_concat_command` would produce, and the function returns `output_path`.
- `tests/test_orchestrator.py`: `assemble=False` (default) — `output_video_url` stays `None`, `assembly.assemble` (mocked) is never called. `assemble=True` — mocked `assembly.assemble` is called with clips ordered by `scene.order` and the default `media/<project_id>.mp4` path; `project.output_video_url` is set to its return value. `assembly_output_path` override — the explicit path is used instead of the default. ffmpeg failure — a mocked `assembly.assemble` raising `subprocess.CalledProcessError` (and separately, `FileNotFoundError`) both surface as `PipelineError`.
- No live-ffmpeg integration test — `assemble()`'s own tests mock `subprocess.run`, consistent with every other real-dependency test in this project (mocked SDK clients, no live API calls).

## Open questions / follow-ups (not blocking this spec)

- Cross-clip audio continuity (a separate music bed, ducking native per-clip audio) — real limitation, deferred; not solved by simple concatenation.
- Whether `assembly_output_path`'s default should ever be configurable via `ModelConfig` rather than a `run_pipeline` kwarg — no evidence yet that this is needed; revisit if it comes up.
