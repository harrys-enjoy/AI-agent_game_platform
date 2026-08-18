import test from 'node:test';
import assert from 'node:assert/strict';
import { createAgentCard } from '../src/agent-card.js';

test('인증이 필요한 Agent Card에 공개 가능한 기능과 endpoint를 포함한다', () => {
  const card = createAgentCard({ publicUrl: 'https://game.example', requiresAuth: true });
  assert.equal(card.url, 'https://game.example/message:send');
  assert.deepEqual(card.supportedInterfaces, [{
    url: 'https://game.example/message:send', protocolBinding: 'HTTP+JSON', protocolVersion: '1.0',
  }]);
  assert.equal(card.capabilities.streaming, false);
  assert.deepEqual(card.skills.map((skill) => skill.id), ['dev-guide', 'catalog', 'codex', 'lore']);
  assert.equal(card.securitySchemes.bearerAuth.scheme, 'bearer');
});

test('인증이 비활성인 Agent Card는 보안 요구사항을 선언하지 않는다', () => {
  const card = createAgentCard({ publicUrl: 'https://game.example' });
  assert.equal(card.securitySchemes, undefined);
});
