# Main AI Multi-Orchestrator

Docker 환경에서 Main AI Orchestrator가 업무지원, 영상 생성, 개발 보조, 게임 Q&A Agent를 연결하고 요청을 분배하는 프로젝트입니다.

## 실행

```bash
docker compose up --build
```

- Main API: <http://localhost:8000>
- Health: <http://localhost:8000/health>
- Agent 목록: <http://localhost:8000/api/agents>

환경변수는 `.env.example`을 복사해 설정합니다. Agent 주소는 소스 코드에 하드코딩하지 않고 Main 컨테이너에 환경변수로 주입합니다.

## 통신 Protocol

| 항목 | 합의안 |
| --- | --- |
| A2A Protocol | `1.0` |
| Protocol Binding | `HTTP+JSON` |
| Docker 내부 통신 | HTTP + JSON |
| 외부 운영 통신 | HTTPS + JSON |
| Agent Card | A2A 1.0 공식 Schema 준수 |
| Message·Task·Artifact | A2A 1.0 공식 구조 준수 |
| 구현 기준 | 공식 A2A SDK 타입과 모델 우선 사용 |

업무지원·영상 생성·개발 보조 Agent는 공통 A2A 규약을 따릅니다.

게임 Q&A Agent는 Catalog에 연결된 기존 Endpoint를 사용하므로 예외로 관리합니다. 현재 Catalog도 A2A 1.0 `HTTP+JSON`의 `/message:send` Endpoint를 제공하며, 향후 다른 Agent와 Endpoint를 통일할지는 별도로 결정합니다.

Docker 내부 통신은 서비스 네트워크에서 HTTP를 사용합니다. 외부 운영 환경에서 HTTPS를 사용하려면 Reverse Proxy 또는 API Gateway에서 TLS를 종료하고 JSON 요청을 전달해야 합니다. 현재 Compose는 로컬 Docker 내부 통신을 위한 설정이며 TLS 인증서와 외부 Gateway는 포함하지 않습니다.

## Agent 계약

| Agent | 환경변수 | Docker 서비스명 | Port | 환경변수 값 | 상태 |
| --- | --- | --- | --- | --- | --- |
| 업무지원 | `WORKMATE_AGENT_URL` | `workmate-agent` | `8001` | `http://workmate-agent:8001/a2a` | 실제 Agent |
| 영상 생성 | `VIDEO_AGENT_URL` | `video-agent` | `8002` | `http://video-agent:8002/a2a` | 실제 Agent |
| 개발 보조 | `DEV_AGENT_URL` | `dev-agent` | `8003` | `http://dev-agent:8003/a2a` | Mock |
| 게임 Q&A | `GAME_QNA_AGENT_URL` | `game-qa-agent` | `3000` | `http://game-qa-agent:3000/message:send` | Catalog 연결 |

`video-agent`는 Gemini 기반 7단계 에이전트(기획~프롬프트~이미지 검수) + 실제 Veo/LTX 렌더 백엔드 + `ffmpeg` 합본까지 전 구간이 실제로 동작한다 (`../video_agent`, 자세한 내용은 그 저장소의 README 참고). `VIDEO_SERVICE_TOKEN` Bearer 인증 + `A2A-Version: 1.0` 헤더가 모든 `/a2a/*` 요청에 필요하다.

모든 주소는 Orchestrator에 환경변수로 주입합니다. Main은 환경변수에서 Endpoint 주소를 읽고, Agent Card를 조회할 때 필요한 경우 `/a2a` 또는 `/message:send`를 제거해 Base URL을 계산합니다.

## Docker Compose 환경변수

Main 서비스에는 계약표와 동일한 Endpoint URL을 주입합니다.

