import test from "node:test";
import assert from "node:assert/strict";
import { createTask, updateTask, createTaskProposal, isTaskRequest, getTaskAction, createChatReply, shouldApplyChatResponse } from "../src/task-utils.ts";

test("creates a ready task from a non-empty task name", () => {
  assert.deepEqual(createTask("Review combat balance", "Development Assistant", "task-4"), {
    id: "task-4",
    name: "Review combat balance",
    owner: "You",
    status: "Ready to start",
    agent: "Development Assistant",
  });
});

test("does not create a task when the task name is empty", () => {
  assert.equal(createTask("   ", "Workmate AI", "task-5"), null);
});

test("updates owner, status, and agent without changing the task id", () => {
  const original = { id: "task-1", name: "Review combat balance", owner: "You", status: "Ready to start", agent: "Workmate AI" };
  assert.deepEqual(updateTask(original, { owner: "PW", status: "In Progress", agent: "Development Assistant" }), {
    ...original,
    owner: "PW",
    status: "In Progress",
    agent: "Development Assistant",
  });
});

test("detects task creation intent without treating a normal question as a task", () => {
  assert.equal(isTaskRequest("영상 생성 작업을 추가해줘"), true);
  assert.equal(isTaskRequest("게임 캐릭터 스킬이 뭐야?"), false);
});

test("builds a task proposal with the matching specialist agent", () => {
  assert.deepEqual(createTaskProposal("PR 변경사항 검토 일정 추가해줘", "proposal-1"), {
    id: "proposal-1",
    name: "PR 변경사항 검토 일정 추가해줘",
    owner: "You",
    status: "Ready to start",
    agent: "Development Assistant",
  });
});

test("never auto-adds a normal chat message to Project Task", () => {
  assert.equal(getTaskAction("홍길동 설명"), "chat");
});

test("asks for confirmation before adding an explicit task request", () => {
  assert.equal(getTaskAction("영상 생성 작업을 Task에 추가해줘"), "confirm");
});

test("returns a visible reply for a normal chat message", () => {
  assert.match(createChatReply("홍길동"), /홍길동/);
});

test("does not apply a delayed response to a different selected chat", () => {
  assert.equal(shouldApplyChatResponse("Game Q&A", "Workmate AI"), false);
  assert.equal(shouldApplyChatResponse("Game Q&A", "Game Q&A"), true);
});
