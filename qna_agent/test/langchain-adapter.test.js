import test from 'node:test';
import assert from 'node:assert/strict';
import { LangChainModelAdapter } from '../src/langchain-adapter.js';

test('LangChain 호환 모델의 invoke 결과를 표준 결과로 변환한다', async () => {
  const calls = [];
  const adapter = new LangChainModelAdapter({
    model: {
      async invoke(messages) {
        calls.push(messages);
        return {
          content: '검색 근거를 반영한 답변',
          usage_metadata: { input_tokens: 12, output_tokens: 7 },
        };
      },
    },
  });
  const result = await adapter.generate({
    system: '근거가 없으면 추측하지 않는다.',
    question: '세계관 질문',
    evidence: ['세력 A는 세력 B와 동맹이다.'],
    maxOutputChars: 100,
  });
  assert.equal(result.answer, '검색 근거를 반영한 답변');
  assert.deepEqual(result.usage, { inputTokens: 12, outputTokens: 7 });
  assert.equal(calls[0][0].role, 'system');
  assert.match(calls[0][1].content, /세계관 질문/);
});

test('LangChain 모델 실행 오류는 MODEL_UNAVAILABLE로 변환한다', async () => {
  const adapter = new LangChainModelAdapter({
    model: { async invoke() { throw new Error('provider down'); } },
  });
  await assert.rejects(
    () => adapter.generate({ system: '규칙', question: '질문', evidence: [] }),
    (error) => error.code === 'MODEL_UNAVAILABLE' && error.statusCode === 503,
  );
});