```yaml
services:
  main-agent:
    environment:
      WORKMATE_AGENT_URL: "http://workmate-agent:8001/a2a"
      VIDEO_AGENT_URL: "http://video-agent:8002/a2a"
      DEV_AGENT_URL: "http://dev-agent:8003/a2a"
      GAME_QNA_AGENT_URL: "http://game-qa-agent:3000/message:send"

      WORKMATE_SERVICE_TOKEN: ${WORKMATE_SERVICE_TOKEN}
      VIDEO_SERVICE_TOKEN: ${VIDEO_SERVICE_TOKEN}
      DEV_SERVICE_TOKEN: ${DEV_SERVICE_TOKEN}
      GAME_QNA_SERVICE_TOKEN: ${GAME_QNA_SERVICE_TOKEN}
```

토큰은 서버 컨테이너에서만 사용합니다. 기존 환경과의 호환을 위해 `*_AGENT_TOKEN`도 fallback으로 지원하지만, 신규 설정에서는 `*_SERVICE_TOKEN`을 사용합니다.

`LIVE_AGENT_DISCOVERY=true`일 때 Main은 매 요청마다 `AGENT_REGISTRY`에 나열된 Agent 이름(예: `workmate-agent,video-agent,dev-agent,game-qna-agent`)의 Agent Card를 실시간으로 다시 조회합니다(`registry.refresh()`). 꺼져 있으면 최초 기동 시 조회한 Agent Card만 사용합니다.

채팅 라우팅(어느 사용자 메시지를 어느 Sub-agent로 보낼지 판단)은 기본적으로 규칙 기반이며, `ROUTER_LLM_ENABLED=true`로 켜면 `ROUTER_MODEL_NAME`/`ROUTER_BASE_URL`/`ROUTER_API_KEY`(기본 `https://integrate.api.nvidia.com/v1`)로 지정한 LLM이 라우팅 판단에 추가로 관여합니다(`ROUTER_TIMEOUT_SECONDS`, 기본 `8`초). 셋 중 하나라도 비어 있으면 `ROUTER_LLM_ENABLED=true`여도 LLM 라우팅은 비활성화됩니다.

Agent 컨테이너는 기본적으로 Docker 내부에서만 접근할 수 있도록 `expose`를 사용합니다.

```yaml
  workmate-agent:
    expose: ["8001"]
  video-agent:
    expose: ["8002"]
  dev-agent:
    expose: ["8003"]
  game-qa-agent:
    expose: ["3000"]
```

개발 중 Host에서 Agent에 직접 접근해야 할 때만 다음처럼 `ports`를 추가합니다.

```yaml
  workmate-agent:
    ports: ["8001:8001"]
  video-agent:
    ports: ["8002:8002"]
  dev-agent:
    ports: ["8003:8003"]
  game-qa-agent:
    ports: ["3000:3000"]
```

## Agent Card와 Endpoint

Main은 각 Agent의 다음 URL에서 Agent Card를 조회합니다.

```text
GET <Agent Base URL>/.well-known/agent-card.json
```

Agent Card의 `supportedInterfaces`에서 다음 조건을 만족하는 Endpoint를 선택합니다.

```json
{
  "protocolBinding": "HTTP+JSON",
  "protocolVersion": "1.0"
}
```

일반 Agent는 `/a2a` 호환 Endpoint를 사용하고, Catalog 게임 Q&A Agent는 다음 Endpoint를 사용합니다.

```text
POST http://game-qa-agent:3000/message:send
Content-Type: application/a2a+json
A2A-Version: 1.0
```

CAT Compose는 `AGENT_PUBLIC_URL=http://game-qa-agent:3000`을 주입하므로 Agent Card가 Docker 내부에서 접근 가능한 `/message:send` 주소를 광고합니다.

## Task API

작업 생성:

```http
POST /api/tasks
Content-Type: application/json
```

작업 상태 조회:

```http
GET /api/tasks/{task_id}
```

Main은 `queued`, `running`, `succeeded`, `failed`, `cancelled` 상태를 관리하며, Agent가 완료 Task를 반환하는 경우 Task URL을 polling합니다.

