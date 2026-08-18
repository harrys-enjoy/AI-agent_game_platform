import assert from "node:assert/strict";
import test from "node:test";
import { scrollChatToBottom } from "../src/chat-scroll.ts";

test("scrollChatToBottom moves the chat viewport to the latest message", () => {
  const viewport = { scrollTop: 0, scrollHeight: 860 };
  scrollChatToBottom(viewport);
  assert.equal(viewport.scrollTop, 860);
});
