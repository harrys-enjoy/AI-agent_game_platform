import test from 'node:test';
import assert from 'node:assert/strict';
import { createAgentRegistry } from '../src/agents.js';

test('video prompt guide declares and requests the Video handoff JSON schema', async () => {
  let generated;
  const registry = createAgentRegistry({
    modelAdapter: {
      async generate(input) {
        generated = input;
        return { answer: '{}', usage: null };
      },
    },
  });

  await registry.get('video-prompt-guide').ask({
    question: '/art 전우치',
    evidence: ['전우치는 변신과 도술로 권력의 거짓을 폭로한다.'],
  });

  assert.match(generated.system, /JSON/);
  assert.match(generated.system, /story/);
  assert.match(generated.system, /character/);
  assert.match(generated.system, /context/);
  assert.match(generated.system, /nearby/);
  assert.match(generated.system, /prompt/);
});
