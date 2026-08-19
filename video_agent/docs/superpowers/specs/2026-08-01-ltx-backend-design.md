# LTXBackend — real render backend, replacing the SelfHostedBackend stub

## Context

`SelfHostedBackend` (`render_backends/selfhosted_backend.py`) has been a stub since the original scaffold (2026-07-28) — its `endpoint_url` constructor param and the test file's example value (`https://example-tunnel.ngrok.app`) confirm the original intent was a self-hosted open-weight model exposed via an ngrok tunnel (e.g. from Google Colab). Given real deadline pressure on this bootcamp project, and that self-hosting + quantizing an open video/audio diffusion model is a substantially bigger undertaking, the user is deferring that path and instead wiring up LTX 2.3 (`api.ltx.io`) — a hosted, cost-effective video-generation API that also generates audio in the same call — as the real backend for now. Real self-hosting remains a separate future exercise, not abandoned, just not blocking this project's deadline.

Real API docs sourced directly from `docs.ltx.io` (pasted by the user 2026-08-01): the `image-to-video`, `text-to-video`, `retake`, `extend`, and `video-to-video-reframe` endpoints, the `Input Formats` reference, and the `Pricing` page.

## Goals

- Replace the stub with a real `LTXBackend` implementing the existing `RenderBackend` protocol (`render_backends/base.py`) — no changes to that protocol or to `VideoRenderAgent`/`beat_backend_map`'s calling convention.
- Rename throughout: `SelfHostedBackend` → `LTXBackend`, `render_backends/selfhosted_backend.py` → `render_backends/ltx_backend.py`, `tests/render_backends/test_selfhosted_backend.py` → `tests/render_backends/test_ltx_backend.py`.
- Real, accurate cost accounting via `budget_guard` — no guessed pricing.

## Non-goals

- True self-hosting (open-weight model + quantization + manual audio sync) — explicitly deferred, tracked as a separate future exercise, not part of this spec.
- Supporting LTX's other endpoints (`retake`, `extend`, `reframe`, `text-to-video`) — this pipeline only ever renders from an already-generated scene image, so only `image-to-video` is relevant.
- The async `v2/image-to-video` endpoint — deliberately not used; see Design below.

## Design

### Endpoint choice: sync `v1/image-to-video`, not async `v2`

