import assert from "node:assert/strict";
import test from "node:test";
import { normalizeStoryReviewInput, parseStoryText, storyEditorText } from "../src/story-import.ts";

test("keeps a one-line natural-language prompt as story review content", () => {
  const draft = normalizeStoryReviewInput("홍길동 또는 전우치 사망시 2인자 스토리는?", "chat-story.txt");

  assert.deepEqual(draft, {
    name: "스토리 검토 초안",
    keywords: ["스토리 검토"],
    answer: "홍길동 또는 전우치 사망시 2인자 스토리는?",
  });
});

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

test("한 줄 일반 TXT도 전체 내용을 본문으로 보존한다", () => {
  const content = "제 4세력은 실리를 채우려는 활동영역이고, 그 세력에 흡수된 팀은 공공의 적이 된다.";
  const draft = parseStoryText(content, "fourth-faction.txt");

  assert.equal(draft.name, content);
  assert.equal(draft.answer, content);
});

test("TXT 편집창에는 제목을 제외하지 않고 원문 전체를 표시한다", () => {
  const content = "첫 번째 줄\r\n중간 내용\r\n마지막 줄";

  assert.equal(storyEditorText(content), "첫 번째 줄\n중간 내용\n마지막 줄");
});
