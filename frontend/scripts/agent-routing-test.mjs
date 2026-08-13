import assert from "node:assert/strict";
import { routeAgentRequest } from "../src/agent-routing.ts";

assert.equal(routeAgentRequest("영상 자막을 만들어줘"), "Video Generation");
assert.equal(routeAgentRequest("로그인 버그를 수정해줘"), "Development Assistant");
assert.equal(routeAgentRequest("캐릭터 스토리를 검토해줘"), "Game Q&A");
assert.equal(routeAgentRequest("회의 일정과 할 일을 정리해줘"), "Workmate AI");
assert.equal(routeAgentRequest("오늘 날씨 알려줘"), null);
console.log("agent routing tests passed");
