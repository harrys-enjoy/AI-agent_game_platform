# 게임 개발 Q&A API MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 외부 업무생산성 서비스가 `POST /api/ask` 하나로 게임 기획·아트 가이드 Q&A와 카탈로그·도감·세계관 Q&A를 호출할 수 있는 최소 API를 만든다.

**Architecture:** Node.js 내장 HTTP 서버가 JSON 요청을 받고, 검증기와 단일 오케스트레이터를 거친다. `catalog`·`codex`는 구조화 데이터 조회를 먼저 수행하고, 그 외 질문은 Mock 에이전트와 Mock 모델 어댑터를 사용한다. 모델 제공자와 A2A 외부 호출은 각각 `ModelAdapter`와 `AgentRequest`/`AgentResponse` 경계 뒤에 둔다.

**Tech Stack:** Node.js 20 이상, Node 내장 `node:http`, Node 내장 `node:test`, JSON 파일, 외부 런타임 의존성 0개

## Global Constraints

- 업무생산성 서비스의 메인페이지와 아침 업무 브리핑 UI는 제작하지 않는다.
- 외부 진입점은 `POST /api/ask` 하나로 유지한다.
- 지원 모드는 `dev-guide`, `catalog`, `codex`, `lore` 네 가지다.
- `question`은 공백 제거 후 1~2,000자만 허용한다.
- `catalog`·`codex`는 구조화 데이터 조회를 모델 호출보다 우선한다.
- 모델 제공자 API를 라우트에 직접 작성하지 않는다.
- Elice ML API의 엔드포인트·인증·요청 형식을 추측하지 않는다.
- 외부 A2A 네트워크, 레지스트리, 재시도 큐, 워크플로 엔진은 만들지 않는다.
- API 키는 클라이언트와 소스 코드에 노출하지 않는다.
- 모든 요청과 오류 응답에 `requestId`를 포함한다.
- 모델 제공자가 측정하지 않은 토큰 수를 임의로 계산하지 않는다.
- 모든 비자명한 분기와 파싱 로직에는 Node 내장 테스트를 하나 이상 둔다.

---

## 파일 구조

```text
package.json                 실행 명령과 Node 버전 조건
src/server.js                HTTP 서버와 응답 직렬화
src/request.js               JSON 파싱·요청 검증·requestId 생성
src/errors.js                표준 오류 타입과 오류 코드
src/knowledge.js             구조화 게임 데이터 조회
src/model.js                 ModelAdapter 계약과 MockModelAdapter
src/agents.js                AgentRequest/AgentResponse와 Mock 에이전트 라우팅
src/orchestrator.js          mode별 최소 호출 흐름
data/knowledge.json          MVP용 카탈로그·도감·세계관 샘플 데이터
test/request.test.js         입력 검증 테스트
test/knowledge.test.js       직접 조회 테스트
test/orchestrator.test.js    오케스트레이션·토큰 절감 테스트
test/api.test.js             HTTP 계약 테스트
README.md                    외부 서비스 연동 문서
```

## Task 1: Node 프로젝트와 요청 경계 만들기

**Files:**
- Create: `package.json`
- Create: `src/errors.js`
- Create: `src/request.js`
- Test: `test/request.test.js`

**Interfaces:**
- Produces `parseJsonBody(rawBody): object`
- Produces `validateAskRequest(body): { mode, question, context }`
- Produces `createRequestId(): string`
- Produces `AppError(code, message, statusCode)` with `code`, `message`, and `statusCode`

- [ ] **Step 1: 실패 테스트 작성**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { validateAskRequest } from '../src/request.js';

test('허용된 mode와 질문을 검증한다', () => {
  assert.deepEqual(
    validateAskRequest({ mode: 'dev-guide', question: '팔레트를 추천해줘' }),
    { mode: 'dev-guide', question: '팔레트를 추천해줘', context: {} },
  );
});

test('빈 질문과 미지원 mode를 거부한다', () => {
  assert.throws(
    () => validateAskRequest({ mode: 'unknown', question: '   ' }),
    (error) => error.code === 'INVALID_REQUEST',
  );
});

