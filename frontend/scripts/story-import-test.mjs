import assert from "node:assert/strict";
import test from "node:test";
import { parseStoryText } from "../src/story-import.ts";

test("TXT의 제목·키워드·본문을 스토리 초안으로 변환한다", () => {
  const draft = parseStoryText(
    "Title: The Glass Star\nKeywords: Glass Star, Memory, Harbor\n\nContent:\nThe harbor loses its shared memory.",
    "story.txt",
  );

  assert.deepEqual(draft, {
    name: "The Glass Star",
    keywords: ["Glass Star", "Memory", "Harbor"],
    answer: "The harbor loses its shared memory.",
  });
});

test("헤더가 없는 TXT는 첫 줄을 제목으로 사용한다", () => {
  const draft = parseStoryText("Ashes at Dawn\nThe first bell rings over the harbor.", "ashes.txt");

  assert.equal(draft.name, "Ashes at Dawn");
  assert.deepEqual(draft.keywords, []);
  assert.equal(draft.answer, "The first bell rings over the harbor.");
});
