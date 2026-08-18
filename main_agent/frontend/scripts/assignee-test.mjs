import assert from "node:assert/strict";
import { assigneeOptions, findAssignee } from "../src/assignee.ts";

assert.deepEqual(assigneeOptions.map((item) => item.name), ["서선정", "배동우", "이승현", "변해훈"]);
assert.equal(findAssignee("서선정").chat, "Workmate AI");
assert.equal(findAssignee("배동우").chat, "Video Generation");
assert.equal(findAssignee("이승현").chat, "Development Assistant");
assert.equal(findAssignee("변해훈").chat, "Game Q&A");
assert.equal(findAssignee("삭제된 담당자").name, "서선정");
console.log("assignee tests passed");
