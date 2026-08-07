# Main AI Multi-Orchestrator

로컬 Docker 환경에서 Main AI가 4개 전문 Agent를 연결하는 기반 프로젝트입니다.

## 실행

```bash
docker compose up --build
```

- Main API: http://localhost:8000
- Health: http://localhost:8000/health
- Agent 목록: http://localhost:8000/api/agents

Agent 주소는 `.env`에서 바꿀 수 있습니다. 실제 Catalog를 로컬 Node 서버로 실행할 때는 `GAME_QA_AGENT_URL=http://127.0.0.1:3010/message:send`로 설정하고 `LIVE_AGENT_DISCOVERY=true`를 사용합니다.

현재 전문 Agent는 결정론적 Mock A2A 서버입니다. 실제 Git 브랜치의 Agent로 교체할 때는 각 서비스의 `build` 경로를 해당 Agent 폴더로 바꾸고, `/.well-known/agent-card.json`과 `/a2a` JSON-RPC 엔드포인트를 제공하면 됩니다.

## 로컬 구조

```text
main-agent/
├── backend/          # Main AI API와 Orchestrator
├── frontend/         # 참고 UI 기반 Viewer
├── workmate-agent/   # 업무지원 Agent 브랜치 체크아웃 위치
├── video-agent/      # 영상 Agent 브랜치 체크아웃 위치
├── dev-agent/        # 개발 Agent 브랜치 체크아웃 위치
└── game-qa-agent/    # 게임 Q&A Agent 브랜치 체크아웃 위치
```

## A2A 1.0 연동 설정

`.env.example`을 복사해 Agent registry와 서버 간 token을 설정합니다. `AGENT_REGISTRY`는 쉼표로 구분한 Agent 이름 목록이며, 각 Agent는 `<이름>_AGENT_URL`과 선택적인 `<이름>_AGENT_TOKEN`을 사용합니다.

Main Agent는 `GET /.well-known/agent-card.json`을 조회한 뒤 `supportedInterfaces`의 `protocolBinding=HTTP+JSON`, `protocolVersion=1.0` endpoint를 선택합니다. 호출에는 `application/a2a+json`을 사용하며 token이 설정된 경우에만 `Authorization: Bearer ...`를 서버에서 추가합니다.

Task API는 `POST /api/tasks`로 작업을 만들고 `GET /api/tasks/{task_id}`에서 `queued`, `running`, `succeeded`, `failed`, `cancelled` 상태를 조회합니다. 프론트엔드는 terminal 상태까지 polling합니다.

Catalog의 `/message:send` 오류는 `error.code`, `error.status`, `error.message`, `error.requestId`를 보존합니다. 입력 오류는 400, 인증 오류는 401, 미발견은 404, 일시적 장애는 503, 내부 오류는 502로 Main API에 매핑됩니다.
