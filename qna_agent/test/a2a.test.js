import test from 'node:test';
import assert from 'node:assert/strict';
import { createHttpAgent, createAgentRequest, createDiscoveredHttpAgent, discoverAgentCard, createHttpJsonAgent } from '../src/a2a.js';

test('HTTP+JSON A2A 에이전트는 표준 메시지 형식으로 요청한다', async () => {
  let received;
  const agent = createHttpJsonAgent({
    agentName: 'lore-agent',
    endpoint: 'https://agent.example/message:send',
    fetchImpl: async (url, options) => {
      received = { url, options: JSON.parse(options.body) };
      return new Response(JSON.stringify({
        message: { messageId: 'req_1', role: 'ROLE_AGENT', parts: [{ text: '세계관 응답' }] },
      }), { status: 200 });
    },
  });

  const response = await agent.ask({
    requestId: 'req_1', mode: 'lore', question: '왕국의 역사', context: {}, evidence: [],
  });

  assert.equal(received.url, 'https://agent.example/message:send');
  assert.equal(received.options.message.role, 'ROLE_USER');
  assert.equal(received.options.message.parts[0].text, '왕국의 역사');
  assert.deepEqual(response, {
    answer: '세계관 응답', mode: 'lore', agent: 'lore-agent', sources: [], usage: null, requestId: 'req_1', confidence: null,
  });
});

test('HTTP+JSON A2A 에이전트는 완료된 task의 상태 메시지를 읽는다', async () => {
  const agent = createHttpJsonAgent({
    agentName: 'planning-agent',
    endpoint: 'https://agent.example/message:send',
    fetchImpl: async () => new Response(JSON.stringify({
      task: {
        id: 'task-1',
        status: {
          state: 'TASK_STATE_COMPLETED',
          message: { role: 'ROLE_AGENT', parts: [{ text: '기획 검토 결과' }] },
        },
      },
    }), { status: 200 }),
  });

  const response = await agent.ask({
    requestId: 'req_2', mode: 'dev-guide', question: '전투 기획', context: {}, evidence: [],
  });

  assert.equal(response.answer, '기획 검토 결과');
  assert.equal(response.requestId, 'req_2');
  assert.equal(response.agent, 'planning-agent');
});
import { createDefaultOrchestrator } from '../src/server.js';

test('A2A 요청을 공통 AgentRequest 형식으로 만든다', () => {
  assert.deepEqual(
    createAgentRequest({
      requestId: 'req_test',
      mode: 'lore',
      question: '세력 관계는?',
      context: { projectId: 'demo' },
      evidence: ['자료 1'],
    }),
    {
      requestId: 'req_test',
      mode: 'lore',
      question: '세력 관계는?',
      context: { projectId: 'demo' },
      evidence: ['자료 1'],
    },
  );
});

