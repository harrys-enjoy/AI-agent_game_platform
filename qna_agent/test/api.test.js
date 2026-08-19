import { once } from 'node:events';
import http from 'node:http';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/server.js';

test('POST /api/ask가 표준 응답을 반환한다', async () => {
  const server = createServer({
    orchestrator: { ask: async (request) => ({
      answer: '테스트 답변', mode: request.mode, agent: 'art-guide',
      sources: [], usage: null, requestId: request.requestId,
    }) },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/ask`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'dev-guide', question: '질문' }),
  });
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.equal(body.answer, '테스트 답변');
  assert.match(body.requestId, /^req_/);
});

test('잘못된 JSON은 INVALID_REQUEST JSON을 반환한다', async () => {
  const server = createServer({ orchestrator: { ask: async () => { throw new Error('호출되면 안 됨'); } } }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/ask`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: '{',
  });
  const body = await response.json();
  server.close();
  assert.equal(response.status, 400);
  assert.equal(body.error.code, 'INVALID_REQUEST');
});

test('기본 서버를 의존성 주입 없이 생성할 수 있다', () => {
  const server = createServer();
  assert.equal(typeof server.listen, 'function');
  server.close();
});

test('GET /health가 모델 호출 없이 상태를 반환한다', async () => {
  const server = createServer({
    orchestrator: { ask: async () => { throw new Error('호출되면 안 됨'); } },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/health`);
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.deepEqual(body, { status: 'ok', service: 'game-qna-api' });
});

test('GET /metrics가 토큰 절감 지표를 반환한다', async () => {
  const server = createServer({
    orchestrator: {
      ask: async () => ({}),
      getMetrics: () => ({ cacheHits: 3, directKnowledgeResponses: 5, agentCalls: 2 }),
    },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/metrics`);
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.deepEqual(body, { cacheHits: 3, directKnowledgeResponses: 5, agentCalls: 2 });
});

test('허용된 출처의 CORS preflight에 응답한다', async () => {
  const server = createServer({
    corsOrigin: 'https://productivity.example',
    orchestrator: { ask: async () => ({}) },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/ask`, {
    method: 'OPTIONS',
    headers: { origin: 'https://productivity.example', 'access-control-request-method': 'POST' },
  });
  server.close();
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('access-control-allow-origin'), 'https://productivity.example');
});

test('API_KEY가 설정되면 Bearer 인증을 요구한다', async () => {
  const server = createServer({ apiKey: 'secret-key', orchestrator: { ask: async () => ({}) } }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const unauthorized = await fetch(`http://127.0.0.1:${port}/api/ask`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'dev-guide', question: '질문' }),
  });
  const authorized = await fetch(`http://127.0.0.1:${port}/api/ask`, {
    method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer secret-key' },
    body: JSON.stringify({ mode: 'dev-guide', question: '질문' }),
  });
  const a2aUnauthorized = await fetch(`http://127.0.0.1:${port}/a2a`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'lore', question: '질문' }),
  });
  server.close();
  assert.equal(unauthorized.status, 401);
  assert.equal(authorized.status, 200);
  assert.equal(a2aUnauthorized.status, 401);
});

test('POST /a2a가 AgentResponse 형식으로 응답한다', async () => {
  const server = createServer({
    orchestrator: { ask: async (request) => ({
      answer: `응답: ${request.question}`,
      mode: request.mode,
      agent: 'planning-guide',
      sources: request.evidence,
      usage: null,
      requestId: request.requestId,
    }) },
  }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/a2a`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      requestId: 'req_a2a', mode: 'dev-guide', question: '전투 시스템 기획',
      context: { projectId: 'demo' }, evidence: ['근거 자료'],
    }),
  });
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.deepEqual(body, {
    answer: '응답: 전투 시스템 기획',
    mode: 'dev-guide',
    agent: 'planning-guide',
    sources: ['근거 자료'],
    usage: null,
    requestId: 'req_a2a',
    confidence: null,
  });
});

test('well-known Agent Card를 공개한다', async () => {
  const server = createServer({ publicUrl: 'https://game.example', orchestrator: { ask: async () => ({}) } }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/.well-known/agent-card.json`);
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.equal(body.url, 'https://game.example/message:send');
  assert.equal(body.skills.length, 4);
});
