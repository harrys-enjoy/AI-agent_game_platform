import test from "node:test";
import assert from "node:assert/strict";
import { getPreviewKind } from "../src/preview-utils.ts";

test("classifies supported image files as image previews", () => {
  assert.equal(getPreviewKind("concept.PNG"), "image");
  assert.equal(getPreviewKind("character.webp"), "image");
});

test("classifies supported source files as code previews", () => {
  assert.equal(getPreviewKind("agent.tsx"), "code");
  assert.equal(getPreviewKind("pipeline.py"), "code");
  assert.equal(getPreviewKind("config.json"), "code");
});

test("classifies unknown files as unsupported", () => {
  assert.equal(getPreviewKind("archive.zip"), "unsupported");
});
