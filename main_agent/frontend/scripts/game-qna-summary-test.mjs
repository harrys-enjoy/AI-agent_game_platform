import test from "node:test";
import assert from "node:assert/strict";
import { createRecentGameQnaWork, recentGameQnaWork, reviewSummaryLines, summaryStatusLabel, storyReviewStatus, upsertRecentGameQnaWork } from "../src/game-qna-summary-utils.ts";

test("labels Game Q&A summary statuses", () => {
  assert.equal(summaryStatusLabel("review"), "검토 필요");
  assert.equal(summaryStatusLabel("attention"), "수정 필요");
});

test("summarizes the first story review issues for the dashboard", () => {
  assert.deepEqual(reviewSummaryLines({ continuityConflicts: ["인물의 소속이 충돌함"], suggestions: ["동기를 보강할 것"] }), ["설정 충돌: 인물의 소속이 충돌함", "개선 제안: 동기를 보강할 것"]);
});

test("limits the Story Review 핵심 panel to three concise items", () => {
  const lines = reviewSummaryLines({
    continuityConflicts: ["설정 충돌"],
    timelineIssues: ["시간 순서 누락"],
    characterConsistency: ["동기 불명확"],
    suggestions: ["세력 관계 보완"],
  });

  assert.equal(lines.length, 3);
});

test("derives story review status from the existing review notice", () => {
  assert.equal(storyReviewStatus(null, ""), "pending");
  assert.equal(storyReviewStatus({ verdict: "review_required" }, "Review complete"), "review");
  assert.equal(storyReviewStatus({ verdict: "reject" }, "Review complete"), "attention");
  assert.equal(storyReviewStatus({ verdict: "pass" }, "Review complete"), "approvable");
  assert.equal(storyReviewStatus(null, "Story approved and saved to Catalog."), "complete");
});

test("shows story review as the recent work instead of the art prompt", () => {
  assert.deepEqual(recentGameQnaWork({ verdict: "review_required" }, "Review complete: Review required."), {
    title: "스토리 검토",
    detail: "검토 결과와 핵심 요약을 확인하세요.",
    status: "검토 완료",
    tone: "review",
  });
});

test("uses the latest Game Q&A chat request as recent work", () => {
  const work = createRecentGameQnaWork("/lore 홍길동과 전우치의 갈등을 정리해줘", "완료");

  assert.deepEqual(work, {
    title: "세계관 조회",
    detail: "홍길동과 전우치의 갈등을 정리해줘",
    status: "완료",
    tone: "ready",
  });
});

test("keeps the three most recent Game Q&A chat activities instead of replacing them", () => {
  const history = [
    createRecentGameQnaWork("/art 야간 시장 콘셉트", "완료"),
    createRecentGameQnaWork("/lore 홍길동의 신념", "완료"),
    createRecentGameQnaWork("/catalog 기록 보관소", "완료"),
  ];
  const updated = upsertRecentGameQnaWork(history, createRecentGameQnaWork("/story-review 후인 이야기", "검토 완료"));

  assert.equal(updated.length, 3);
  assert.equal(updated[0].title, "스토리 검토");
  assert.equal(updated[1].title, "아트 프롬프트");
});
