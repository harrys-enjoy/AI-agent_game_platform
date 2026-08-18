# Game Q&A API

카탈로그·도감·세계관 데이터 작성 규칙은 [`docs/knowledge-authoring.md`](docs/knowledge-authoring.md)에서 확인할 수 있습니다.

외부 업무생산성 서비스가 업무 중 게임 제작 정보를 요청할 수 있는 독립형 API입니다.

## 실행

요구 사항: Node.js 20 이상

## 환경변수

`.env.example`을 복사해 프로젝트 루트에 `.env` 파일을 만들고 서비스 키를 입력합니다. `.env`는 Git에 커밋되지 않습니다.

```powershell
Copy-Item .env.example .env
```

현재 `GAME_QNA_SERVICE_TOKEN`(권장, main_agent 쪽 토큰 명명 규칙과 통일 — 구 이름 `API_KEY`도 계속 동작), `CORS_ORIGIN`, 원격 agent URL은 서버에 바로 적용됩니다. `MODEL_NAME`, `MODEL_BASE_URL`, `MODEL_API_KEY`가 모두 있으면 기본 서버가 OpenAI 호환 Chat Completions 어댑터를 자동 사용하고, 세 값이 모두 없을 때만 Mock 어댑터로 실행됩니다. 일부만 설정하면 시작 시 설정 오류로 중단됩니다. 모델 키는 클라이언트에 노출하지 않습니다.

Qwen endpoint를 Elice로 교체할 때는 `.env`의 `MODEL_NAME`, `MODEL_BASE_URL`, `MODEL_API_KEY`만 변경하면 됩니다. Elice endpoint가 OpenAI 호환 형식이 아니면 `src/model-factory.js`에 Elice 전용 provider 분기를 추가합니다.

모델 호출 timeout은 기본 30초이며 `MODEL_TIMEOUT_MS`로 조정할 수 있습니다.

```bash
npm test
npm start
```

기본 포트는 `3000`이며 `PORT` 환경변수로 변경할 수 있습니다.

## Docker 실행

1. `.env.example`을 `.env`로 복사하고 실제 `API_KEY`, `MODEL_API_KEY`를 입력합니다. `.env`는 저장소에 커밋하지 않습니다.
2. `docker compose up --build -d`로 실행합니다.
3. `Invoke-RestMethod http://127.0.0.1:3000/health`로 상태를 확인합니다.
4. 출처 확인은 `Invoke-RestMethod http://127.0.0.1:3000/sources`를 사용합니다.
5. 중지는 `docker compose down`을 사용합니다.

호스트 포트는 `.env`의 `PORT`로 변경할 수 있으며, 기본값은 `3000`입니다. 실제 모델 키와 API 키는 Dockerfile, Compose 파일, 브라우저 코드에 넣지 않습니다.

## API

연동 상태 확인:

```http
GET /health
```

응답: `{"status":"ok","service":"game-qna-api"}`

토큰 절감 경로 확인:

```http
GET /metrics
```

`cacheHits`, `directKnowledgeResponses`, `agentCalls`를 반환합니다. 프로세스 시작 후 누적된 수치이며 질문·사용자·프롬프트 원문은 포함하지 않습니다.

```http
POST /api/ask
Content-Type: application/json
```

```json
{
  "mode": "dev-guide",
  "question": "중세 판타지 마을의 색상 팔레트를 추천해줘",
  "context": {
    "projectId": "demo-game",
    "userId": "user-123",
    "workContext": "morning-briefing"
  }
}
```

지원 모드:

- `dev-guide`: 기획·아트 가이드 Q&A
- `catalog`: 게임 카탈로그
- `codex`: 캐릭터·몬스터·아이템 도감
- `lore`: 세계관 Q&A

`dev-guide`는 모델을 호출하기 전에 질문을 분류합니다. `기획`, `퀘스트`, `전투 시스템`, `레벨 디자인`, `밸런스`, `규칙`, `스킬 설계`가 포함되면 `planning-guide`로, 그 외에는 `art-guide`로 라우팅합니다.

예시:

```bash
curl -X POST http://127.0.0.1:3000/api/ask \
  -H "content-type: application/json" \
  -d '{"mode":"codex","question":"루멘의 약점은 무엇인가?","context":{"workContext":"in-progress"}}'
```

구조화 데이터로 답할 수 있는 `catalog`·`codex` 질문은 모델을 호출하지 않습니다. 자료가 없는 경우 `KNOWLEDGE_NOT_FOUND`를 반환합니다.

동일한 프로젝트·사용자·mode·질문은 오케스트레이터의 인메모리 캐시에서 60초 동안 재사용됩니다. 캐시는 최대 100개 응답만 보관하며, 서버 재시작 시 초기화됩니다.

## 콘텐츠 출처·라이선스 확인

게임 카탈로그·도감·세계관 데이터의 공개 출처와 라이선스는 다음 엔드포인트에서 확인할 수 있습니다. 이 경로는 콘텐츠 출처 확인용 공개 정보만 반환하며, API 키나 사용자 질문은 포함하지 않습니다.

```http
GET /sources
```

응답의 각 항목에는 `title`, `sourceUrl`, `license`, `licenseUrl`, `usage`가 포함됩니다. 현재 등록되는 외부 게임 소스는 CC0만 허용됩니다.

## LangChain 연결

기본 실행은 외부 패키지가 없는 Mock 모델을 사용합니다. LangChain을 사용할 때는 LangChain 모델의 `invoke(messages)`를 `LangChainModelAdapter`에 주입합니다.

