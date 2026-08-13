import assert from "node:assert/strict";
import test from "node:test";
import { shouldShowCodePreview } from "../src/preview-mode.ts";

test("Game Q&A에서는 ADD CODE 미리보기를 표시하지 않는다", () => {
  assert.equal(shouldShowCodePreview(true), false);
});

test("다른 Agent 화면에서는 ADD CODE 미리보기를 유지한다", () => {
  assert.equal(shouldShowCodePreview(false), true);
});
