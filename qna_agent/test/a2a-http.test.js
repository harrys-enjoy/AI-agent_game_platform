import test from 'node:test';
import assert from 'node:assert/strict';
import { toAgentRequest, toSendMessageResponse } from '../src/a2a-http.js';

test('A2A HTTP+JSON SendMessage 요청을 내부 에이전트 요청으로 변환한다', () => {
  const request = toAgentRequest({
    message: {
      messageId: 'message-1',
      role: 'ROLE_USER',
      parts: [{ text: '전투 시스템 기획을 검토해줘' }],
      contextId: 'context-1',
    },
    metadata: { mode: 'dev-guide', evidence: ['회의 메모'] },
  });

  assert.deepEqual(request, {
    requestId: 'message-1',
    mode: 'dev-guide',
    locale: 'ko',
    question: '전투 시스템 기획을 검토해줘',
    context: { contextId: 'context-1' },
    evidence: ['회의 메모'],
  });
});

test('A2A HTTP+JSON 응답은 에이전트 메시지 하나를 반환한다', () => {
  const response = toSendMessageResponse({
    requestId: 'message-1',
    answer: '전투 루프와 실패 조건을 먼저 정의하세요.',
  });

  assert.deepEqual(response, {
    message: {
      messageId: 'message-1',
      role: 'ROLE_AGENT',
      parts: [{ text: '전투 루프와 실패 조건을 먼저 정의하세요.' }],
    },
  });
});

test('A2A HTTP+JSON은 사용자 텍스트 메시지만 받는다', () => {
  assert.throws(
    () => toAgentRequest({ message: { role: 'ROLE_AGENT', parts: [{ text: '질문' }] } }),
    { code: 'INVALID_REQUEST' },
  );
});