test('2,001자 질문을 거부한다', () => {
  assert.throws(
    () => validateAskRequest({ mode: 'lore', question: 'a'.repeat(2001) }),
    (error) => error.code === 'INVALID_REQUEST',
  );
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

실행: `npm test -- --test-name-pattern="허용된 mode와 질문을 검증한다"`

예상 결과: `ERR_MODULE_NOT_FOUND` 또는 `validateAskRequest is not a function`으로 실패한다.

- [ ] **Step 3: 최소 구현 작성**

`package.json`에는 다음을 둔다.

```json
{
  "name": "game-qna-api",
  "private": true,
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": { "start": "node src/server.js", "test": "node --test" }
}
```

`src/request.js`는 `ALLOWED_MODES`를 `Set(['dev-guide', 'catalog', 'codex', 'lore'])`로 두고, 문자열·길이·mode를 검증한다. `context`가 없으면 `{}`를 반환하고, 객체가 아니면 `INVALID_REQUEST`를 던진다. `src/errors.js`의 `AppError`는 `Error`를 확장하며 `statusCode` 기본값은 400으로 둔다. `createRequestId()`는 외부 패키지 없이 `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`를 반환한다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

실행: `npm test -- --test-name-pattern="허용된 mode|빈 질문|2,001자"`

예상 결과: 3개 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add package.json src/errors.js src/request.js test/request.test.js
git commit -m "feat: add ask request boundary"
```

## Task 2: 구조화 지식 조회 구현

**Files:**
- Create: `data/knowledge.json`
- Create: `src/knowledge.js`
- Test: `test/knowledge.test.js`

**Interfaces:**
- Consumes: `mode` and normalized `question` from Task 1
- Produces `lookupKnowledge(mode, question): { answer, sources } | null`

- [ ] **Step 1: 실패 테스트 작성**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { lookupKnowledge } from '../src/knowledge.js';

test('codex 질문은 모델 없이 도감 데이터를 반환한다', () => {
  const result = lookupKnowledge('codex', '루멘의 약점은 무엇인가?');
  assert.equal(result.answer, '루멘의 약점은 냉기 속성입니다.');
  assert.deepEqual(result.sources, ['codex:lumens']);
});

test('자료가 없는 질문은 null을 반환한다', () => {
  assert.equal(lookupKnowledge('catalog', '없는 아이템을 보여줘'), null);
});
```

- [ ] **Step 2: 실패 확인**

실행: `npm test -- --test-name-pattern="codex 질문|자료가 없는"`

예상 결과: `ERR_MODULE_NOT_FOUND`로 실패한다.

- [ ] **Step 3: 최소 구현 작성**

`data/knowledge.json`에 `catalog`, `codex`, `lore` 배열과 다음 한 건을 포함한다.

```json
{
  "codex": [
    {
      "id": "lumens",
      "name": "루멘",
      "keywords": ["루멘", "약점"],
      "answer": "루멘의 약점은 냉기 속성입니다."
    }
  ]
}
```

`src/knowledge.js`는 파일을 모듈 로딩 시 한 번 읽고, 각 항목의 `keywords`가 질문에 포함되는 첫 항목을 반환한다. 반환 형식은 `{ answer: item.answer, sources: [`${mode}:${item.id}`] }`이며 일치하지 않으면 `null`이다. 검색엔진이나 벡터 DB는 추가하지 않는다.

- [ ] **Step 4: 통과 확인**

실행: `npm test -- --test-name-pattern="codex 질문|자료가 없는"`

예상 결과: 2개 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add data/knowledge.json src/knowledge.js test/knowledge.test.js
git commit -m "feat: add direct knowledge lookup"
```

## Task 3: 모델 어댑터와 Mock 에이전트 계약 구현

**Files:**
- Create: `src/model.js`
- Create: `src/agents.js`
- Test: `test/orchestrator.test.js`

**Interfaces:**
- Produces `MockModelAdapter.generate({ system, question, evidence, maxOutputChars }): Promise<{ answer, usage }>`
- Produces `createAgentRegistry({ modelAdapter }): Map<string, Agent>`
- Agent consumes `AgentRequest { requestId, mode, question, context, evidence }`
- Agent produces `AgentResponse { answer, agent, sources, usage, confidence }`

- [ ] **Step 1: 실패 테스트 작성**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAgentRegistry } from '../src/agents.js';
import { MockModelAdapter } from '../src/model.js';

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
```

- [ ] **Step 2: 실패 확인**

실행: `npm test -- --test-name-pattern="art-guide agent"`

예상 결과: 모듈 또는 `createAgentRegistry` 미정의 오류로 실패한다.

- [ ] **Step 3: 최소 구현 작성**

`src/model.js`의 `MockModelAdapter.generate()`는 `evidence`를 한 문장으로 합쳐 `answer`를 만들고, `maxOutputChars`를 넘기면 자른다. Mock 제공자는 실제 토큰을 측정하지 않으므로 `usage: null`을 반환한다.

`src/agents.js`는 `planning-guide`, `art-guide`, `lore`를 등록하고 `catalog`, `codex` 에이전트는 Task 2의 직접 조회 경로에서 처리한다. 각 Agent는 짧은 `system` 문자열과 `evidence.slice(0, 5)`만 모델 어댑터에 전달한다. 에이전트 응답은 항상 `agent`, `sources`, `usage`, `confidence: null`을 포함한다.

- [ ] **Step 4: 통과 확인**

실행: `npm test -- --test-name-pattern="art-guide agent"`

예상 결과: PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/model.js src/agents.js test/orchestrator.test.js
git commit -m "feat: add mock model and agent contracts"
```

## Task 4: 토큰 절감 오케스트레이터 구현

**Files:**
- Create: `src/orchestrator.js`
- Modify: `test/orchestrator.test.js`

**Interfaces:**
- Consumes: `validateAskRequest()` from Task 1, `lookupKnowledge()` from Task 2, `createAgentRegistry()` from Task 3
- Produces `createOrchestrator({ agents, lookup }): { ask(request): Promise<AskResponse> }`
- `ask(request)` produces `{ answer, mode, agent, sources, usage, requestId }`

- [ ] **Step 1: 실패 테스트 작성**

```js
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
```

- [ ] **Step 2: 실패 확인**

실행: `npm test -- --test-name-pattern="구조화 데이터 응답|lore 질문"`

예상 결과: `createOrchestrator` 미정의 오류로 실패한다.

- [ ] **Step 3: 최소 구현 작성**

`createOrchestrator()`는 먼저 `lookup(mode, question)`을 호출한다. 결과가 있으면 `agent: 'knowledge'`, `usage: null`로 즉시 반환한다. 결과가 없으면 `mode`를 다음처럼 매핑한다: `dev-guide -> art-guide`, `lore -> lore`. `catalog`와 `codex`에서 직접 조회 결과가 없으면 각각 `catalog`와 `codex` 에이전트가 없다는 오류 대신 `KNOWLEDGE_NOT_FOUND`를 반환한다. 모든 응답에 입력의 `requestId`를 그대로 포함한다.

- [ ] **Step 4: 통과 확인**

실행: `npm test -- --test-name-pattern="구조화 데이터 응답|lore 질문|art-guide agent"`

예상 결과: 관련 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/orchestrator.js test/orchestrator.test.js
git commit -m "feat: add minimal qna orchestration"
```

## Task 5: HTTP API 서버와 표준 오류 응답 구현

**Files:**
- Create: `src/server.js`
- Create: `test/api.test.js`
- Modify: `src/request.js`

**Interfaces:**
- Produces `createServer({ orchestrator }): http.Server`
- `POST /api/ask` returns HTTP 200 with `AskResponse`
- Invalid JSON or invalid request returns `{ error: { code, message, requestId } }`
- Unknown path returns HTTP 404 with `INTERNAL_ERROR`-compatible JSON error envelope

- [ ] **Step 1: 실패 테스트 작성**

```js
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
```

- [ ] **Step 2: 실패 확인**

실행: `npm test -- --test-name-pattern="POST /api/ask|잘못된 JSON"`

예상 결과: `createServer` 미정의 오류로 실패한다.

- [ ] **Step 3: 최소 구현 작성**

`src/server.js`는 Node `http.createServer()`만 사용한다. 요청 본문은 1MB를 넘으면 즉시 `INVALID_REQUEST`로 종료한다. `POST /api/ask`만 처리하고, JSON을 파싱한 뒤 `requestId`를 추가하고 `validateAskRequest()`를 호출한다. `AppError`는 해당 `statusCode`로, 알 수 없는 오류는 500과 `INTERNAL_ERROR`로 반환한다. 응답 헤더에는 `content-type: application/json; charset=utf-8`을 넣는다.

- [ ] **Step 4: 통과 확인**

실행: `npm test -- --test-name-pattern="POST /api/ask|잘못된 JSON"`

예상 결과: 2개 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/server.js src/request.js test/api.test.js
git commit -m "feat: expose ask http api"
```

## Task 6: 실행 문서와 외부 연동 계약 정리

**Files:**
- Create: `README.md`
- Modify: `src/server.js`
- Test: `test/api.test.js`

**Interfaces:**
- README documents `POST /api/ask`, four modes, request/response/error examples, and `context.workContext` values.
- Server supports `PORT` environment variable with default `3000`.
- Server creates the default orchestrator internally while allowing dependency injection in tests.

- [ ] **Step 1: 실패 테스트 작성**

```js
test('기본 서버가 PORT 환경변수와 기본 오케스트레이터를 사용한다', async () => {
  const server = createServer();
  assert.equal(typeof server.listen, 'function');
  server.close();
});
```

- [ ] **Step 2: 실패 확인**

실행: `npm test -- --test-name-pattern="기본 서버"`

예상 결과: `createServer`가 인자 없이 실행되지 않아 실패한다.

- [ ] **Step 3: 최소 구현 작성**

`createServer()`가 인자를 받지 않으면 `MockModelAdapter`, 에이전트 레지스트리, 지식 조회기, 오케스트레이터를 내부에서 조립한다. `src/server.js`의 직접 실행 분기에서 `Number(process.env.PORT || 3000)`을 사용한다. README에는 외부 업무생산성 서비스가 서버 API를 호출하는 예시와 Elice ML API 키를 클라이언트에 전달하지 않는다는 경고를 포함한다. 실제 Elice 엔드포인트 예시는 작성하지 않는다.

- [ ] **Step 4: 통과 확인**

실행: `npm test`

예상 결과: 모든 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add README.md src/server.js test/api.test.js
git commit -m "docs: document external api integration"
```

## Task 7: 전체 검증과 인수 기준 확인

**Files:**
- Verify: `package.json`, `src/`, `data/`, `test/`, `README.md`

- [ ] **Step 1: 전체 테스트 실행**

실행: `npm test`

예상 결과: 모든 테스트 PASS, 실패·미처리 rejection 없음.

- [ ] **Step 2: 수동 API 확인**

한 터미널에서 실행:

```bash
npm start
```

다른 터미널에서 실행:

```bash
curl -X POST http://127.0.0.1:3000/api/ask \
  -H "content-type: application/json" \
  -d '{"mode":"codex","question":"루멘의 약점은 무엇인가?","context":{"workContext":"in-progress"}}'
```

예상 결과: `agent`가 `knowledge`이고, `usage`가 `null`인 200 응답.

- [ ] **Step 3: 토큰 절감 경로 확인**

`catalog` 또는 `codex`의 샘플 데이터 질문이 모델 어댑터를 호출하지 않고 응답하는지 테스트 로그와 코드 경로로 확인한다. Mock 제공자는 실제 토큰을 측정하지 않으므로 `usage: null`이 유지되는지 확인한다.

- [ ] **Step 4: 범위 확인**

업무생산성 UI, 실제 Elice ML API, 외부 A2A 네트워크가 추가되지 않았는지 확인한다. API 키와 사용자 식별자가 소스 코드에 들어가지 않았는지 검색한다.

- [ ] **Step 5: 최종 커밋**

```bash
git status --short
git log --oneline -7
```

예상 결과: 의도하지 않은 변경이 없고, Task 1~6 커밋이 순서대로 존재한다.

## Self-Review 결과

- 설계 문서의 API 계약은 Task 1과 Task 5에서 구현한다.
- 네 가지 mode와 구조화 데이터 우선 규칙은 Task 2와 Task 4에서 구현한다.
- A2A 확장 경계는 Task 3의 AgentRequest/AgentResponse 형태로 고정한다.
- Elice ML API 비종속성은 Task 3의 ModelAdapter와 Task 6의 문서로 보장한다.
- 토큰 사용량 조작 금지와 모델 호출 최소화는 Task 2, Task 3, Task 4, Task 7에서 검증한다.
- 업무생산성 UI와 외부 서비스 인증은 모든 작업의 범위 밖으로 유지한다.
- 추가 의존성, 벡터 DB, 검색엔진, UI, 실제 외부 에이전트는 MVP에 포함하지 않는다.
