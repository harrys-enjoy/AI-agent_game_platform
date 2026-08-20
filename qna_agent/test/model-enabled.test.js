import test from 'node:test';
import assert from 'node:assert/strict';
import { isModelEnabled } from '../src/server.js';

test('외부 LLM은 MODEL_ENABLED=true일 때만 활성화된다', () => {
  assert.equal(isModelEnabled({ MODEL_NAME: 'llama', MODEL_API_KEY: 'key' }), false);
  assert.equal(isModelEnabled({ MODEL_ENABLED: 'false', MODEL_NAME: 'llama', MODEL_API_KEY: 'key' }), false);
  assert.equal(isModelEnabled({ MODEL_ENABLED: 'true', MODEL_NAME: 'llama', MODEL_API_KEY: 'key' }), true);
});
