import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createStoryReviewService } from '../src/story-review.js';
import { MockModelAdapter } from '../src/model.js';

const draft = {
  name: '새로운 항로의 기록',
  keywords: ['새로운 항로', '기록'],
  answer: '연화가 사라진 항로의 기록을 발견한다.',
  relatedLoreIds: ['glass-star-origin'],
  relatedCodexIds: ['yeonhwa-codex'],
};

test('LLM review extracts JSON when the model wraps it in prose and a code fence', async () => {
  const service = createStoryReviewService({
    modelAdapter: { async generate() { return { answer: '검토 결과입니다.\n```json\n{"verdict":"pass","suggestions":[]}\n```' }; } },
    listKnowledge: () => [],
  });
  const result = await service.review({ name: 'Story', keywords: ['story'], answer: 'A story.' });
  assert.equal(result.verdict, 'pass');
});

test('LLM review preserves a useful prose review when structured output fails', async () => {
  const prose = '후인의 목표와 홍길동의 기존 신념이 어떻게 충돌하는지 구체화해 주세요.';
  const service = createStoryReviewService({
    modelAdapter: { async generate() { return { answer: prose }; } },
    listKnowledge: () => [],
  });
  const result = await service.review({ name: 'Story', keywords: ['story'], answer: 'A story idea.' });
  assert.equal(result.verdict, 'review_required');
  assert.deepEqual(result.suggestions, [prose]);
});

test('근거가 부족한 Mock 검토는 review_required이며 승인하지 않는다', async () => {
  const service = createStoryReviewService({ modelAdapter: new MockModelAdapter(), listKnowledge: () => [] });
  const result = await service.review(draft);
  assert.equal(result.verdict, 'review_required');
  assert.throws(() => service.approve(result.reviewId, draft), (error) => error.code === 'STORY_REVIEW_REQUIRED');
});

test('approved pass review is persisted', async () => {
  const storyPath = join(mkdtempSync(join(tmpdir(), 'story-review-')), 'reviewed-stories.json');
  const service = createStoryReviewService({
    modelAdapter: { async generate() { return { answer: JSON.stringify({ verdict: 'pass' }) }; } },
    listKnowledge: () => [],
    storyPath,
  });
  const draft = { name: '새 사건', keywords: ['새 사건'], answer: '기록' };
  const result = await service.review(draft);
  const saved = service.approve(result.reviewId, draft);
  assert.equal(saved.status, 'saved');
  assert.equal(JSON.parse(readFileSync(storyPath, 'utf8')).length, 1);
});
