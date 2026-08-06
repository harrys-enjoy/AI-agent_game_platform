import test from "node:test";
import assert from "node:assert/strict";
import { selectMenu } from "../src/menu-utils.ts";

test("selects a sidebar section when a navigation item is clicked", () => {
  assert.deepEqual(selectMenu({ type: "section", id: "Roles" }), {
    activeSection: "Roles",
    activeChat: null,
  });
});

test("selects an AI chat without clearing the current section", () => {
  assert.deepEqual(selectMenu({ type: "chat", id: "Game Q&A" }, "Home"), {
    activeSection: "Home",
    activeChat: "Game Q&A",
  });
});
