import assert from "node:assert/strict";
import { quickActions, readUiVariant } from "../src/ui-variant.ts";
import { selectMenu } from "../src/menu-utils.ts";

assert.equal(readUiVariant("legacy"), "legacy");
assert.equal(readUiVariant("updated"), "updated");
assert.equal(readUiVariant("unknown"), "legacy");
assert.equal(readUiVariant(null), "legacy");
assert.deepEqual(quickActions.map((item) => item.id), ["tasks", "recording", "meetings", "minutes"]);
assert.equal(quickActions.length, 4);
assert.equal(quickActions[0].prompt, "오늘 할 일과 우선순위를 정리해줘");
assert.deepEqual(selectMenu({ type: "section", id: "Policies" }), { activeSection: "Policies", activeChat: null });
assert.deepEqual(selectMenu({ type: "section", id: "Skills" }), { activeSection: "Home", activeChat: null });
console.log("ui variant tests passed");
