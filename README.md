# AI-agent_game_platform (통합 모노레포)

Main Agent(오케스트레이터)가 4개의 하위 Agent(업무지원 · 영상 생성 · 개발 보조 · 게임 Q&A)와 A2A 1.0 프로토콜로 통신하며 요청을 분배하는 프로젝트입니다. 원래 5개의 별도 저장소였던 것을 하나의 모노레포로 합쳤습니다(2026-08-18, `feat: unify main_agent, dev_agent, qna_agent, video_agent, workmate-agent into one monorepo`).

> 이 파일은 저장소 루트에 있던 원래 README가 통합 작업 중 `main_agent/README.md`로 옮겨지면서(내용은 그대로, 경로만 이동) 전체 구조를 설명하는 루트 README가 없어져 새로 작성했습니다. 서비스별 세부 문서는 각 폴더의 README를 참고하세요.

## 폴더 구조

```
AI-agent_game_platform/
├── main_agent/       # 오케스트레이터 (FastAPI 백엔드 + React 프론트엔드), docker-compose.yml 위치
├── video_agent/       # 영상 생성 Agent (실제 파이프라인: Gemini + Veo/LTX)
├── dev_agent/         # 개발 보조 Agent (LangGraph, PR 리뷰/CI 트리거)
├── qna_agent/         # 게임 Q&A Agent ("Catalog", Node.js)
└── workmate-agent/    # 업무지원 Agent
```

전체 스택은 `main_agent/docker-compose.yml` 하나로 실행합니다. 각 서비스는 위 폴더들을 형제 디렉터리로 `build:` 참조하므로, 이 5개 폴더가 반드시 같은 부모 디렉터리 아래 나란히 있어야 합니다(지금 구조 그대로).

## 빠른 시작

```bash
cd main_agent
docker compose up --build
```

