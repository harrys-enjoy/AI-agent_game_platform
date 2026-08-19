import assert from "node:assert/strict";
import test from "node:test";
import { extractArtPrompt } from "../src/art-prompt-utils.ts";

test("extractArtPrompt rejects unrelated JSON objects", () => {
  assert.equal(extractArtPrompt('{"question":"전우치","근거":"없음"}'), null);
});

test("extractArtPrompt accepts the Video handoff schema", () => {
  const prompt = extractArtPrompt(JSON.stringify({
    story: "기록 조작 사건",
    character: "전우치",
    context: "권력의 거짓과 대립",
    nearby: ["홍길동", "무명회"],
    prompt: "조선풍 판타지 캐릭터 콘셉트 아트",
  }));
  assert.equal(prompt?.character, "전우치");
});
