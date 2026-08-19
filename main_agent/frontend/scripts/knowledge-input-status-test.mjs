import assert from "node:assert/strict";
import test from "node:test";
import { getKnowledgeInputStatus } from "../src/knowledge-input-status.ts";

test("shows upload waiting before a story is loaded", () => {
  assert.deepEqual(getKnowledgeInputStatus({}), { label: "업로드 대기", progress: 0 });
});

test("shows review progress while a story is being checked", () => {
  assert.deepEqual(getKnowledgeInputStatus({ hasDraft: true, isReviewing: true }), { label: "검토 중", progress: 50 });
});

test("shows Catalog completion after approval", () => {
  assert.deepEqual(getKnowledgeInputStatus({ notice: "Story approved and saved to Catalog." }), { label: "반영 완료", progress: 100 });
});