- Main API: <http://localhost:8000> (`/health`, `/api/agents`)
- 프론트엔드는 Compose에 포함되어 있지 않습니다 — 별도로 `main_agent/frontend`에서 `npm install && npm run dev`로 띄웁니다 (<http://localhost:5173>).
- dev-agent용 GitHub 대시보드(kosa-front)는 <http://localhost:8004>.

## .env 파일 — 어디에 뭘 넣어야 하는가

이 모노레포에는 **두 개의 `.env` 파일**이 필요합니다. 둘 다 git에서 제외되어 있으니(`.gitignore`) 직접 만들어야 합니다.

### 1. `main_agent/.env` — 메인 오케스트레이터 + video/dev/qna Agent 공용

`docker-compose.yml`이 `main-agent`, `video-agent`, `dev-agent`, `game-qa-agent` 네 서비스 모두에 이 파일을 `env_file:`로 주입합니다. 즉 이 하나의 파일이 사실상 4개 서비스의 설정을 겸합니다.

| 키 | 용도 | 필수 여부 |
| --- | --- | --- |
| `LIVE_AGENT_DISCOVERY` | `true`면 Main이 매 요청마다 각 Agent의 `/.well-known/agent-card.json`을 실시간 조회. `false`면 코드에 하드코딩된 정적 카드만 사용 | 필수 (보통 `true`) |
| `AGENT_REGISTRY` | 등록된 Agent 이름 목록 (쉼표 구분) | 필수 |
| `WORKMATE_AGENT_URL` / `VIDEO_AGENT_URL` / `DEV_AGENT_URL` / `GAME_QNA_AGENT_URL` | 각 Agent의 A2A 엔드포인트. Docker 내부 통신이면 서비스명 그대로(`http://workmate-agent:8001/a2a` 등) | 필수 |
| `WORKMATE_SERVICE_TOKEN` | Main ↔ workmate-agent 인증 토큰. **`workmate-agent/.env`의 같은 키와 반드시 같은 값**이어야 함(둘 중 하나만 다르면 401) | 필수 |
| `VIDEO_SERVICE_TOKEN` | Main ↔ video-agent 인증 토큰. video-agent 컨테이너도 같은 파일(`main_agent/.env`)을 읽으므로 자동으로 값이 맞음 | 필수 |
| `DEV_SERVICE_TOKEN` | Main ↔ dev-agent 인증 토큰 (위와 동일 이유로 자동 일치) | 필수 |
| `GAME_QNA_SERVICE_TOKEN` | Main ↔ game-qna-agent 인증 토큰 (`API_KEY`로 대체 가능, 아래 참고) | 선택 |
| `GEMINI_API_KEY` | video-agent 실제 파이프라인이 쓰는 Google Gemini API 키(기획/스토리보드/프롬프트/이미지/리뷰/디렉터 7단계 전부 이 키 하나로 호출) | video-agent 실제 생성에 필수, 비워두면 렌더 단계에서 실패 |
| `VEO_API_KEY` | video-agent가 실제 영상 렌더링에 쓰는 Veo API 키 | Veo 백엔드 사용 시 필수 |
| `LTX_API_KEY` | video-agent가 더 저렴한 LTX 백엔드로 렌더링할 때 쓰는 키 | LTX 백엔드 사용 시에만 필요 |
| `SERVER_MAX_BUDGET_USD` | video-agent 1회 생성당 서버측 예산 상한(USD). 클라이언트가 더 큰 값을 요청해도 이 값으로 잘림. 안 넣으면 기본 5.00 | 선택 |
| `GITHUB_TOKEN` | dev-agent가 PR/브랜치 조회, CI 트리거에 쓰는 GitHub PAT(Personal Access Token). CI 트리거(`actions:write`)까지 쓰려면 해당 권한 필요, 없으면 401/60회 제한 익명 접근으로 동작 | dev-agent 기능 제한적으로 필요 |
| `WORKSPACE_REPO_MAP` | dev-agent의 워크스페이스 ID → GitHub 레포 매핑. 형식: `팀id=owner/repo`(쉼표로 여러 개) — dev-agent가 접근 가능한 레포의 경계선 | 필수(dev-agent 사용 시) |
| `MODEL_NAME` / `MODEL_BASE_URL` / `MODEL_API_KEY` | game-qna-agent(Catalog)가 스토리 생성 등에 쓰는 OpenAI 호환 LLM 엔드포인트 설정. 셋 다 비우면 Mock 모델로 자동 대체, 하나만 채우면 에러 | 선택(세 개를 세트로) |
| `ELICE_API_KEY` | Elice 플랫폼 API 키. 위 `MODEL_API_KEY`와 같은 값을 재사용하는 경우가 많음 | `MODEL_*` 사용 시 |
| `MAIN_AGENT_URL` | Cat AI Chat 같은 외부 클라이언트가 `/api/ask` 요청을 Main으로 보낼 때 쓰는 주소 | 선택 |
| `API_KEY` | game-qna-agent(Catalog) 자체 인증키. `GAME_QNA_SERVICE_TOKEN`이 없을 때 fallback으로 쓰임 | 선택 |

**주의**: `.env` 파일 안에서 주석은 반드시 `#`으로 시작해야 합니다. `#` 없이 설명만 적힌 줄이 있으면 파서가 깨질 수 있습니다.

### 2. `workmate-agent/.env` — workmate-agent 컨테이너 전용

`main_agent/.env`와는 **별개의 파일**입니다. `docker-compose.yml`의 `workmate-agent` 서비스만 이 파일을 읽습니다.

| 키 | 용도 | 필수 여부 |
| --- | --- | --- |
| `WORKMATE_SERVICE_TOKEN` | 위 `main_agent/.env`의 같은 키와 **반드시 동일한 값** | 필수 |
| `APP_BASE_URL` | 컨테이너가 자기 Agent Card에 광고할 URL. Docker 내부에서는 보통 `http://workmate-agent:8001/a2a` 그대로 | 선택(기본값 있음) |
| `OPENAI_API_KEY` | 회의 분석, 메일 Action Item 추출, 자연어 Assistant 응답에 사용하는 OpenAI 호환 API 키 | LLM 기능 사용 시 필수 |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | OpenAI 호환 API 주소와 모델 이름 | 선택(기본값 있음) |
| `GOOGLE_CLIENT_SECRET_FILE` / `GOOGLE_TOKEN_FILE` | Gmail·Calendar OAuth Client Secret과 사용자 Token 파일 경로. Compose에서는 `google-oauth-test/`의 파일을 컨테이너에 마운트 | Google 연동 시 필수 |
| `WORKMATE_OAUTH_REDIRECT_BASE_URL` | Google OAuth Callback을 받을 Workmate REST API의 외부 주소. Compose에서는 `http://localhost:8100` | Google 계정 연결 시 필수 |
| `DATABASE_URL` | Task·제안·동기화 상태와 회의 검색 색인에 사용하는 PostgreSQL 접속 주소. Compose에서는 자동 주입 | 회의 검색·Compose 운영에 필수 |

`workmate-agent/.env`는 Git에 포함되지 않으므로 로컬에서 직접 준비합니다. Google OAuth 파일도 Secret이므로 `workmate-agent/google-oauth-test/`에 로컬로만 두고 커밋하지 않습니다.

### 3. video_agent / dev_agent / qna_agent 자체 `.env.example`

각 폴더에 `.env.example`이 있지만, **docker-compose로 실행할 때는 사용하지 않습니다** — 세 서비스 모두 `main_agent/.env` 하나를 공유해서 씁니다. 이 `.env.example`들은 각 Agent를 Docker 없이 **단독으로**(예: `python -m video_draft_pipeline.cli`, `pytest` 등) 실행/테스트할 때만 필요합니다.

## 환경변수가 서비스끼리 충돌하는가?

첫 통합 작업을 한 사람이 "env가 다 충돌하는 것 같다, 하나의 `.env`로 될지 모르겠다"고 했던 부분을 실제 코드(`os.environ`/`process.env` 사용처)를 전부 추적해 확인했습니다. 결론: **전반적으로 충돌하는 건 아니고, 대부분은 의도된 공유입니다.** 실제 위험 지점은 두 곳뿐입니다.

**의도된 공유 (문제 아님)** — `main_agent/.env`는 `main-agent`/`video-agent`/`dev-agent`/`game-qa-agent` 네 컨테이너에 그대로 주입됩니다. `VIDEO_SERVICE_TOKEN`/`DEV_SERVICE_TOKEN`/`GAME_QNA_SERVICE_TOKEN`은 Main이 보내는 값과 각 Agent가 검증하는 값이 반드시 같아야 하는데, 같은 파일을 공유하기 때문에 자동으로 일치합니다. `GITHUB_TOKEN`도 dev-agent와 kosa-front가 같은 실제 토큰을 원하므로 공유가 맞는 설계입니다.

**실제 위험 지점 1 — `WORKMATE_SERVICE_TOKEN`은 반대로 자동 동기화가 안 됩니다.** 다른 세 토큰과 달리 workmate-agent는 `main_agent/.env`를 읽지 않고 별도의 `workmate-agent/.env`를 읽습니다. 두 파일에 각각 값을 넣어야 하고, 하나만 바꾸면 조용히 401이 납니다. 두 파일 모두에 이를 명시하는 주석을 추가했습니다.

**실제 위험 지점 2 — `MODEL_NAME`/`MODEL_BASE_URL`/`MODEL_API_KEY`는 두 곳이 동시에 참조합니다.** game-qna-agent(자기 자신의 LLM 호출)와 main-agent의 `RouterLLM`(요청 분류용, `ROUTER_LLM_ENABLED`가 켜져 있고 `ROUTER_MODEL_NAME`/`ROUTER_BASE_URL`/`ROUTER_API_KEY`가 비어 있을 때 이 값들로 fallback)이 동시에 이 이름들을 봅니다. 지금은 `ROUTER_LLM_ENABLED` 기본값이 `false`라 위험하지 않지만, 나중에 라우터를 켜면서 `ROUTER_*`를 따로 설정하지 않으면 game-qna-agent의 모델 설정을 그대로 빌려 씁니다. `router.py`에 이 경우 경고를 띄우도록 추가했습니다 — 라우터를 켤 거면 `ROUTER_MODEL_NAME`/`ROUTER_BASE_URL`/`ROUTER_API_KEY`를 항상 명시적으로 설정하세요.

**사소한 것 — `main_agent/.env`에 죽어있던 `APP_BASE_URL` 줄을 지웠습니다.** workmate-agent 컨테이너는 애초에 이 파일을 안 읽으므로 아무 효과가 없던 줄이었습니다(자기 자신의 `workmate-agent/.env`에 있는 `APP_BASE_URL`만 유효).

그 외 `GEMINI_API_KEY`/`VEO_API_KEY`/`LTX_API_KEY`/`SERVER_MAX_BUDGET_USD`/`WORKSPACE_REPO_MAP`/`ELICE_API_KEY`/`SELF_INTERNAL_URL` 등은 정확히 하나의 서비스만 읽으므로 충돌 가능성이 없습니다.

## video-agent는 통합 때 바뀌었는가?

**바뀌지 않았습니다.** 통합(`8e3400e`) 커밋의 `video_agent/` 아래 52개 파일을 실제 video-agent 저장소(`proj`, 현재 `5cf7642`)와 한 줄씩 비교했고, `.gitignore`에서 무관한 한 줄(`.superpowers/`)이 빠진 것 말고는 완전히 동일했습니다. 오늘 고친 문제들은 전부 `main_agent` 쪽 배선(Docker Compose, 오래된 프론트엔드 파일 등)에 있었고 video-agent 자체 코드는 손대지 않은 채로 그대로 옮겨졌습니다.

## 서비스 · 포트 · 상태

| Agent | Docker 서비스명 | 내부 Port | 호스트 노출 | 상태 |
| --- | --- | --- | --- | --- |
| Main Orchestrator | `main-agent` | 8000 | `8000:8000` | 실제 |
| 업무지원 (Workmate AI) | `workmate-agent` | 8001 | `8100:8001` | 실제 A2A + REST 백엔드 |
| 영상 생성 | `video-agent` | 8002 | `8002:8002` | 실제 (Gemini + Veo/LTX 파이프라인) |
| 개발 보조 | `dev-agent` | 8003 | 미노출 | 실제 |
| 게임 Q&A | `game-qa-agent` | 3000 | 미노출 | 실제 |
| dev-agent GitHub 대시보드 | `kosa-front` | 8000(컨테이너 내부) | `8004:8000` | 실제 |

## Workmate 실행 구조

`workmate-agent`의 단일 FastAPI 앱이 컨테이너 내부 `8001`에서 A2A(`/a2a/*`)와 Workmate REST API(`/api/v1/*`)를 함께 제공합니다. Main Agent는 Docker 네트워크의 `http://workmate-agent:8001/a2a`로 통신하고, 브라우저의 Workmate 화면은 호스트에 공개된 `http://127.0.0.1:8100`으로 REST API를 호출합니다.

Compose는 PostgreSQL(`pgvector`)을 함께 실행하고 `DATABASE_URL`을 Workmate에 주입합니다. PostgreSQL이 없거나 `DATABASE_URL`이 누락된 단독 실행에서는 일부 로컬 기능은 SQLite로 동작하지만, 이전 회의 검색처럼 PostgreSQL 색인이 필요한 기능은 사용할 수 없습니다.

현재 Workmate 화면은 오늘 브리핑, 주간 업무보고, 할 일 관리, 회의 녹음·분석·검색, Gmail·Calendar 제안과 검토 기능을 제공합니다. Google 연동 기능은 로컬 OAuth Client Secret과 Token이 설정되어 있어야 합니다.

## 실행 확인

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/agents
```

Backend 테스트:

```bash
cd main_agent
python -m pytest backend/tests -q
```

Frontend 테스트:

```bash
cd main_agent/frontend
npx tsc -b && npx vitest run
```
