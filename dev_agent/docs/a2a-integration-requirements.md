# A2A 연동 요구사항 — 개발 보조(dev-agent) 기준

출처: [팀 공통 개발 규약 상세내용](https://app.notion.com/p/3b0c021f58f480499464fa1835d2c2e0) (Notion, 2026-08-06 재확인 — 전체 20개 섹션 재열람, 아래는 그 결과 반영)

이 문서는 팀 공통 규약 전체 중 **우리 Agent("개발 보조", `dev-agent`)에게 실제로 적용되는 부분만** 추려서 정리한다. 팀 문서가 원본이며, 충돌 시 팀 문서가 우선한다.

## 1. Agent 정체성 / 엔드포인트 계약

| 항목 | 값 |
|---|---|
| Agent | 개발 보조 |
| Docker 서비스명 | `dev-agent` |
| 내부 Port | `8003` |
| Base URL (env: `DEV_AGENT_URL`) | `http://dev-agent:8003/a2a` |
| 서비스 토큰 env | `DEV_SERVICE_TOKEN` |
| 상태 | Mock (팀 문서 기준으로도 여전히 Mock — 오케스트레이터 실연동 전) |
| 수신 주소 | `0.0.0.0:8003` (컨테이너 내부) |

다른 Agent 3개(참고용, 우리와 무관):

| Agent | 환경변수 | Docker 서비스명 | Port | 상태 |
|---|---|---|---|---|
| 업무지원 | `WORKMATE_AGENT_URL` | `workmate-agent` | 8001 | Mock |
| 영상 생성 | `VIDEO_AGENT_URL` | `video-agent` | 8002 | Mock |
| 게임 Q&A | `GAME_QNA_AGENT_URL` | `game-qa-agent` | 3000 | Catalog 연결 (예외: Base URL이 아니라 `/message:send`까지 포함한 전체 URL) |

## 2. URL 규칙

- Base URL: `http://{docker-service-name}:{internal-port}/a2a`
- Operation은 Base URL 뒤에 그대로 붙인다. **버전 세그먼트(`/v1/`) 없음.**

| Method | Path | 용도 |
|---|---|---|
| POST | `/a2a/message:send` | 메시지 전송 / Task 시작·재개 |
| GET | `/a2a/tasks/{id}` | Task 상태 + Artifact 조회 |
| POST | `/a2a/tasks/{id}:cancel` | 실행 중 Task 취소 |

임의 경로(`/run`, `/execute`, `/ask`, `/chat`) 금지.

## 3. Agent Card

`GET /.well-known/agent-card.json`을 반드시 제공해야 한다. (지금 우리 서버엔 없음 — 신규 구현 필요)

필수 항목: Agent 이름/설명, 버전, Provider 정보, `supportedInterfaces`, Protocol Binding, A2A Protocol 버전, 대표 Skill, 입출력 Media Type, 인증 방식, Streaming/Push Notification 지원 여부. **Token/Secret 절대 포함 금지.**

```json
{
  "supportedInterfaces": [
    {
      "url": "http://dev-agent:8003/a2a",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0"
    }
  ]
}
```

Skill ID는 영문 snake_case (예: `code_assistance`). 우리는 "동적 Tool Calling Agent"이므로 Message에 `skill_id` 없이 자연어 `text`만 받는 계약으로 처리 가능(문서 9번).

## 4. 요청 형식 (자연어 Tool Calling Agent)

```json
{
  "message": {
    "messageId": "msg-code-001",
    "role": "ROLE_USER",
    "parts": [{"text": "로그인 코드를 검토하고 버그를 찾아줘.", "mediaType": "text/plain"}]
  },
  "metadata": {"request_id": "req-code-001"}
}
```

필수: `messageId`(중복 방지), `request_id`(추적). `user_id`/`workspace_id`는 재확인해봐도 여전히 이 자연어 예시엔 없음 — 스킬 ID 기반(구조화) 요청 예시엔 `parts[0].data.workspace_id`로 들어있지만, 우리처럼 자연어만 받는 Agent용 예시는 `metadata: {"request_id": ...}` 딱 하나뿐임. 팀 문서 "공통 필수 항목" 표에도 "사용자·Workspace 정보"가 필요하다고만 적혀있고 자연어 Agent에서 정확히 어디에 싣는지는 여전히 명시 안 됨.

**→ 지금 우리 `A2AMetadata`(`request_id`/`user_id`/`workspace_id` 전부 필수)는 팀 문서의 자연어 예시를 그대로 보내면 422로 튕겨낸다.** 오케스트레이터가 실제로 문서 예시 그대로 보낼지, 아니면 `workspace_id`를 어떻게든 같이 실어 보낼지 **팀에 재확인 필요** — 우리 쪽 `WORKSPACE_REPO_MAP` 매핑 자체가 이 값에 의존하므로 단순 스키마 문제가 아니라 기능이 걸린 문제.

### 실측 확인 (main_agent 실제 코드로 로컬 통합 테스트, 2026-08-10)

팀원이 가져온 `main_agent/`(오케스트레이터 백엔드)를 우리 `dev-agent`와 `docker compose`로 실제로 붙여서 확인했다
(`main_agent/docker-compose.override.yml`). 결과, 위 우려가 실측으로 확인됐고 그 외에 두 가지가 더 나왔다.

1. **`workspace_id` 미전송 확인** — `main_agent/backend/app/a2a_client.py`의 `send_message()`가 실제로 보내는
   `metadata`는 `{mode, locale, context, evidence, systemPrompt?}`뿐이다. `request_id`/`user_id`/`workspace_id`는
   아예 안 보낸다. 실제로 붙여보니 우리 서버가 `422`(`metadata.request_id`/`user_id`/`workspace_id` 전부 필수)로
   거절하는 것을 확인. **위 문단의 우려가 이론이 아니라 지금 코드 기준 사실**이다 — 오케스트레이터 쪽에 이 셋을
   어떻게 실어 보낼지가 정해지기 전까지는 실제 연동이 안 된다. `workspace_id`가 우리 접근 제어 경계라
   임시로 기본값을 넣어 우회하는 건 하지 않았다.
2. **Agent Card에 최상위 `url` 필수** — main_agent의 `AgentCard` 모델(`contracts.py`)은 `url` 필드를 필수로
   요구하는데, 팀 문서 3번 섹션 예시(및 우리 기존 구현)는 `supportedInterfaces`에만 넣고 최상위 `url`은 안 넣는다.
   없으면 카드 파싱이 **조용히** 실패하고(`AgentRegistry.refresh()`가 예외를 삼킴), 오케스트레이터가 우리 Agent를
   "사용 불가"로 치고 로컬 에코 클라이언트로 대체해버린다 — 에러 없이 그냥 입력 텍스트를 그대로 돌려주는
   답을 받게 되어 눈치채기 어렵다. 우리 쪽 `AGENT_CARD`에 최상위 `url`을 추가해서 해결([a2a_server.py](../a2a_server.py)).
3. **`supportedInterfaces[0].url`은 base URL이 아니라 `/message:send`까지 포함해야 함** — 문서 2번 섹션은
   "Operation은 Base URL 뒤에 그대로 붙인다"고 되어 있지만, main_agent의 `A2AClient.send_message()`는 URL을
   조합하지 않는다 — 카드가 준 URL 문자열이 `/message:send`로 끝나는지만 보고 HTTP+JSON/JSON-RPC 중 뭘 쓸지
   정한 뒤 그 URL에 그대로 POST한다. Base URL만 주면 JSON-RPC로 오인해 `POST /a2a`를 호출하는데 우리 서버엔
   그 경로가 없어 `404`. `supportedInterfaces[0].url`을 `http://dev-agent:8003/a2a/message:send`로 바꿔서
   해결. **이건 문서와 main_agent 실제 구현이 다른 부분이라 팀에 공유 필요** — 다른 Agent도 같은 함정에 걸릴 수 있음.

1, 2, 3 모두 `docker compose up`으로 실제 컨테이너를 띄우고 `main-agent`를 거쳐 `dev-agent`까지 요청을 보내
확인했다(더미 `ELICE_API_KEY`라 그래프 실행 자체는 실패하지만, A2A 봉투/인증/라우팅 계층은 전부 검증됨).
2, 3은 우리 쪽 코드만 고쳐서 해결했고, 1은 오케스트레이터 쪽 결정이 필요해 미해결.

## 5. 응답 형식 — Task + Artifact

지금 구현(`{"message": {...}}`으로 요청 형태 반사)은 틀렸다. 정식 응답:

```json
{
  "task": {
    "id": "task-001",
    "contextId": "context-001",
    "status": {"state": "TASK_STATE_COMPLETED"},
    "artifacts": [
      {
        "artifactId": "artifact-001",
        "name": "Agent 처리 결과",
        "parts": [
          {"text": "# 처리 결과\n...", "mediaType": "text/markdown"},
          {"data": {"schema_version": "1.0", "result": {}}, "mediaType": "application/json"}
        ]
      }
    ]
  }
}
```

Task 생성 전 오류만 HTTP 상태로 반환 (`400` 입력 오류, `401` 인증 실패, `403` 권한 부족).

**출력 규칙** (재확인 시 새로 확인된 부분 — 지금 구현엔 없음):
- 구조화된 JSON 결과 제공, 요청받은 경우에만 Markdown 제공
- Agent 간 후속 처리는 JSON 사용 (Markdown은 사람이 읽을 때만)
- **일부 데이터 실패는 `warnings`에 기록** — 지금 우리 artifact의 JSON part(`{"schema_version": "1.0", "result": {}}`)엔 이 필드가 없음
- **근거가 필요한 결과는 `source_refs` 제공** — 이것도 지금 없음. 우리 케이스면 리뷰 코멘트가 참조한 PR 파일:라인 같은 게 해당할 듯

## 6. Task 상태

| 상태 | 의미 |
|---|---|
| `TASK_STATE_SUBMITTED` | 요청 접수 |
| `TASK_STATE_WORKING` | 처리 중 |
| `TASK_STATE_INPUT_REQUIRED` | 사용자 입력 필요 |
| `TASK_STATE_AUTH_REQUIRED` | 외부 인증 필요 |
| `TASK_STATE_COMPLETED` | 정상 완료 |
| `TASK_STATE_FAILED` | 처리 실패 |
| `TASK_STATE_CANCELED` | 취소 |
| `TASK_STATE_REJECTED` | 정책/지원 범위상 거절 |

## 7. 동기 vs 비동기 — 15초 예산

> 즉시 Workflow의 권장 실행 예산은 **15초**. 그 안에 완료 못 하면 장기 Task로 전환.

우리 그래프는 가벼운 요청도 20~30초, `deploy_trigger`가 계획에 들어가면 수 분까지 걸린다([model-card.md](model-card.md) 참고). **사실상 항상 비동기 경로를 타야 한다는 뜻**:

```
POST /a2a/message:send   → TASK_STATE_WORKING + taskId 즉시 반환 (그래프는 백그라운드 실행)
GET  /a2a/tasks/{id}     → 폴링, 완료되면 TASK_STATE_COMPLETED + artifacts
```

지금 `a2a_server.py`는 요청을 받은 스레드에서 그래프를 끝까지 블로킹 실행하는 완전 동기 구조라 이 요구사항과 정면으로 어긋난다.

## 8. 폴링 규칙 (오케스트레이터 쪽 동작, 참고용)

권장 간격: 2초 → 4초 → 8초 → 최대 10초. `Retry-After` 헤더가 있으면 그 값 우선. `COMPLETED`/`FAILED`/`CANCELED`/`REJECTED`에서 폴링 종료.

## 9. 인증

```
Authorization: Bearer {DEV_SERVICE_TOKEN 값}
A2A-Version: 1.0
Content-Type: application/json
```

토큰은 Agent Card, Git 저장소, 소스 코드, 로그, 브라우저 어디에도 남기지 않는다.

`A2A-Version: 1.0` 헤더도 매 요청에 실려 온다 — 우리 서버는 지금 이 헤더를 안 보고 무시함(검증 안 함). 팀 문서에 "필수로 검증하라"는 명시는 없어서 당장 급한 갭은 아님.

## 10. 멱등성 / 재시도

- 네트워크 재시도는 **같은 `messageId`**로 온다 — 서버가 `messageId` 기준 중복 처리를 감지해야 함(`_message_task_map`으로 반영됨).
- 오케스트레이터는 네트워크 타임아웃/429/502/503/504만 재시도. 400/401/403/404/409는 재시도 안 함.
- **"Agent 내부 Provider 재시도는 Agent가 담당한다"** — 재확인하며 새로 발견한 문구. 즉 supervisor/workers가 부르는 LLM(로컬 qwen4b, NVIDIA)이 타임아웃 나면 그건 오케스트레이터가 아니라 **우리 코드가 재시도해야 함**. 지금 `supervisor_node`/`workers.py` 어디에도 LLM 호출 재시도 로직이 없음 — 실제로 로컬 LLM `APITimeoutError`를 이미 한 번 봤다(테스트 중). 갭으로 기록.

## 11. 추적 식별자

| 식별자 | 의미 |
|---|---|
| `messageId` | A2A Message 식별 |
| `taskId` | 장기 작업 식별 |
| `contextId` | 대화·업무 맥락 |
| `request_id` | 요청 로그 추적 |
| `traceparent` | 분산 추적 |

## 12. MVP 범위

**포함**: Agent Card, HTTP+JSON A2A, Message 전송, Task 생성·조회·취소, Message·Task·Artifact, Polling, Bearer Service Token, Docker Compose 서비스 연결, 환경변수 기반 Endpoint 주입
**제외**: Streaming, Push Notification, gRPC, JSON-RPC 동시지원, Custom Protocol Binding, 여러 Binding 자동 전환

## 13. UI API vs A2A API 경계 (재확인 시 신규 확인)

```
Orchestrator → A2A API ─┐
                        ├→ 공통 Workflow·Repository
사용자 UI → UI REST API ┘
```

- A2A Route와 UI Route에 업무 규칙을 중복 구현하지 않는다 — A2A Endpoint는 Protocol/Schema 검증만, UI API는 파일 업로드/화면 요청만 담당
- **A2A Service Token을 브라우저에 전달하지 않는다**

우리 상황: `app.py`(Streamlit UI)와 `a2a_server.py`(A2A)가 둘 다 `graph/build.py`의 같은 그래프를 호출하고, `app.py`는 `DEV_SERVICE_TOKEN`을 아예 다루지 않는다 — 이미 원칙과 맞음. 별도 조치 불필요.

## 14. 버전 관리 (재확인 시 신규 확인)

| 버전 | 예 | 의미 |
|---|---|---|
| A2A Protocol | 1.0 | Agent 간 통신 규격 |
| Agent | 1.0.0 | Agent 배포 버전 |
| Skill Schema | 1.0 | Agent별 입출력 계약 |

> **URL에 `/v1`을 포함하지 않아도 A2A Protocol 버전은 계속 1.0이다.** 버전은 URL이 아니라 `A2A-Version: 1.0` 헤더로 표현한다.

지난번에 경로에서 `/v1/`을 뺀 게(`/a2a/v1/message:send` → `/a2a/message:send`) 이 원칙과 정확히 일치함을 재확인.

---

## 현재 구현과의 갭 (`a2a_server.py`)

| 항목 | 지금 | 요구사항 | 상태 |
|---|---|---|---|
| 경로 | `/a2a/message:send` | `/a2a/message:send` | ✅ 반영됨 |
| 포트 | 8003 (Agent Card 기준) | 8003 | ✅ 반영됨 |
| 토큰 env | `DEV_SERVICE_TOKEN` | `DEV_SERVICE_TOKEN` | ✅ 반영됨 |
| 응답 형식 | `{"task": {"id", "contextId", "status", "artifacts"}}` | `{"task": {..., "artifacts": [...]}}` | ✅ 반영됨 |
| 실행 모델 | `BackgroundTasks`로 비동기 실행, `TASK_STATE_WORKING` 즉시 반환 + `GET /a2a/tasks/{id}` 폴링, `POST /a2a/tasks/{id}:cancel` | 15초 초과 시 비동기(Task+폴링) | ✅ 반영됨. 단, Task 저장소가 프로세스 메모리(dict)뿐이라 재시작하면 진행 중 Task 유실. cancel은 상태만 바꿀 뿐 실행 중인 그래프(특히 deploy_trigger의 subprocess)를 실제로 중단시키진 못함 |
| Agent Card | `GET /.well-known/agent-card.json` 구현됨 | `GET /.well-known/agent-card.json` | ✅ 반영됨 |
| messageId 중복 처리 | `_message_task_map`으로 같은 messageId 재요청 시 기존 Task 그대로 반환 (재실행 안 함) | 같은 messageId 재시도 시 중복 실행 방지 | ✅ 반영됨 |
| `workspace_id` 위치 | metadata에서 필수로 읽음 (없으면 422) | 팀 문서 자연어 예시엔 `request_id`뿐, `workspace_id` 없음 | ⚠️ 팀 재확인 필요 — 재확인해도 여전히 미해결. `WORKSPACE_REPO_MAP` 매핑이 이 값에 의존해서 기능 차단 리스크 있음 |
| 워크스페이스→레포 매핑 | env(`WORKSPACE_REPO_MAP`) | 문서에 명시 없음, 우리 자체 설계 | ✅ 유지 가능 (팀 규약과 무관한 우리 쪽 내부 로직) |
| Artifact `warnings`/`source_refs` | 없음 (JSON part는 `{"schema_version": "1.0", "result": {}}` 고정) | 일부 실패는 `warnings`, 근거 필요 결과는 `source_refs` | ❌ 미반영 |
| LLM 호출 재시도 | 없음 | "Agent 내부 Provider 재시도는 Agent가 담당" | ❌ 미반영 — 로컬 LLM 타임아웃 실제 관측됨 |
| `A2A-Version` 헤더 검증 | 안 봄(무시) | 요청에 실려 옴, 검증 필수 여부는 문서에 불명확 | ⚠️ 낮은 우선순위 |
| `traceparent` 전파 | 없음 | 분산 추적용 식별자 | ⚠️ MVP 필수 여부 불명확, 낮은 우선순위 |
| UI/A2A 경계 원칙 | `app.py`가 `DEV_SERVICE_TOKEN` 안 다룸, 그래프 로직 공유 | Route 간 업무 규칙 중복 금지, 토큰 브라우저 전달 금지 | ✅ 이미 준수 |