test('HTTP 에이전트는 응답을 표준 AgentResponse로 정규화한다', async () => {
  let request;
  const agent = createHttpAgent({
    agentName: 'remote-lore',
    endpoint: 'https://agent.example/a2a',
    fetchImpl: async (_endpoint, options) => {
      request = { endpoint: _endpoint, options };
      return new Response(JSON.stringify({
        answer: '원격 세계관 답변',
        sources: ['lore:remote'],
        usage: null,
        confidence: 0.9,
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    },
  });
  const result = await agent.ask({
    requestId: 'req_test', mode: 'lore', question: '질문', context: {}, evidence: [],
  });
  assert.equal(request.endpoint, 'https://agent.example/a2a');
  assert.equal(request.options.method, 'POST');
  assert.equal(JSON.parse(request.options.body).requestId, 'req_test');
  assert.deepEqual(result, {
    answer: '원격 세계관 답변',
    agent: 'remote-lore',
    sources: ['lore:remote'],
    usage: null,
    confidence: 0.9,
  });
});

test('HTTP 에이전트는 설정된 인증 헤더를 전달한다', async () => {
  let headers;
  const agent = createHttpAgent({
    agentName: 'remote-lore',
    endpoint: 'https://agent.example/a2a',
    headers: { authorization: 'Bearer integration-key' },
    fetchImpl: async (_endpoint, options) => {
      headers = options.headers;
      return new Response(JSON.stringify({ answer: '답변' }), { status: 200 });
    },
  });
  await agent.ask({ requestId: 'req_test', mode: 'lore', question: '질문', context: {}, evidence: [] });
  assert.equal(headers.authorization, 'Bearer integration-key');
  assert.equal(headers['content-type'], 'application/json');
});

test('원격 에이전트 오류는 MODEL_UNAVAILABLE로 변환한다', async () => {
  const agent = createHttpAgent({
    agentName: 'remote-lore',
    endpoint: 'https://agent.example/a2a',
    fetchImpl: async () => new Response('{}', { status: 503 }),
  });
  await assert.rejects(
    () => agent.ask({ requestId: 'req_test', mode: 'lore', question: '질문', context: {}, evidence: [] }),
    (error) => error.code === 'MODEL_UNAVAILABLE' && error.statusCode === 503,
  );
});

test('원격 에이전트 timeout은 MODEL_UNAVAILABLE로 변환한다', async () => {
  let receivedSignal;
  const agent = createHttpAgent({
    agentName: 'slow-lore',
    endpoint: 'https://agent.example/a2a',
    timeoutMs: 1,
    fetchImpl: async (_endpoint, options) => new Promise((resolve, reject) => {
      receivedSignal = options.signal;
      options.signal.addEventListener('abort', () => reject(new Error('timeout')));
    }),
  });
  await assert.rejects(
    () => agent.ask({ requestId: 'req_test', mode: 'lore', question: '질문', context: {}, evidence: [] }),
    (error) => error.code === 'MODEL_UNAVAILABLE' && error.statusCode === 503,
  );
  assert.equal(receivedSignal instanceof AbortSignal, true);
});

test('기본 오케스트레이터는 주입된 원격 lore agent를 사용한다', async () => {
  const orchestrator = createDefaultOrchestrator({
    remoteAgents: {
      lore: {
        async ask() {
          return { answer: '원격 lore', agent: 'remote-lore', sources: [], usage: null };
        },
      },
    },
  });
  const result = await orchestrator.ask({
    requestId: 'req_test', mode: 'lore', question: '세력 관계', context: {},
  });
  assert.equal(result.agent, 'remote-lore');
  assert.equal(result.answer, '원격 lore');
});

test('Agent Card에서 A2A endpoint를 발견한다', async () => {
  let requestedUrl;
  const card = {
    name: 'game-qna-agent',
    url: 'https://game.example/a2a',
    skills: [{ id: 'lore' }],
  };
  const discovered = await discoverAgentCard({
    cardUrl: 'https://game.example/.well-known/agent-card.json',
    fetchImpl: async (url) => {
      requestedUrl = url;
      return new Response(JSON.stringify(card), { status: 200 });
    },
  });
  assert.equal(requestedUrl, 'https://game.example/.well-known/agent-card.json');
  assert.equal(discovered.url, 'https://game.example/a2a');
});

test('발견 기반 agent는 Agent Card를 한 번 조회한 뒤 요청을 보낸다', async () => {
  let cardCalls = 0;
  let a2aCalls = 0;
  const agent = createDiscoveredHttpAgent({
    agentName: 'remote-game',
    cardUrl: 'https://game.example/.well-known/agent-card.json',
    fetchImpl: async (url) => {
      if (url.endsWith('agent-card.json')) {
        cardCalls += 1;
        return new Response(JSON.stringify({ url: 'https://game.example/a2a' }), { status: 200 });
      }
      a2aCalls += 1;
      return new Response(JSON.stringify({ answer: '답변' }), { status: 200 });
    },
  });
  await agent.ask({ requestId: 'req_1', mode: 'lore', question: '질문', context: {}, evidence: [] });
  await agent.ask({ requestId: 'req_2', mode: 'lore', question: '질문2', context: {}, evidence: [] });
  assert.equal(cardCalls, 1);
  assert.equal(a2aCalls, 2);
});
