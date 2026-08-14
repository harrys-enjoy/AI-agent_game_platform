import test from "node:test";
import assert from "node:assert/strict";
import { commandCatalog, getCommandInputValue, resolveChatCommand } from "../src/command-utils.ts";

test("Game Q&A help command returns the available specialist commands", () => {
  const result = resolveChatCommand("/?");
  assert.equal(result.kind, "help");
  assert.deepEqual(result.commands, commandCatalog);
});

test("planning command selects dev-guide and removes the command prefix", () => {
  assert.deepEqual(resolveChatCommand("/planning 전투 시스템을 설계해줘"), {
    kind: "request",
    mode: "dev-guide",
    content: "전투 시스템을 설계해줘",
    command: "/planning",
  });
});

test("art command selects dev-guide with a video prompt template", () => {
  const result = resolveChatCommand("/art");
  assert.equal(result.kind, "request");
  assert.equal(result.mode, "dev-guide");
  assert.equal(result.command, "/art");
  assert.match(result.content, /Video Generation/);
});

test("selecting art keeps only the command in the chat input", () => {
  assert.equal(getCommandInputValue("/art"), "/art ");
});

test("/? video stays in Game Q&A as the art prompt guide", () => {
  assert.deepEqual(resolveChatCommand("/? video 캐릭터 등장 장면 프롬프트"), {
    kind: "request",
    mode: "dev-guide",
    content: "캐릭터 등장 장면 프롬프트",
    command: "/art",
  });
});

test("codexbook command selects the codex mode", () => {
  const result = resolveChatCommand("/codexbook 루멘");
  assert.equal(result.kind, "request");
  assert.equal(result.mode, "codex");
  assert.equal(result.command, "/codexbook");
});

test("normal Game Q&A text remains an unchanged lore request", () => {
  assert.deepEqual(resolveChatCommand("전우치와 홍길동의 관계"), {
    kind: "request",
    mode: "lore",
    content: "전우치와 홍길동의 관계",
    command: null,
  });
});

test("story review command selects the Story Review workspace", () => {
  assert.deepEqual(resolveChatCommand("/story-review 기억의 문 초안"), {
    kind: "request",
    mode: "story-review",
    content: "기억의 문 초안",
    command: "/story-review",
  });
});
