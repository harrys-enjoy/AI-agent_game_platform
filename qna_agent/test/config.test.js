import test from 'node:test';
import assert from 'node:assert/strict';
import { parseEnv } from '../src/config.js';

test('.env 문자열을 환경변수 객체로 파싱한다', () => {
  assert.deepEqual(parseEnv(`
    MODEL_NAME=Qwen/Qwen3-Next-80B-A3B-Instruct
    MODEL_API_KEY="secret-value"
    # comment
    CORS_ORIGIN=https://productivity.example
  `), {
    MODEL_NAME: 'Qwen/Qwen3-Next-80B-A3B-Instruct',
    MODEL_API_KEY: 'secret-value',
    CORS_ORIGIN: 'https://productivity.example',
  });
});