## Video Agent Task API

video-agent 전용 A2A Task Proxy Route입니다.

```http
POST   /api/video-agent/tasks
GET    /api/video-agent/tasks?owner=...&limit=20&offset=0
GET    /api/video-agent/tasks/{task_id}
GET    /api/video-agent/tasks/{task_id}/detail
POST   /api/video-agent/tasks/{task_id}/cancel
DELETE /api/video-agent/tasks/{task_id}
GET    /api/video-agent/veo-usage
POST   /api/video-agent/tasks/{task_id}/scenes/{scene_id}/resume
```

`POST /api/video-agent/tasks`는 video-agent의 `message:send`를 호출해 Task를 생성하고(모호한 요청이면 명확화 질문을 반환), 담당자별 업무 로그(`task_log_store`)에도 "진행 중" 항목을 남깁니다. `GET /tasks`는 `owner`로 필터링된 Task 목록(갤러리용, 페이지네이션 포함)을, `GET /tasks/{task_id}/detail`은 내러티브·스토리보드·프롬프트까지 포함한 전체 생성 기록을 반환합니다. `DELETE`는 Task와 결과 영상 파일을 함께 삭제하며(진행 중인 Task는 거부, 먼저 취소 필요), `GET /veo-usage`는 로컬 Veo 호출 카운터를(Google 실제 쿼터 아님) 반환합니다. 나머지는 각각 Task 상태 조회, 취소, 수동 수정 이미지 재개(resume)를 video-agent에 그대로 proxy합니다. `video_agent_client.py`가 이 모든 호출에 `VIDEO_SERVICE_TOKEN` Bearer 인증을 붙입니다.

Video Agent Frontend는 더 이상 별도 Vite Entry(`video-agent.html`)가 아니라 메인 앱 SPA 안의 전용 페이지(`frontend/src/video-agent/VideoAgentPage.tsx`, 갤러리는 `VideoGallery.tsx`/`VideoDetailModal.tsx`)로 통합되어 메인 Sidebar 네비게이션에서 바로 접근할 수 있습니다.

Frontend 테스트:

```bash
cd frontend && npm run test:video-agent
```

교차 저장소 수동 Smoke Test(`scripts/video_agent_smoke_test.sh`)는 다음이 필요합니다.

- `video_draft_pipeline` 저장소가 형제 디렉터리로 checkout되어 있어야 합니다(기본 경로 `../proj`, 인자로 override 가능).
- `ffmpeg`가 PATH에 있어야 합니다.

## Catalog 게임 Q&A 연동

게임 Q&A는 기존 Catalog Endpoint를 예외 계약으로 사용합니다.

- Agent Card: `http://game-qa-agent:3000/.well-known/agent-card.json`
- A2A HTTP+JSON: `http://game-qa-agent:3000/message:send`
- Content-Type: `application/a2a+json`
- Protocol version: `1.0`

Catalog의 오류 응답은 `error.code`, `error.status`, `error.message`, `error.requestId`를 유지한 채 Main API 오류로 매핑합니다.

## Mock Agent를 실제 Agent로 교체

1. 해당 Agent의 Docker Compose `build` 경로를 실제 Agent 프로젝트로 변경합니다.
2. 해당 Agent가 `/.well-known/agent-card.json`을 제공합니다.
3. Agent Card에 `HTTP+JSON`, `1.0` 인터페이스를 선언합니다.
4. Compose의 서비스명, 내부 Port, 환경변수 URL을 계약표와 일치시킵니다.
5. 필요한 경우 `*_SERVICE_TOKEN`을 설정합니다.

## 검증

Backend 계약 테스트:

```bash
python -m pytest backend/tests/test_registry.py backend/tests/test_a2a_client.py backend/tests/test_contracts.py -q
```

Catalog 테스트:

```bash
cd "../Catalog & Manual(Game project)"
npm test
```
