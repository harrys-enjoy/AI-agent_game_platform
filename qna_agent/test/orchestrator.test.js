import test from 'node:test';
import assert from 'node:assert/strict';
import { createAgentRegistry } from '../src/agents.js';
import { MockModelAdapter } from '../src/model.js';
import { createOrchestrator } from '../src/orchestrator.js';

test('isolates lore cache entries by A2A contextId', async () => {
  let calls = 0;
  const orchestrator = createOrchestrator({
    lookup: () => null,
    agents: new Map([['lore', { ask: async ({ context }) => {
      calls += 1;
      return {
        answer: `answer for ${context.contextId}`,
        agent: 'lore',
        sources: [],
        usage: null,
        confidence: null,
      };
    } }]]),
    cacheTtlMs: 60_000,
  });
  const baseRequest = {
    mode: 'lore',
    question: 'same lore question',
    context: {
      projectId: 'demo',
      userId: 'user-1',
      workContext: 'same work context',
    },
    evidence: ['same evidence'],
  };

  const first = await orchestrator.ask({
    ...baseRequest,
    requestId: 'req_ctx_a',
    context: { ...baseRequest.context, contextId: 'ctx-a' },
  });
  const second = await orchestrator.ask({
    ...baseRequest,
    requestId: 'req_ctx_b',
    context: { ...baseRequest.context, contextId: 'ctx-b' },
  });

  assert.equal(calls, 2);
  assert.equal(first.answer, 'answer for ctx-a');
  assert.equal(second.answer, 'answer for ctx-b');
});

test('art-guide agent는 제한된 컨텍스트로 응답한다', async () => {
  const registry = createAgentRegistry({ modelAdapter: new MockModelAdapter() });
  const result = await registry.get('art-guide').ask({
    requestId: 'req_test',
    mode: 'dev-guide',
    question: '마을 색상을 추천해줘',
    context: {},
    evidence: ['저채도 갈색과 청록색을 사용한다.'],
  });
  assert.equal(result.agent, 'art-guide');
  assert.match(result.answer, /저채도/);
  assert.equal(result.usage, null);
});

test('lore agent는 등록된 에이전트로 조회할 수 있다', () => {
  const registry = createAgentRegistry({ modelAdapter: new MockModelAdapter() });
  assert.equal(typeof registry.get('lore').ask, 'function');
});

test('구조화 데이터 응답은 모델을 호출하지 않는다', async () => {
  let calls = 0;
  const orchestrator = createOrchestrator({
    lookup: () => ({ answer: '직접 조회 결과', sources: ['codex:test'] }),
    agents: new Map([['codex', { ask: async () => { calls += 1; return {}; } }]]),
  });
  const result = await orchestrator.ask({
    requestId: 'req_test', mode: 'codex', question: '도감 질문', context: {},
  });
  assert.equal(result.agent, 'knowledge');
  assert.equal(calls, 0);
});

test('lore 질문은 lore agent만 호출한다', async () => {
  const called = [];
  const orchestrator = createOrchestrator({
    lookup: () => null,
    agents: new Map([
      ['lore', { ask: async () => { called.push('lore'); return { answer: '세계관 답변', agent: 'lore', sources: [], usage: null, confidence: null }; } }],
      ['art-guide', { ask: async () => { called.push('art-guide'); return {}; } }],
    ]),
  });
  await orchestrator.ask({ requestId: 'req_test', mode: 'lore', question: '세력 관계', context: {} });
  assert.deepEqual(called, ['lore']);
});

test('같은 질문은 TTL 동안 에이전트를 다시 호출하지 않는다', async () => {
  let calls = 0;
  const orchestrator = createOrchestrator({
    lookup: () => null,
    agents: new Map([['lore', { ask: async () => {
      calls += 1;
      return { answer: '캐시 가능한 답변', agent: 'lore', sources: [], usage: null, confidence: null };
    } }]]),
    cacheTtlMs: 60_000,
  });
  const first = await orchestrator.ask({ requestId: 'req_1', mode: 'lore', question: '세력 관계', context: { projectId: 'demo' } });
  const second = await orchestrator.ask({ requestId: 'req_2', mode: 'lore', question: '세력 관계', context: { projectId: 'demo' } });
  assert.equal(calls, 1);
  assert.equal(first.requestId, 'req_1');
  assert.equal(second.requestId, 'req_2');
});

test('dev-guide의 기획 질문은 planning-guide로 라우팅한다', async () => {
  const called = [];
  const makeAgent = (name) => ({ ask: async () => {
    called.push(name);
    return { answer: name, agent: name, sources: [], usage: null, confidence: null };
  } });
  const orchestrator = createOrchestrator({
    lookup: () => null,
    agents: new Map([
      ['planning-guide', makeAgent('planning-guide')],
      ['art-guide', makeAgent('art-guide')],
    ]),
  });
  const result = await orchestrator.ask({
    requestId: 'req_test', mode: 'dev-guide', question: '전투 시스템 기획안을 검토해줘', context: {},
  });
  assert.equal(result.agent, 'planning-guide');
  assert.deepEqual(called, ['planning-guide']);
});

test('오케스트레이터는 토큰 절감 경로별 호출 수를 제공한다', async () => {
  const orchestrator = createOrchestrator({
    lookup: (mode) => mode === 'codex' ? { answer: '직접 조회', sources: [] } : null,
    agents: new Map([['lore', { ask: async () => ({ answer: '에이전트', agent: 'lore', sources: [], usage: null }) }]]),
  });
  await orchestrator.ask({ requestId: 'req_1', mode: 'codex', question: '도감', context: {} });
  await orchestrator.ask({ requestId: 'req_2', mode: 'lore', question: '세계관', context: {} });
  await orchestrator.ask({ requestId: 'req_3', mode: 'lore', question: '세계관', context: {} });
  assert.deepEqual(orchestrator.getMetrics(), {
    cacheHits: 1,
    directKnowledgeResponses: 1,
    agentCalls: 1,
  });
});

test('근거 자료가 다르면 같은 질문도 별도로 처리한다', async () => {
  let calls = 0;
  const orchestrator = createOrchestrator({
    lookup: () => null,
    agents: new Map([['lore', { ask: async ({ evidence }) => {
      calls += 1;
      return { answer: evidence.join(','), agent: 'lore', sources: [], usage: null };
    } }]]),
  });
  const first = await orchestrator.ask({
    requestId: 'req_1', mode: 'lore', question: '세력 관계', context: {}, evidence: ['근거 A'],
  });
  const second = await orchestrator.ask({
    requestId: 'req_2', mode: 'lore', question: '세력 관계', context: {}, evidence: ['근거 B'],
  });
  assert.equal(calls, 2);
  assert.equal(first.answer, '근거 A');
  assert.equal(second.answer, '근거 B');
});
