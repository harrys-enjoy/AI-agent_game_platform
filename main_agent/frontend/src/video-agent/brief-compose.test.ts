import { describe, expect, it } from "vitest";
import { composeStructuredBrief } from "./brief-compose";

// Mirrors brief_intake.py's _DURATION_RE / _BUDGET_RE exactly.
const DURATION_RE = /(\d+)\s*초/;
const BUDGET_RE = /(\d+(?:\.\d+)?)\s*(?:달러|\$|usd)/i;

describe("composeStructuredBrief", () => {
  it("always includes the raw brief text", () => {
    const sentence = composeStructuredBrief({ brief: "할로윈 신규 캐릭터 공개" });
    expect(sentence).toContain("할로윈 신규 캐릭터 공개");
  });

  it("encodes duration so brief_intake.py's duration regex matches", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", durationSec: 15 });
    const match = sentence.match(DURATION_RE);
    expect(match?.[1]).toBe("15");
  });

  it("encodes budget so brief_intake.py's budget regex matches", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", maxBudgetUsd: 3.5 });
    const match = sentence.match(BUDGET_RE);
    expect(match?.[1]).toBe("3.5");
  });

  it("includes a literal preset keyword brief_intake.py recognizes", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", preset: "이벤트" });
    expect(sentence).toContain("이벤트");
  });

  it("includes a literal scene_type keyword brief_intake.py recognizes", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", sceneType: "인게임" });
    expect(sentence).toContain("인게임");
  });

  it("composes all fields together and every field still matches", () => {
    const sentence = composeStructuredBrief({
      brief: "할로윈 이벤트",
      durationSec: 20,
      preset: "공개",
      sceneType: "스튜디오",
      maxBudgetUsd: 4,
    });
    expect(sentence.match(DURATION_RE)?.[1]).toBe("20");
    expect(sentence.match(BUDGET_RE)?.[1]).toBe("4");
    expect(sentence).toContain("공개");
    expect(sentence).toContain("스튜디오");
  });

  it("omits optional fields entirely when not provided", () => {
    const sentence = composeStructuredBrief({ brief: "테스트" });
    expect(sentence.match(DURATION_RE)).toBeNull();
    expect(sentence.match(BUDGET_RE)).toBeNull();
  });

  it("extracts structured durationSec, not substring from brief text", () => {
    const sentence = composeStructuredBrief({
      brief: "30초 정도 홍보 영상 부탁해요",
      durationSec: 60,
    });
    const match = sentence.match(DURATION_RE);
    expect(match?.[1]).toBe("60");
  });

  it("rounds non-integer durationSec before encoding", () => {
    const sentence = composeStructuredBrief({ brief: "테스트", durationSec: 15.5 });
    const match = sentence.match(DURATION_RE);
    expect(match?.[1]).toBe("16");
  });

  it("includes zero values for durationSec and maxBudgetUsd", () => {
    const sentence = composeStructuredBrief({
      brief: "테스트",
      durationSec: 0,
      maxBudgetUsd: 0,
    });
    expect(sentence.match(DURATION_RE)?.[1]).toBe("0");
    expect(sentence.match(BUDGET_RE)?.[1]).toBe("0");
  });
});
