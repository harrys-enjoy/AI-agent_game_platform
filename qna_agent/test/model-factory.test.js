import test from 'node:test';
import assert from 'node:assert/strict';
import { createModelAdapterFromEnv } from '../src/model-factory.js';

test('Qwen 환경변수로 OpenAI 호환 모델 어댑터를 만든다', async () => {
  let call;
  const adapter = createModelAdapterFromEnv({
    env: {
      MODEL_PROVIDER: 'qwen',
      MODEL_NAME: 'Qwen/Qwen3-Next-80B-A3B-Instruct',
      MODEL_BASE_URL: 'https://qwen.example/v1',
      MODEL_API_KEY: 'test-key',
    },
    fetchImpl: async (url, options) => {
      call = { url, options };
      return new Response(JSON.stringify({
        choices: [{ message: { content: 'Qwen 답변' } }],
        usage: { prompt_tokens: 10, completion_tokens: 4 },
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    },
  });
  const result = await adapter.generate({ system: '규칙', question: '질문', evidence: [] });
  assert.equal(result.answer, 'Qwen 답변');
  assert.deepEqual(result.usage, { inputTokens: 10, outputTokens: 4 });
  assert.equal(call.url, 'https://qwen.example/v1/chat/completions');
  assert.equal(call.options.headers.authorization, 'Bearer test-key');
});

test('모델 환경변수가 없으면 Mock 어댑터를 사용한다', () => {
  const adapter = createModelAdapterFromEnv({ env: {} });
  assert.equal(adapter.constructor.name, 'MockModelAdapter');
});

test('모델 timeout을 초과하면 MODEL_UNAVAILABLE을 반환한다', async () => {
  let receivedSignal;
  const adapter = createModelAdapterFromEnv({
    env: {
      MODEL_PROVIDER: 'qwen', MODEL_NAME: 'qwen-test', MODEL_BASE_URL: 'https://qwen.example/v1',
      MODEL_API_KEY: 'test-key', MODEL_TIMEOUT_MS: '1',
    },
    fetchImpl: async (_url, options) => new Promise((resolve, reject) => {
      receivedSignal = options.signal;
      options.signal.addEventListener('abort', () => reject(new Error('timeout')));
    }),
  });
  await assert.rejects(
    () => adapter.generate({ system: '규칙', question: '질문', evidence: [] }),
    (error) => error.code === 'MODEL_UNAVAILABLE' && error.statusCode === 503,
  );
  assert.equal(receivedSignal instanceof AbortSignal, true);
});

test('MODEL_PROVIDER가 elice여도 OpenAI 호환 포맷으로 호출한다', async () => {
  let call;
  const adapter = createModelAdapterFromEnv({
    env: {
      MODEL_PROVIDER: 'elice',
      MODEL_NAME: 'elice-test',
      MODEL_BASE_URL: 'https://mlapi.run/e9a5f41b-fdda-44f2-9545-ed88c458da53',
      MODEL_API_KEY: 'test-key',
    },
    fetchImpl: async (url, options) => {
      call = { url, options };
      return new Response(JSON.stringify({
        choices: [{ message: { content: 'Elice 답변' } }],
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    },
  });
  const result = await adapter.generate({ system: '규칙', question: '질문', evidence: [] });
  assert.equal(result.answer, 'Elice 답변');
  assert.equal(call.url, 'https://mlapi.run/e9a5f41b-fdda-44f2-9545-ed88c458da53/chat/completions');
  assert.equal(call.options.headers.authorization, 'Bearer test-key');
});

test('모델 환경변수가 일부만 설정되면 명확한 설정 오류를 반환한다', () => {
  assert.throws(
    () => createModelAdapterFromEnv({
      env: { MODEL_NAME: 'qwen-test', MODEL_BASE_URL: 'https://qwen.example/v1' },
    }),
    (error) => error.code === 'MODEL_CONFIG_INVALID' && error.statusCode === 500,
  );
});

test('QWEN_BASE_URL도 OpenAI 호환 모델 endpoint로 사용한다', async () => {
  let calledUrl;
  const adapter = createModelAdapterFromEnv({
    env: {
      MODEL_NAME: 'Qwen/Qwen3-Next-80B-A3B-Instruct',
      QWEN_BASE_URL: 'https://integrate.api.nvidia.com/v1',
      MODEL_API_KEY: 'test-key',
    },
    fetchImpl: async (url) => {
      calledUrl = url;
      return new Response(JSON.stringify({
        choices: [{ message: { content: '응답' } }],
      }), { status: 200 });
    },
  });

  await adapter.generate({ system: '규칙', question: '질문', evidence: [] });
  assert.equal(calledUrl, 'https://integrate.api.nvidia.com/v1/chat/completions');
});
