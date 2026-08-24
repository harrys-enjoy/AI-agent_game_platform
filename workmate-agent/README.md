# Workmate AI Agent

Workmate AI의 공식 `a2a-sdk==1.1.2` HTTP+JSON 런타임이자 업무지원 REST 백엔드입니다. 하나의 FastAPI 앱이 A2A Route와 오늘 브리핑, 주간 업무보고, 할 일, 회의, Gmail·Calendar 제안 및 Assistant Route를 함께 제공합니다.

## 현재 계약

| 항목 | 값 |
| --- | --- |
| 컨테이너 | `workmate-agent` |
| 포트 | `8001` |
| A2A Base URL | `http://workmate-agent:8001/a2a` |
| 인증 | `Authorization: Bearer $WORKMATE_SERVICE_TOKEN` |
| A2A 버전 | `1.0` (`A2A-Version` 헤더) |
| SDK | `a2a-sdk==1.1.2` |
| Protocol Binding | `HTTP+JSON` |
| A2A 인프라 저장소 | 운영: PostgreSQL (`DATABASE_URL`), 로컬·Contract Test: SQLite 파일 |
| REST API | `/api/v1/*` (Compose에서 호스트 `http://127.0.0.1:8100`으로 공개) |

Agent Card는 `GET /.well-known/agent-card.json`에서 공개합니다. Card의 `capabilities.streaming`은 `true`이며, SDK가 생성한 Route 중 MVP allowlist만 등록합니다.

```text
GET  /.well-known/agent-card.json
POST /a2a/message:send
POST /a2a/message:stream
GET  /a2a/tasks/{id}
POST /a2a/tasks/{id}:cancel
POST /a2a/tasks/{id}:subscribe
GET  /health/live
GET  /health/ready
```

Push notification, task list, extended card Route와 SDK 호환용 `GET /a2a/tasks/{id}:subscribe` 변형은 공개하지 않습니다. `POST /a2a/tasks/{id}:subscribe`만 MVP Subscribe 계약으로 허용합니다.

## 로컬 실행

```powershell
$env:WORKMATE_SERVICE_TOKEN = 'local-development-token'
uv sync --frozen
uv run python -m app.server
```

Windows에서 PostgreSQL Task Store를 사용할 때도 위 명령을 사용한다. 직접
`uvicorn app.main:app`을 실행하면 기본 Proactor Event Loop와 psycopg async
연결이 호환되지 않는다. 주소와 포트는 `WORKMATE_HOST`, `WORKMATE_PORT`로
변경한다.

확인:

```powershell
Invoke-RestMethod http://localhost:8001/health/live
Invoke-RestMethod http://localhost:8001/.well-known/agent-card.json
```

## Docker 실행

Compose 파일은 `../main_agent/docker-compose.yml`에 있습니다. `workmate-agent/.env`와 Google OAuth 파일에 Secret을 저장할 수 있지만 Git에는 커밋하지 않습니다.

```env
WORKMATE_SERVICE_TOKEN=local-development-token
APP_BASE_URL=http://workmate-agent:8001/a2a
OPENAI_API_KEY=...
WORKMATE_OAUTH_REDIRECT_BASE_URL=http://localhost:8100
```

```powershell
cd ../main_agent
docker compose up --build -d
docker compose ps
docker compose down
```

Compose는 컨테이너의 `8001`을 호스트 `8100`으로 공개하고 PostgreSQL을 함께 실행합니다. A2A는 Main Agent가 Docker 내부 주소 `http://workmate-agent:8001/a2a`로 호출하고, 프론트엔드는 REST API를 `http://127.0.0.1:8100`으로 호출합니다.

Google 연동을 사용하려면 `google-oauth-test/client_secret.json`과 최초 로그인으로 발급받은 `token.json`을 준비합니다. Compose가 두 파일을 컨테이너에 마운트하며 `GOOGLE_CLIENT_SECRET_FILE`, `GOOGLE_TOKEN_FILE`을 자동 지정합니다.

## 업무 기능

