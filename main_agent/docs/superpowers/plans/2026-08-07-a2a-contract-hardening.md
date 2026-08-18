# A2A 계약 표준화 및 CAT 연동 강화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MAIN 저장소의 A2A 경계를 A2A 1.0 HTTP+JSON, Agent Card discovery, 환경변수 registry, Service Token, Task/Polling, CAT 오류 계약에 맞게 표준화한다.

**Architecture:** `AgentCard`와 `A2AError`를 공통 계약으로 확장하고, `AgentRegistry`가 환경변수 설정과 Card discovery를 담당한다. `A2AClient`는 Card의 HTTP+JSON interface를 선택해 인증된 요청을 보내며, 동기 message·완료 Task·polling 결과를 하나의 응답 모델로 정규화한다. FastAPI Task API와 React UI는 MAIN Task 상태를 polling한다.

**Tech Stack:** Python 3.12, FastAPI, httpx, Pydantic, pytest, pytest-asyncio, React, TypeScript, Docker Compose.

## Global Constraints

- 기존 `/a2a` JSON-RPC 호환 경로는 유지한다.
- CAT의 `/message:send`는 `application/a2a+json`으로 호출한다.
- Service Token과 API key는 소스·프론트엔드·로그에 기록하지 않는다.
- 기존 `GAME_QA_AGENT_URL` fallback을 제거하지 않는다.
- 새 동작은 반드시 failing test를 먼저 작성하고 확인한다.
- 관련 변경이 끝날 때마다 backend test, frontend build, Compose config를 재검증한다.

---

### Task 1: Agent Card와 A2A 응답 계약 확장

**Files:**
- Modify: `backend/app/contracts.py`
- Modify: `backend/app/a2a_client.py`
- Test: `backend/tests/test_contracts.py`
- Test: `backend/tests/test_a2a_client.py`

**Interfaces:**
- `AgentCard.supported_interfaces: list[AgentInterface]`
- `A2AClient.send_message(agent_url: str, request: dict, headers: dict | None = None) -> dict`
- `A2AClient`가 message와 완료 task/artifact 텍스트를 `answer`로 정규화

- [ ] **Step 1: HTTP+JSON Card와 완료 Task 응답 테스트 작성**
- [ ] **Step 2: 테스트가 Card 필드 누락과 Task 응답 미해석으로 실패하는지 확인**
- [ ] **Step 3: AgentInterface, security scheme, response extraction 구현**
- [ ] **Step 4: `application/a2a+json`, requestId, context, evidence 전송 구현**
- [ ] **Step 5: 관련 테스트와 기존 A2A 테스트 실행**

### Task 2: 환경변수 기반 Agent registry와 Service Token

**Files:**
- Modify: `backend/app/registry.py`
- Modify: `backend/app/main.py`
- Modify: `docker-compose.yml`
- Create: `.env.example`
- Test: `backend/tests/test_registry.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- `AgentRegistry.from_environment(environ: Mapping[str, str]) -> AgentRegistry`
- `AgentConfig(name: str, base_url: str, token: str | None)`
- `A2AClient`가 AgentConfig token을 Bearer header로 사용

- [ ] **Step 1: 환경변수 registry와 token header 테스트 작성**
- [ ] **Step 2: 테스트 실패 확인**
- [ ] **Step 3: registry factory와 legacy URL fallback 구현**
- [ ] **Step 4: Compose 및 `.env.example` 설정 추가**
- [ ] **Step 5: registry·API·Compose contract 테스트 실행**

### Task 3: 표준 Task 결과와 polling

**Files:**
- Modify: `backend/app/a2a_client.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/task_store.py`
- Modify: `backend/app/contracts.py`
- Test: `backend/tests/test_a2a_client.py`
- Test: `backend/tests/test_api.py`
- Test: `backend/tests/test_task_store.py`

**Interfaces:**
- `A2AClient.poll_task(task_url: str, task_id: str, headers: dict | None = None) -> dict`
- `TaskRecord.agent_tasks: list[dict]` 또는 기존 result/event 구조를 통한 Agent Task 상태
- terminal states: `succeeded`, `failed`, `cancelled`

- [ ] **Step 1: polling 성공·timeout·실패 테스트 작성**
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: polling과 timeout 구현**
- [ ] **Step 4: Main background task가 정규화된 결과를 저장하도록 연결**
- [ ] **Step 5: backend 전체 테스트 실행**

### Task 4: CAT 오류 표준화와 예외 endpoint

**Files:**
- Create: `backend/app/errors.py`
- Modify: `backend/app/a2a_client.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_a2a_client.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- `A2AError(code: int, status: str, message: str, request_id: str | None = None)`
- CAT의 예외 endpoint는 별도 신규 경로가 아니라 기존 `POST /message:send`의 `application/a2a+json` 오류 응답 계약으로 고정한다.
- CAT status mapping: `INVALID_ARGUMENT=400`, `UNAUTHENTICATED=401`, `NOT_FOUND=404`, `UNAVAILABLE=503`, `INTERNAL=502`

- [ ] **Step 1: CAT error payload와 API 매핑 테스트 작성**
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: A2AError parsing 및 HTTPException 변환 구현**
- [ ] **Step 4: `/api/chats/{agent_name}/reply`와 `/api/tasks`에서 표준 오류를 안정된 JSON으로 노출**
- [ ] **Step 5: 오류·인증·404·503 테스트 실행**

### Task 5: Frontend polling과 통합 검증

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/scripts/task-utils-test.mjs`
- Test: `backend/tests/test_main_catalog_e2e.py`
- Modify: `README.md`
- Modify: `docs/integrations/catalog-game-qna.md`

**Interfaces:**
- `GET /api/tasks/{task_id}` polling until terminal status
- UI task status mapping: `queued`, `running`, `succeeded`, `failed`, `cancelled`

- [ ] **Step 1: polling state transition helper 테스트 작성**
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: UI polling 및 결과/event 반영 구현**
- [ ] **Step 4: 실행 문서에 env, token, Card, polling, 오류 계약 반영**
- [ ] **Step 5: `pytest -q`, frontend tests/build, `docker compose config` 실행**
- [ ] **Step 6: 실제 Catalog 연동 가능 여부를 별도 smoke test로 확인하고 결과 기록**

## Self-Review Checklist

- Agent Card interface 선택은 Task 1에서 다룬다.
- 환경변수와 token은 Task 2에서 다룬다.
- Task polling은 Task 3과 Task 5 양쪽에서 다룬다.
- CAT 오류는 Task 4에서 다룬다.
- 테스트·문서·Compose 검증은 Task 5에서 다룬다.
- 기존 `/a2a` 호환 경로와 legacy URL fallback을 유지한다.
