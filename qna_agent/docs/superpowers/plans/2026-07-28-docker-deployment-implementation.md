# Docker 배포 구성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 게임 Q&A API를 비밀값을 이미지에 넣지 않는 Docker Compose 서비스로 실행한다.

**Architecture:** 단일 Node.js 20 Alpine 컨테이너가 기존 `npm start` 명령으로 API를 실행한다. Compose는 호스트의 `.env` 파일을 런타임에만 주입하고, 빌드 컨텍스트는 `.dockerignore`로 축소한다. 애플리케이션 코드는 변경하지 않는다.

**Tech Stack:** Docker, Docker Compose, Node.js 20, 기존 Node 내장 테스트 러너.

## Global Constraints

- API 키와 모델 API 키는 Dockerfile, Compose 파일, README 예시, 로그, 이미지 레이어에 기록하지 않는다.
- `.env`는 Git 추적과 Docker 빌드 컨텍스트에서 제외한다.
- 컨테이너 내부 포트는 `3000`이며, Compose의 호스트 포트는 `${PORT:-3000}`이다.
- 새 런타임 패키지와 데이터베이스, 볼륨을 추가하지 않는다.
- 기존 `npm.cmd test` 전체 테스트가 통과해야 한다.

---

### Task 1: 보안 Docker 실행 구성

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `compose.yaml`

**Interfaces:**
- Consumes: `package.json`의 `npm start`, `.env`의 `PORT`, `API_KEY`, `MODEL_API_KEY` 등 기존 환경변수
- Produces: `docker compose up --build -d`로 실행되는 `game-qna-api` 서비스, 호스트 `${PORT:-3000}`에서 접근 가능한 HTTP API

- [ ] **Step 1: Docker 빌드가 가능한지 확인한다**

Run: `docker version`

Expected: Docker Client와 Server 버전이 출력된다. Docker가 설치·실행되지 않은 환경이면 이 단계에서 멈추고 사용자에게 Docker Desktop 실행을 요청한다.

- [ ] **Step 2: 최소 Dockerfile을 작성한다**

Create `Dockerfile`:

```dockerfile
FROM node:20-alpine

WORKDIR /app
COPY package.json ./
COPY src ./src
COPY data ./data

EXPOSE 3000
CMD ["npm", "start"]
```

- [ ] **Step 3: 비밀값 제외 규칙을 작성한다**

Create `.dockerignore`:

```gitignore
.git
.worktrees
.env
.env.*
!.env.example
node_modules
test
docs
README.md
```

`COPY package.json`, `COPY src`, `COPY data`만 사용하므로 `.env`가 이미지에 복사되지 않으며, `.dockerignore`는 빌드 컨텍스트도 줄인다.

- [ ] **Step 4: Compose 런타임 구성을 작성한다**

Create `compose.yaml`:

```yaml
services:
  game-qna-api:
    build:
      context: .
    env_file:
      - .env
    ports:
      - "${PORT:-3000}:3000"
    restart: unless-stopped
```

- [ ] **Step 5: Compose 구성을 검증한다**

Run: `docker compose config`

Expected: `game-qna-api` 서비스, `3000:3000` 기본 포트 매핑, `.env` 기반 환경변수 설정이 오류 없이 출력된다. 실제 키는 출력에 포함시키지 않는다.

- [ ] **Step 6: 컨테이너를 빌드하고 상태 경로를 검증한다**

Run:

```powershell
docker compose up --build -d
Invoke-RestMethod http://127.0.0.1:3000/health
Invoke-RestMethod http://127.0.0.1:3000/sources
docker compose down
```

Expected: `/health`가 `status: ok`, `/sources`가 CC0 출처 배열을 반환하고, 마지막 명령이 컨테이너와 네트워크를 중지한다.

- [ ] **Step 7: 커밋한다**

```bash
git add Dockerfile .dockerignore compose.yaml
git commit -m "feat: add Docker deployment configuration"
```

### Task 2: Docker 운영 안내 추가

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1의 `compose.yaml`, 기존 `.env.example`, `/health`, `/sources`
- Produces: 개발·운영 담당자가 키를 저장소에 넣지 않고 서비스 실행·상태 확인·중지를 수행할 수 있는 안내

- [ ] **Step 1: README에 Docker 실행 절을 추가한다**

`## 실행` 절 뒤에 다음 내용을 추가한다:

```markdown
## Docker 실행

1. `.env.example`을 `.env`로 복사하고 실제 `API_KEY`, `MODEL_API_KEY`를 입력합니다. `.env`는 저장소에 커밋하지 않습니다.
2. `docker compose up --build -d`로 실행합니다.
3. `Invoke-RestMethod http://127.0.0.1:3000/health`로 상태를 확인합니다.
4. 출처 확인은 `Invoke-RestMethod http://127.0.0.1:3000/sources`를 사용합니다.
5. 중지는 `docker compose down`을 사용합니다.

호스트 포트는 `.env`의 `PORT`로 변경할 수 있으며, 기본값은 `3000`입니다. 실제 모델 키와 API 키는 Dockerfile, Compose 파일, 브라우저 코드에 넣지 않습니다.
```

- [ ] **Step 2: 기존 테스트와 문서 변경을 검증한다**

Run: `npm.cmd test`

Expected: 모든 Node 테스트가 통과한다. README에는 실제 키 문자열이 없고 `.env` 파일을 커밋하지 않는다는 안내가 있다.

- [ ] **Step 3: 커밋한다**

```bash
git add README.md
git commit -m "docs: add Docker run instructions"
```

### Task 3: 최종 배포 확인과 원격 반영

**Files:**
- Modify: 없음

**Interfaces:**
- Consumes: Task 1의 Compose 서비스, Task 2의 운영 문서
- Produces: GitHub `codex/langchain-mvp` 브랜치에 검증된 Docker 배포 구성

- [ ] **Step 1: 작업 트리와 테스트 상태를 확인한다**

Run:

```powershell
git status --short
npm.cmd test
```

Expected: 작업 트리가 비어 있고 모든 테스트가 통과한다.

- [ ] **Step 2: 원격 브랜치에 푸시한다**

Run: `git push`

Expected: `codex/langchain-mvp` 브랜치의 Docker 관련 커밋이 GitHub에 반영된다. 열려 있는 PR이 있으면 변경 내용이 자동으로 추가된다.

## Self-Review

- Spec coverage: Dockerfile, 빌드 제외 규칙, Compose 환경변수 주입, 포트, 실행·상태 확인·중지 문서, 보안 제약, 검증 절차를 Task 1~3에 모두 반영했다.
- Placeholder scan: 미완성 표식과 미정 단계 없이 모든 생성 파일과 명령을 명시했다.
- Type consistency: Compose 서비스 이름 `game-qna-api`, 내부 포트 `3000`, 실행 명령 `npm start`, 상태 경로 `/health`와 `/sources`를 모든 작업에서 동일하게 사용한다.
