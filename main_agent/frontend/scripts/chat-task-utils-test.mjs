import test from "node:test";
import assert from "node:assert/strict";
import { normalizeAgentWorkTasks, syncGameQnaStoryReviewTask } from "../src/chat-task-utils.ts";

test("removes saved Story Review sub-items when agent work is restored", () => {
  assert.deepEqual(normalizeAgentWorkTasks([
    { id: "story-review-1", chat: "Game Q&A", title: "스토리 검토", status: "done", hidden: false },
    { id: "game-qna-1", chat: "Game Q&A", title: "Game Q&A 작업", status: "done", hidden: false },
  ]), [
    { id: "game-qna-1", chat: "Game Q&A", title: "Game Q&A 작업", status: "done", hidden: false },
  ]);
});

test("merges story review progress into the Game Q&A agent work item", () => {
  const tasks = syncGameQnaStoryReviewTask([
    { id: "story-review-1", chat: "Game Q&A", title: "스토리 검토", status: "working", hidden: false },
    { id: "video-1", chat: "Video Generation", title: "Video Generation 작업", status: "done", hidden: false },
  ], "done", "game-qna-1");

  assert.deepEqual(tasks, [
    { id: "video-1", chat: "Video Generation", title: "Video Generation 작업", status: "done", hidden: false },
    { id: "game-qna-1", chat: "Game Q&A", title: "Game Q&A 작업", status: "done", hidden: false },
  ]);
});
