import test from "node:test";
import assert from "node:assert/strict";
import { extractArtPrompt, formatArtPromptForChat, formatArtPromptJson, parseArtPromptJson } from "../src/art-prompt-utils.ts";

const answer = `[Source: Guide (planning / art)]
{"story":"연화의 선택","character":"연화","context":"중립자","nearby":["전우치","홍길동"]}`;

test("extracts the original art prompt JSON from a Game Q&A answer", () => {
  assert.deepEqual(extractArtPrompt(answer), {
    story: "연화의 선택",
    character: "연화",
    context: "중립자",
    nearby: ["전우치", "홍길동"],
  });
});

test("extracts an art prompt even when the model adds text after its JSON", () => {
  assert.deepEqual(extractArtPrompt(`${answer}\n전송 준비 완료`), {
    story: "연화의 선택",
    character: "연화",
    context: "중립자",
    nearby: ["전우치", "홍길동"],
  });
});

test("formats the stored art prompt as readable Game Q&A guidance", () => {
  assert.match(formatArtPromptForChat(extractArtPrompt(answer)), /스토리 맥락/);
  assert.match(formatArtPromptForChat(extractArtPrompt(answer)), /연화/);
});

test("formats the exact handoff payload as readable indented JSON", () => {
  assert.equal(formatArtPromptJson({ character: "연화", nearby: ["홍길동"] }), '{\n  "character": "연화",\n  "nearby": [\n    "홍길동"\n  ]\n}');
});

test("accepts an edited handoff JSON only when it is an object", () => {
  assert.deepEqual(parseArtPromptJson('{"character":"연화","nearby":["홍길동"]}'), {
    character: "연화",
    nearby: ["홍길동"],
  });
  assert.equal(parseArtPromptJson("[\"not-an-object\"]"), null);
  assert.equal(parseArtPromptJson('{"character":}'), null);
});
