import { once } from 'node:events';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/server.js';

test('POST /message:send가 A2A HTTP+JSON 메시지 응답을 반환한다', async () => {
  const server = createServer({
    orchestrator: { ask: async (request) => ({
      answer: `응답: ${request.question}`,
      requestId: request.requestId,
    }) },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/message:send`, {
    method: 'POST',
    headers: { 'content-type': 'application/a2a+json' },
    body: JSON.stringify({
      message: { messageId: 'message-1', role: 'ROLE_USER', parts: [{ text: '전투 기획' }] },
      metadata: { mode: 'dev-guide' },
    }),
  });
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/a2a+json; charset=utf-8');
  assert.deepEqual(body, {
    message: { messageId: 'message-1', role: 'ROLE_AGENT', parts: [{ text: '응답: 전투 기획' }] },
  });
});

test('POST /message:send의 검증 오류는 A2A JSON 오류 형식으로 반환한다', async () => {
  const server = createServer({ orchestrator: { ask: async () => ({}) } }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/message:send`, {
    method: 'POST',
    headers: { 'content-type': 'application/a2a+json' },
    body: JSON.stringify({ message: { role: 'ROLE_AGENT', parts: [{ text: '질문' }] } }),
  });
  const body = await response.json();
  server.close();
  assert.equal(response.status, 400);
  assert.equal(response.headers.get('content-type'), 'application/a2a+json; charset=utf-8');
  assert.deepEqual(body.error, {
    code: 400,
    status: 'INVALID_ARGUMENT',
    message: 'message.role은 ROLE_USER여야 합니다.',
    details: [{
      '@type': 'type.googleapis.com/google.rpc.BadRequest',
      fieldViolations: [],
    }],
  });
});

test('인증이 필요한 A2A HTTP+JSON CORS preflight는 Authorization 헤더를 허용한다', async () => {
  const server = createServer({
    apiKey: 'secret-key',
    corsOrigin: 'https://productivity.example',
    orchestrator: { ask: async () => ({}) },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/message:send`, {
    method: 'OPTIONS',
    headers: {
      origin: 'https://productivity.example',
      'access-control-request-method': 'POST',
      'access-control-request-headers': 'authorization, content-type',
    },
  });
  server.close();
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('access-control-allow-headers'), 'authorization, content-type');
});
