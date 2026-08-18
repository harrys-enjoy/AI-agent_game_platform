import test from "node:test";
import assert from "node:assert/strict";
import { buildUnresolvedScenes, markSceneStatus, mergeResumeResult, buildResumeFormData, finalVideoMessageText } from "../src/resume-utils.ts";

test("builds pending scenes from raw server data", () => {
  const raw = [{ sceneId: "scene_04", imageUrl: "u1", issues: ["too wide"] }];
  assert.deepEqual(buildUnresolvedScenes(raw), [{ ...raw[0], status: "pending" }]);
});

test("marks only the matching scene status", () => {
  const scenes = buildUnresolvedScenes([
    { sceneId: "scene_04", imageUrl: "u1", issues: [] },
    { sceneId: "scene_05", imageUrl: "u2", issues: [] },
  ]);
  const updated = markSceneStatus(scenes, "scene_04", "uploading");
  assert.equal(updated[0].status, "uploading");
  assert.equal(updated[1].status, "pending");
});

test("preserves status for scenes remaining after resume", () => {
  const previous = [{ sceneId: "scene_04", imageUrl: "u1", issues: [], status: "uploading" }];
  const result = { scene_id: "scene_05", resolved: true, remaining_unresolved: [{ sceneId: "scene_04", imageUrl: "u1", issues: [] }], output_video_url: null };
  assert.deepEqual(mergeResumeResult(previous, result), [{ ...result.remaining_unresolved[0], status: "uploading" }]);
});

test("returns an empty scene list when all scenes are resolved", () => {
  const result = { scene_id: "scene_05", resolved: true, remaining_unresolved: [], output_video_url: "video.mp4" };
  assert.deepEqual(mergeResumeResult([], result), []);
});

test("wraps the file in FormData", () => {
  const formData = buildResumeFormData(new File(["fake"], "fixed.png", { type: "image/png" }));
  assert.equal(formData.get("file").name, "fixed.png");
});

test("formats the final video message", () => {
  assert.match(finalVideoMessageText("video.mp4"), /video\.mp4/);
});