`POST https://api.ltx.io/v1/image-to-video` blocks until the video is generated and returns the raw video bytes directly in the response body — no job-polling loop needed, unlike `VeoBackend`'s real Veo integration (`_poll_until_done`, `render_backends/veo_backend.py:103-107`), which uses Google's async operations API. Chosen deliberately for `LTXBackend` specifically: `ltx-2-3-fast` (this backend's default model) is a lower-latency tier by design, and it's paired against the more critical climax/resolution beats via `VeoBackend` in `beat_backend_map` — so the extra async+polling complexity is judged not worth it here. Known risk, accepted: a slow generation could hit an HTTP client timeout with no LTX-published latency figures to rule that out; if this becomes a real problem, swapping to `v2` only touches `LTXBackend`'s internals, not the rest of the pipeline, since both implement the same `RenderBackend` protocol.

### Image input: base64 data URI, not a hosted URL

Per LTX's `Input Formats` docs, `image_uri` accepts `data:{mime-type};base64,{data}` inline (images up to 7MB encoded), so `LTXBackend.render()` reads the accepted candidate's local image file and base64-encodes it directly — the same pattern `GeminiImageEditAgent`/`GeminiReviewAgent` already use for their own image inputs. No image-hosting infrastructure needed.

### Request/response shape

```python
POST https://api.ltx.io/v1/image-to-video
Headers: {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
Body: {
    "image_uri": f"data:image/png;base64,{b64_image}",
    "prompt": motion_prompt,
    "model": self.model,          # default "ltx-2-3-fast"
    "duration": round(duration_sec),
    "resolution": self.resolution,  # default "1920x1080"
    "generate_audio": True,
}
```

Response: raw video bytes in the body (not JSON) — written to `output_dir/{candidate_id}.mp4`, matching `VeoBackend`'s output-file convention (`self.output_dir / f"{candidate.candidate_id}.mp4"`).

### Pricing

From LTX's real pricing page, `image-to-video` costs (per second of output):

| Model | Resolution | $/sec |
|---|---|---|
| `ltx-2-3-fast` | 1920x1080 / 1080x1920 | 0.06 |
| `ltx-2-3-fast` | 2560x1440 / 1440x2560 | 0.12 |
| `ltx-2-3-fast` | 3840x2160 / 2160x3840 | 0.24 |
| `ltx-2-3-pro` | 1920x1080 / 1080x1920 | 0.08 |
| `ltx-2-3-pro` | 2560x1440 / 1440x2560 | 0.16 |
| `ltx-2-3-pro` | 3840x2160 / 2160x3840 | 0.32 |

`PRICE_PER_SEC_USD: dict[str, dict[str, float]]` keyed `[model][resolution]`. Default `model="ltx-2-3-fast"`, `resolution="1920x1080"` — the cheapest documented combination, appropriate for this backend's role as the cheap-tier option in `beat_backend_map`. Unknown model/resolution combo raises `ValueError`, matching `VeoBackend`'s unknown-tier handling.

**Naming note**: `beat_backend_map(paid_backend, free_backend)`'s `free_backend` parameter name (`agents/video_render_agent.py:42`) predates this change and was accurate when `SelfHostedBackend.estimate_cost()` returned a hardcoded `0.0`. `LTXBackend` is not actually free ($0.06+/sec) — the parameter name becomes a slight misnomer, but nothing in `beat_backend_map`'s logic assumes zero cost (it's just a dict-building convenience function), so this is a documentation/naming accuracy issue, not a functional one. Not fixed as part of this spec — flagged for later.

### Auth

New `LTX_API_KEY` env var (LTX is not in Elice's catalog, so this is a real, separately-billed key — same pattern as `VEO_API_KEY`, not the Elice-proxied `base_url_config_field` pattern the OpenAI/Gemini/Nemotron agents use). Added to `config.ApiKeys`/`load_api_keys()` and `.env.example`.

### New dependency

`requests` — LTX's docs show plain REST calls with no Python SDK, unlike OpenAI/Gemini/Veo which are all backed by an SDK already in `pyproject.toml`. Add `requests>=2.31` to `[project.dependencies]`.

### Schema change

`schema.RenderBackendName` (`Literal["veo-3.1-lite", "veo-3.1-fast", "veo-3.1-standard", "self-hosted"]`) drops `"self-hosted"` in favor of `"ltx-2-3-fast"` and `"ltx-2-3-pro"` — matching how Veo's tiers are literal model identifiers, not a generic label. `LTXBackend.name`/`RenderResult.backend` is set to `self.model` (mirroring `VeoBackend.name = tier`).

### Error handling

A new `LTXBackendError(Exception)`. Wraps: unreadable/missing candidate image (`OSError`, with the same "requires a real image file, stub ImageAgent won't work" hint `VeoBackend` already gives), non-2xx HTTP response, and any `requests` exception (connection error, timeout). Mirrors `VeoBackend.render()`'s try/except structure.

## Testing

- `tests/render_backends/test_ltx_backend.py` (renamed from `test_selfhosted_backend.py`): mock `requests.post` (no live HTTP calls, matching this project's established convention) — successful render (correct URL, headers, base64 payload, writes returned bytes to `output_dir/{candidate_id}.mp4`, returns matching `RenderResult`), missing/unreadable image raises `LTXBackendError`, non-200 response raises `LTXBackendError`, `requests` exception raises `LTXBackendError`, `estimate_cost()` for at least two of the six pricing combinations, unknown model/resolution raises `ValueError`.
- `tests/test_config.py`: `LTX_API_KEY` coverage, matching the existing `VEO_API_KEY` test.
- `tests/agents/test_video_render_agent.py`/`tests/test_orchestrator.py`: existing tests referencing `SelfHostedBackend` (if any) updated to `LTXBackend`.

## Open questions / follow-ups (not blocking this spec)

- Real self-hosted open-weight model + quantization — deferred, tracked as a future learning exercise per the user's stated intent.
- `beat_backend_map`'s `free_backend` parameter naming no longer being literally accurate — flagged, not fixed here.
- No confirmed max/min duration range from LTX's "Supported Models" reference page (not provided) — `duration` is passed as `round(scene.duration_sec)` with no client-side range validation; an out-of-range value will surface as a `422` from LTX, wrapped into `LTXBackendError` same as any other API error.