- 오늘 브리핑과 주간 업무보고 생성
- 할 일 등록·수정·완료·삭제 및 우선순위 계산
- 회의 녹음 업로드, 분석, Action Item 검토와 이전 회의 검색
- Gmail·Calendar 동기화, 업무 제안 승인·무시
- 자연어 Assistant를 통한 업무·회의·메일·일정 조회

Assistant가 검색 결과를 답변할 때 회의는 가장 관련도 높은 1건의 날짜·시간·제목, 메일은 수신일·제목을 근거로 표시하고 Calendar에서 직접 찾은 정보에는 `근거: 캘린더`를 표시합니다.

회의 삭제는 사용자 화면과 SQLite 회의 목록에서는 soft delete로 처리해 기존 Task의 provenance 조회를 보존합니다. 동시에 PostgreSQL의 해당 회의 검색 색인과 하위 chunk는 제거하여 삭제한 회의가 이후 검색 결과에 나타나지 않게 합니다. 색인 삭제에 실패하면 불일치 방지를 위해 요청을 `503`으로 종료하고 soft delete도 수행하지 않습니다.

## 테스트

M0.1-01과 M0.1-02의 기준 테스트는 `tests/` 아래의 공식 SDK 런타임·Contract Test입니다.

```powershell
uv run python -m unittest discover -s tests -v
```

M5.1 Workmate A2A 호환성 검수는 실행 중인 Agent를 실제 HTTP로 호출한다. 운영 Orchestrator가 없어도 Workmate의 Agent Card·5개 Skill·Artifact·Mock 차단을 먼저 확인할 수 있다. 이 결과는 M5.1 사전 호환성 증빙이며 실제 Orchestrator 종단 간 완료를 대신하지 않는다.

```powershell
$env:WORKMATE_A2A_BASE_URL = 'http://127.0.0.1:8001/a2a'
$env:WORKMATE_SERVICE_TOKEN = '로컬 토큰'
uv run python tools/m51_a2a_compatibility.py
```

테스트는 Agent Card의 HTTP+JSON·Streaming 선언, SDK Route allowlist, Bearer Token·`A2A-Version` 검사, SDK Message 직렬화, 승인된 Skill·Artifact Schema 검증, `message:send`·Streaming 응답을 확인합니다. Schema는 Superproject의 `docs/schemas/`를 자동 탐색하며, 별도 checkout에서는 `WORKMATE_SCHEMA_ROOT`로 지정합니다.

## 구현 경계

- `app/main.py`: FastAPI 진입점, health와 인증 미들웨어
- `app/a2a/runtime.py`: Agent Card, SDK `DefaultRequestHandler`, `AgentExecutor`, Route allowlist, Store·Registry 연결
- `app/a2a/persistence.py`: A2A Task·Message 멱등성·Artifact·`task_id ↔ thread_id`·Checkpoint 저장 경계
- `app/workflows/registry.py`: `skill_id → Workflow` 선택과 전송 독립 요청·결과 타입
- `migrations/001_a2a_infrastructure.sql`: PostgreSQL 운영용 M0.1 A2A 인프라 Migration
- `pyproject.toml`, `uv.lock`: 의존성의 단일 원장
- `tests/test_runtime_boot.py`: M0.1-01 부트스트랩 검증
- `tests/test_persistence.py`, `tests/test_migration.py`: M0.1-03 영속 경계·Migration 검증

Executor는 Registry를 통해 업무 Workflow를 선택하고 A2A 인프라 Snapshot·멱등성·Checkpoint를 기록합니다. Gmail·Calendar·업무 DB·LLM Workflow가 연결되어 있으며, 외부 Provider 기능은 해당 자격 증명이 설정되어야 동작합니다. `DATABASE_URL`이 없으면 지원되는 로컬 저장소는 SQLite 파일을 사용하지만, 회의 검색 색인처럼 PostgreSQL 전용인 기능은 사용할 수 없습니다. 운영 Compose는 PostgreSQL URL을 자동 주입합니다.

기존 Legacy `smoke_test.py`는 제거했으며, 공식 SDK 타입과 승인된 Contract Test로 교체했습니다. 업무 Workflow와 Workmate Result는 A2A 및 REST 실행 경로에서 실제 구현을 사용합니다.
