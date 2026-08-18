# Workmate Agent 메인 UI 연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `workmate-agent-main`을 메인 Docker Compose와 `Workmate AI` 채팅에 연결한다.

**Architecture:** 기존 `workmate-agent` 서비스명과 포트는 유지하고 빌드 컨텍스트만 실제 에이전트 폴더로 교체한다. 메인 A2A 클라이언트에는 Workmate가 요구하는 인증·버전·skill 데이터 형식을 추가한다.

**Tech Stack:** Docker Compose, FastAPI, Python, httpx, pytest, Pydantic.

## Global Constraints

- Workmate 서비스의 내부 주소는 `http://workmate-agent:8001`을 유지한다.
- A2A 버전은 `1.0`이며 HTTP+JSON 요청에는 `A2A-Version: 1.0`을 포함한다.
- Workmate 서비스 토큰은 메인 API와 Workmate 컨테이너에 동일하게 전달한다.
- 기존 다른 에이전트의 호출 동작과 사용자 변경 사항을 보존한다.

### Task 1: Workmate 요청 계약 테스트 추가

**Files:**
- Modify: `backend/tests/test_a2a_client.py`
- Test: `backend/tests/test_a2a_client.py`

**Interfaces:**
- Consumes: existing `A2AClient.send_message()`.
- Produces: failing regression tests for the Workmate HTTP+JSON envelope.

- [ ] **Step 1: Write the failing test**

  Add a transport test that calls `send_message("http://workmate-agent:8001/a2a/message:send", {"message": "오늘 업무", "skill_id": "daily_briefing"})` and asserts the request has `A2A-Version: 1.0`, bearer authorization when supplied, and `message.parts[0].data.skill_id == "daily_briefing"`.

- [ ] **Step 2: Run test to verify it fails**

  Run: `python -m pytest backend/tests/test_a2a_client.py -q`
  Expected: FAIL because the current client omits `A2A-Version` and sends only text parts.

- [ ] **Step 3: Commit**

  Do not commit yet; implementation and configuration are verified together in Task 3.

### Task 2: Compose actual Workmate service

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `workmate-agent-main/compose.yaml`, port `8001`, `/health/ready`.
- Produces: a `workmate-agent` service built from `../workmate-agent-main` with shared token configuration.

- [ ] **Step 1: Update Compose configuration**

  Set the service build context to `../workmate-agent-main`, pass `WORKMATE_SERVICE_TOKEN`, set `APP_BASE_URL=http://workmate-agent:8001/a2a`, expose port `8001`, and add the readiness healthcheck. Make `main-agent` depend on `workmate-agent` being healthy.

- [ ] **Step 2: Update environment example**

  Add `WORKMATE_SERVICE_TOKEN` with a non-secret example placeholder and document that the same value is used by both services.

- [ ] **Step 3: Validate Compose config**

  Run: `docker compose config`
  Expected: valid rendered configuration with the external build context and shared token wiring.

### Task 3: Implement minimal A2A compatibility and verify

**Files:**
- Modify: `backend/app/a2a_client.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_a2a_client.py`

**Interfaces:**
- Consumes: Task 1 failing contract and Task 2 service settings.
- Produces: Workmate-compatible request envelopes while preserving generic JSON-RPC behavior.

- [ ] **Step 1: Implement the smallest client change**

  Add `A2A-Version: 1.0` only to HTTP+JSON requests. When `request` contains `skill_id`, put it in the first message part as `data` with the original message and locale; retain the existing text-part behavior for requests without a skill id. Preserve existing authorization headers.

- [ ] **Step 2: Pass the Workmate skill from the chat request**

  Add `skill_id="daily_briefing"` to the Workmate request path without changing other chat agents.

- [ ] **Step 3: Run focused tests**

  Run: `python -m pytest backend/tests/test_a2a_client.py backend/tests/test_api.py -q`
  Expected: PASS.

- [ ] **Step 4: Run the full backend suite**

  Run: `python -m pytest backend/tests -q`
  Expected: PASS with no new failures.

- [ ] **Step 5: Run integration smoke checks**

  Run: `docker compose up --build -d`, then check `http://localhost:8000/health`, `http://localhost:8000/api/agents`, and Workmate `http://localhost:8001/health/ready`; send one `Workmate AI` chat request through the API and verify a succeeded response.

- [ ] **Step 6: Commit**

  Run: `git add docker-compose.yml .env.example backend/app/a2a_client.py backend/app/main.py backend/tests/test_a2a_client.py docs/superpowers/specs/2026-08-07-workmate-agent-integration-design.md docs/superpowers/plans/2026-08-07-workmate-agent-integration.md && git commit -m "feat: connect workmate agent to main orchestrator"`