```js
import { LangChainModelAdapter } from './src/langchain-adapter.js';
import { createDefaultOrchestrator, createServer } from './src/server.js';

const langChainModel = {
  async invoke(messages) {
    // 실제 LangChain ChatModel 또는 Runnable을 연결한다.
    return { content: `응답: ${messages[1].content}` };
  },
};

const server = createServer({
  orchestrator: createDefaultOrchestrator({
    modelAdapter: new LangChainModelAdapter({ model: langChainModel }),
  }),
});
server.listen(3000);
```

실제 LangChain provider 패키지와 모델 설정은 사용하는 제공자의 공식 문서를 따릅니다. Elice ML API의 엔드포인트·인증·요청 형식은 기술 명세가 확보된 뒤 별도 어댑터로 연결하며, 이 API의 외부 계약은 변경하지 않습니다.

## A2A 에이전트 연결

외부 에이전트는 `createHttpAgent()`로 내부 에이전트와 같은 `ask()` 계약으로 감쌀 수 있습니다.

```js
import { createHttpAgent } from './src/a2a.js';

const remoteLoreAgent = createHttpAgent({
  agentName: 'remote-lore',
  endpoint: process.env.LORE_AGENT_URL,
});
```

서버 조립 시 원격 에이전트를 mode에 연결할 수 있습니다. URL 문자열을 넘기면 내부에서 HTTP A2A 어댑터를 만듭니다.

```js
const server = createServer({
  remoteAgents: { lore: process.env.LORE_AGENT_URL },
});
```

오케스트레이터의 `agents` 맵에서 같은 이름의 에이전트를 교체하면 됩니다. 요청은 `requestId`, `mode`, `question`, `context`, `evidence`를 포함하고, 응답은 `answer`, `agent`, `sources`, `usage`, `confidence`로 정규화됩니다. 외부 A2A 서버·레지스트리·재시도 큐는 현재 API가 소유하지 않습니다.

원격 호출은 기본 5초 timeout을 사용합니다. 응답 지연·네트워크 오류·비정상 응답은 모두 `MODEL_UNAVAILABLE`로 변환됩니다.

## 외부 연동 원칙

- 업무생산성 메인페이지와 아침 업무 브리핑 UI는 이 프로젝트가 만들지 않습니다.
- MCP Host와 중앙 업무 오케스트레이션은 기업 업무생산성 프로젝트가 담당합니다.
- 이 프로젝트는 MCP Host를 구현하지 않고 REST API와 A2A 전문 에이전트로 연결됩니다.
- 외부 서비스는 `POST /api/ask`를 호출하고 `context.workContext`에 호출 맥락을 전달합니다.
- API 키는 클라이언트나 저장소에 넣지 않습니다.
- `GAME_QNA_SERVICE_TOKEN`(구 이름 `API_KEY`도 계속 동작)을 설정하면 `/api/ask`, `/a2a`, `/message:send`에 `Authorization: Bearer <토큰>`이 필요합니다. `/health`, `/metrics`, `/sources`, Agent Card는 공개입니다.
- 일반 API 응답에는 추적용 `requestId`가 포함됩니다. A2A HTTP+JSON 오류 응답은 표준 `error.status`와 `details`를 사용합니다.
- 모델 제공자가 측정하지 않은 토큰 수는 임의로 표시하지 않습니다.
- 브라우저 호출은 `CORS_ORIGIN`에 지정된 단일 출처만 허용합니다. 기본값은 비활성입니다.

전체 HTTP 계약은 [`docs/api/openapi.yaml`](docs/api/openapi.yaml)에서 확인할 수 있습니다.

업무생산성 서비스 담당자를 위한 연결 절차와 요청 예시는 [`docs/integration/productivity-a2a.md`](docs/integration/productivity-a2a.md)에 정리했습니다.

### A2A HTTP+JSON 표준 메시지 경로

`POST /message:send`는 A2A HTTP+JSON의 동기 텍스트 메시지 경로입니다. 요청과 응답의 콘텐츠 타입은 `application/a2a+json`이며, `ROLE_USER` 텍스트 파트를 받아 `ROLE_AGENT` 텍스트 메시지 하나를 반환합니다. `metadata.mode`, `metadata.context`, `metadata.evidence`로 이 서비스의 게임 Q&A 맥락을 전달할 수 있습니다.

이 구현은 빠른 동기 Q&A용 최소 범위입니다. 스트리밍(`/message:stream`), 작업 조회·취소, 푸시 알림, 파일 파트는 아직 제공하지 않습니다. 따라서 전체 A2A HTTP+JSON binding 구현으로 표현하지 않으며, Agent Card에도 `streaming: false`, `pushNotifications: false`를 명시합니다.

`createDiscoveredHttpAgent()`는 Agent Card의 `supportedInterfaces`에 `HTTP+JSON`이 있으면 표준 메시지 형식으로 호출하고, 없으면 기존 `/a2a` 계약을 사용합니다.

기업 업무생산성 프로젝트는 전문 에이전트 호출 시 `POST /a2a`를 사용합니다. `/api/ask`와 같은 Q&A 입력을 받고 `AgentResponse`에 `confidence`를 추가해 반환합니다.

`/a2a`의 `evidence`는 최대 5개이며, 각 항목은 1~2,000자, 전체는 6,000자 이하여야 합니다.

에이전트 발견 정보는 `GET /.well-known/agent-card.json`에서 제공하며, 공개 URL은 `AGENT_PUBLIC_URL`로 설정합니다. 카드에는 API 키나 모델 키를 포함하지 않습니다.

클라이언트는 `createDiscoveredHttpAgent()`를 사용해 Agent Card를 한 번 조회한 뒤 카드의 `url`로 A2A 요청을 보낼 수 있습니다.

Bearer 인증이 필요하면 agent factory의 `headers`에 `authorization: 'Bearer <API_KEY>'`를 전달합니다.
