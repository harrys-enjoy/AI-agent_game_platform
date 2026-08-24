# ONE Platform

**하나의 목표, 하나의 완성된 결과물을 위한 AI 협업 플랫폼**입니다.

ONE Platform은 사용자의 요청을 이해해 업무지원, 영상 생성, 개발 보조, 게임 Q&A 중 적합한 전문 AI Agent로 연결합니다. 하나의 작업 흐름 안에서 아이디어를 일정·콘텐츠·개발·게임 지식 업무로 구체화하는 것을 목표로 합니다.

## 구성

| 역할 | 서비스 | 주요 기능 |
| --- | --- | --- |
| Main Agent | `main-agent` | 요청 분류, Agent 연결, 대화 세션 관리 |
| Workmate AI | `workmate-agent` | 일정·할 일·회의·제안함·Google 연동 |
| Video Generation | `video-agent` | 영상 브리프 작성, 생성 작업과 결과 확인 |
| Development Assistant | `dev-agent` | 개발 작업 지원과 GitHub 워크스페이스 연동 |
| Game Q&A | `game-qa-agent` | 게임 설정·스토리·Catalog 기반 질의응답 |

Main Agent와 전문 Agent는 A2A HTTP+JSON 통신으로 연결됩니다. 요청이 다른 전문 영역에 더 적합하면 해당 Agent 화면으로 이동하며, 의미가 모호하면 사용자가 담당 Agent를 직접 선택할 수 있습니다.

## 빠른 시작

전체 서비스는 `main_agent` 폴더의 Compose 설정으로 실행합니다.

```powershell
cd main_agent
docker compose -p main-agent-docker up -d --build
```

종료와 재기동:

```powershell
docker compose -p main-agent-docker down
docker compose -p main-agent-docker up -d --build
```

## 접속 주소

| 항목 | 주소 |
| --- | --- |
| ONE Platform 화면 | <http://localhost:5173> |
| Main Agent API / 상태 확인 | <http://localhost:8000/health> |
| Workmate REST API | <http://localhost:8100> |
| Video Agent | <http://localhost:8002> |
| 개발 GitHub 대시보드 | <http://localhost:8004> |

## 내부 Agent Chat 동작

1. 사용자가 요청을 입력하면 Main Agent가 담당 영역을 분류합니다.
2. 적합한 전문 Agent가 있으면 해당 Agent 화면으로 이동합니다.
3. 일정·회의 요청은 Workmate 흐름으로 전달되며, 일반 Project Task 자동 제안과 분리됩니다.
4. 요청 의미가 모호하면 Workmate AI, Video Generation, Development Assistant, Game Q&A 중 담당 Agent를 선택합니다.
5. Video Generation 화면에서는 먼저 요청을 분류하고, 사용자가 **생성 요청**을 눌렀을 때 영상 작업을 시작합니다.

## Workmate 실행 구조

`workmate-agent`의 단일 FastAPI 앱이 컨테이너 내부 포트 `8001`에서 A2A(`/a2a/*`)와 Workmate REST API(`/api/v1/*`)를 함께 제공합니다.

- Main Agent는 Docker 네트워크의 `http://workmate-agent:8001/a2a`로 통신합니다.
- 브라우저의 Workmate 화면은 호스트에 공개된 `http://127.0.0.1:8100`으로 REST API를 호출합니다.
- Compose는 PostgreSQL(`pgvector`)을 함께 실행하며, 회의 검색 색인과 Task·제안·동기화 상태에 사용합니다.
- Workmate는 오늘 브리핑, 주간 업무보고, 할 일 관리, 회의 녹음·분석·검색, Gmail·Calendar 제안과 검토 기능을 제공합니다.

## 환경 설정

Git에 포함되지 않는 로컬 설정 파일이 필요합니다.

| 파일 | 용도 |
| --- | --- |
| `main_agent/.env` | Main, Video, Dev, Game Q&A Agent의 공통 설정과 서비스 토큰 |
| `workmate-agent/.env` | Workmate 전용 설정 |
| `workmate-agent/google-oauth-test/client_secret.json` | Google OAuth 클라이언트 설정 |
| `workmate-agent/google-oauth-test/token.json` | Workmate 담당자가 관리하는 Google 인증 토큰 |

`WORKMATE_SERVICE_TOKEN`은 `main_agent/.env`와 `workmate-agent/.env`에서 반드시 동일해야 합니다. Workmate의 LLM 기능에는 `OPENAI_API_KEY`가 필요하며, `OPENAI_BASE_URL`과 `OPENAI_MODEL`로 OpenAI 호환 Provider를 지정할 수 있습니다.

Google 연동에는 OAuth 파일 두 개와 `WORKMATE_OAUTH_REDIRECT_BASE_URL`이 필요합니다. Compose 기본 Callback 주소는 `http://localhost:8100`입니다. `token.json`은 담당자가 관리하는 파일이므로 임의로 삭제·교체하지 마세요. Docker 실행 전 `client_secret.json`과 `token.json`은 반드시 **파일** 형태여야 합니다.

영상 생성 기능에는 `main_agent/.env`의 `GEMINI_API_KEY`가 필요하며, 사용하는 렌더러에 따라 `VEO_API_KEY` 또는 `LTX_API_KEY`도 설정합니다.

## 확인과 테스트

```powershell
# Main Agent 상태
curl http://localhost:8000/health

# 백엔드 API 테스트
cd main_agent/backend
python -m pytest tests/test_api.py -q

# 프론트엔드 테스트와 빌드
cd ../frontend
npm run test:task
npx vitest run
npm run build
```

세부 API와 A2A 계약은 [main_agent/README.md](main_agent/README.md), Workmate API와 Google 연동은 [workmate-agent/README.md](workmate-agent/README.md)를 참고하세요.
