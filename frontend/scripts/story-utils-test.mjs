import assert from "node:assert/strict";
import { buildStoryDraft, canApproveStory, reviewLabel } from "../src/story-review-utils.ts";

const draft = buildStoryDraft(" 새 이야기 ", "연화, 기록", " 본문 ");
assert.deepEqual(draft, { name: "새 이야기", keywords: ["연화", "기록"], answer: "본문", relatedLoreIds: [], relatedCodexIds: [] });
assert.equal(canApproveStory({ verdict: "pass", approvalRequired: false }), true);
assert.equal(canApproveStory({ verdict: "review_required" }), false);
assert.equal(reviewLabel({ verdict: "reject" }), "Rejected");
console.log("story-utils tests passed");
