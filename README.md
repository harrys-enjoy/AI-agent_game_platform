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
