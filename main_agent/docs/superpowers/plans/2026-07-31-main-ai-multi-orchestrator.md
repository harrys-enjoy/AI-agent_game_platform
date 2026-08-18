# Main AI Multi-Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Docker-based Main AI that discovers four specialist Agents through A2A, executes single/sequential/parallel plans, and presents task status and results in a three-pane viewer.

**Architecture:** FastAPI hosts the Main AI API and React hosts the viewer. A Python orchestrator owns routing and task state, while an A2A client communicates with four local services through JSON-RPC over HTTP. SQLite stores tasks and events; Docker Compose supplies the local runtime and service discovery.

**Tech Stack:** Python 3.12, FastAPI, httpx, Pydantic, SQLite, pytest, React, TypeScript, Vite, Docker Compose.

## Global Constraints

- All services run locally through Docker Compose; no paid Agent platform is required.
- Main AI communicates with specialist Agents only through the A2A client boundary.
- Initial A2A binding is JSON-RPC over HTTP; streaming is optional and implemented only after the non-streaming path works.
- Specialist services expose Agent Card metadata and a health endpoint.
- Every production behavior is implemented test-first: write a failing test, observe the expected failure, implement the minimum behavior, then run the focused and full test suites.
- The first milestone uses deterministic Mock Agents; real specialist repositories are connected only after the orchestration contract is verified.

---

### Task 1: Bootstrap the Main AI monorepo and test tooling

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `.gitignore`

**Interfaces:**
- Produces `GET /health` returning `{ "status": "ok" }`.
- Produces a runnable frontend shell at `/`.

- [ ] **Step 1: Write the failing backend health test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health_returns_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the focused test and verify it fails because `app` is missing**

Run: `cd backend; python -m pytest tests/test_health.py -q`

Expected: FAIL with an import or missing-route error.

- [ ] **Step 3: Add the minimal FastAPI app and dependency configuration**

Implement `app = FastAPI()` and the `/health` route. Pin FastAPI, httpx, pydantic, pytest, and pytest-asyncio in `pyproject.toml`.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `cd backend; python -m pytest tests/test_health.py -q`

Expected: PASS.

- [ ] **Step 5: Create the Vite React shell and run its build**

Run: `cd frontend; npm install; npm run build`

Expected: a successful production build.

- [ ] **Step 6: Commit the bootstrap changes**

```bash
git add backend frontend .gitignore
git commit -m "feat: bootstrap main ai workspace"
```

### Task 2: Define task, event, Agent Card, and result contracts

**Files:**
- Create: `backend/app/contracts.py`
- Create: `backend/tests/test_contracts.py`

**Interfaces:**
- `AgentCard(name: str, description: str, url: str, skills: list[AgentSkill], streaming: bool)`
- `TaskRecord(task_id: str, request: str, selected_agents: list[str], status: TaskStatus, events: list[TaskEvent], result: dict | None, error: str | None)`
- `TaskStatus = queued | running | succeeded | failed | cancelled`
- `TaskEvent(timestamp: datetime, agent: str | None, type: str, message: str)`

- [ ] **Step 1: Write failing validation tests for valid cards and invalid task statuses**

```python
import pytest
from pydantic import ValidationError
from app.contracts import AgentCard, TaskRecord


def test_agent_card_preserves_declared_skills():
    card = AgentCard(
        name="workmate-agent",
        description="업무지원 Agent",
        url="http://workmate-agent:8001/a2a",
        skills=[{"id": "daily_briefing", "name": "일일 브리핑"}],
        streaming=True,
    )
    assert card.skills[0].id == "daily_briefing"


def test_task_rejects_unknown_status():
    with pytest.raises(ValidationError):
        TaskRecord(task_id="t1", request="x", selected_agents=[], status="unknown")
```

- [ ] **Step 2: Run tests and verify the contract module is missing**

Run: `cd backend; python -m pytest tests/test_contracts.py -q`

Expected: FAIL with an import error.

- [ ] **Step 3: Implement the Pydantic models and enums**

Use UTC timestamps, default empty event lists, and optional result/error fields. Do not add fields that are not used by the MVP.

- [ ] **Step 4: Run focused and full backend tests**

Run: `cd backend; python -m pytest tests/test_contracts.py tests/test_health.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contracts**

```bash
git add backend/app/contracts.py backend/tests/test_contracts.py
git commit -m "feat: define orchestration contracts"
```

### Task 3: Implement Agent Registry and A2A Agent Card discovery

**Files:**
- Create: `backend/app/registry.py`
- Create: `backend/app/a2a_client.py`
- Create: `backend/tests/test_registry.py`
- Create: `backend/tests/test_a2a_client.py`

**Interfaces:**
- `AgentRegistry.register(name: str, card_url: str) -> None`
- `AgentRegistry.refresh() -> dict[str, AgentCard]`
- `AgentRegistry.available() -> list[AgentCard]`
- `A2AClient.get_agent_card(card_url: str) -> AgentCard`
- `A2AClient.send_message(agent_url: str, request: dict) -> dict`

- [ ] **Step 1: Write failing registry tests for discovery and unavailable agents**

Test that one valid Agent Card is registered and that a failed HTTP request marks the agent unavailable without deleting its configuration.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd backend; python -m pytest tests/test_registry.py tests/test_a2a_client.py -q`

Expected: FAIL because the registry and client do not exist.

- [ ] **Step 3: Implement the HTTP client and registry**

Use `httpx.AsyncClient` with a timeout. Fetch `/.well-known/agent-card.json`, parse it into `AgentCard`, and store availability/error metadata separately from the card. Send JSON-RPC 2.0 `SendMessage` requests to the URL declared by the card.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `cd backend; python -m pytest tests/test_registry.py tests/test_a2a_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the registry and client**

```bash
git add backend/app/registry.py backend/app/a2a_client.py backend/tests/test_registry.py backend/tests/test_a2a_client.py
git commit -m "feat: add local a2a agent discovery"
```

### Task 4: Build the orchestration planner and execution engine

**Files:**
- Create: `backend/app/orchestrator.py`
- Create: `backend/app/task_store.py`
- Create: `backend/tests/test_orchestrator.py`
- Create: `backend/tests/test_task_store.py`

**Interfaces:**
- `Orchestrator.create_plan(request: str, cards: list[AgentCard]) -> ExecutionPlan`
- `Orchestrator.run(plan: ExecutionPlan) -> TaskRecord`
- `TaskStore.create(request: str, selected_agents: list[str]) -> TaskRecord`
- `TaskStore.append_event(task_id: str, event: TaskEvent) -> TaskRecord`
- `TaskStore.update(task_id: str, **changes) -> TaskRecord`

- [ ] **Step 1: Write failing tests for single, sequential, and parallel plans**

Use deterministic fake A2A responses. Assert that a request mentioning code review selects `dev-agent`, a request requiring two skills creates ordered steps, and independent steps run concurrently while preserving both results.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd backend; python -m pytest tests/test_orchestrator.py tests/test_task_store.py -q`

Expected: FAIL because planner, store, and executor are missing.

- [ ] **Step 3: Implement SQLite task storage**

Create tables for `tasks` and `task_events`. Store JSON for selected agents, events, and results. Expose synchronous repository methods behind `TaskStore` so the orchestration logic is easy to test.

- [ ] **Step 4: Implement explicit deterministic planning rules**

Use skill IDs from Agent Cards. Route code, PR, CI, or deployment requests to `dev-agent`; video, storyboard, or render requests to `video-agent`; meeting, report, or priority requests to `workmate-agent`; game lore, design, or Q&A requests to `game-qa-agent`. For compound requests, create steps with dependencies; independent steps run with `asyncio.gather`.

- [ ] **Step 5: Implement state transitions and partial failure handling**

Transition `queued -> running -> succeeded|failed`. Preserve successful results when one parallel child fails and add an event describing the failed Agent and error.

- [ ] **Step 6: Run focused and full backend tests**

Run: `cd backend; python -m pytest -q`

Expected: PASS.

- [ ] **Step 7: Commit orchestration**

```bash
git add backend/app/orchestrator.py backend/app/task_store.py backend/tests/test_orchestrator.py backend/tests/test_task_store.py
git commit -m "feat: add multi-agent orchestration"
```

### Task 5: Expose Main AI task and registry APIs

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/app/api.py`
- Create: `backend/tests/test_api.py`

**Interfaces:**
- `GET /api/agents`
- `POST /api/tasks` with `{ "request": str }`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/retry`

- [ ] **Step 1: Write failing API tests**

Test that `POST /api/tasks` returns `202` with a task ID, `GET /api/tasks/{id}` returns the task record, and an unavailable Agent is reported in `GET /api/agents`.

- [ ] **Step 2: Run the API tests and verify they fail**

Run: `cd backend; python -m pytest tests/test_api.py -q`

Expected: FAIL because routes are not registered.

- [ ] **Step 3: Implement dependency wiring and routes**

Construct one registry, A2A client, task store, and orchestrator at application startup. Return stable JSON shapes based on `contracts.py`. Run task execution in a background task and immediately return the queued record.

- [ ] **Step 4: Run API and full backend tests**

Run: `cd backend; python -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit the Main AI API**

```bash
git add backend/app/main.py backend/app/api.py backend/tests/test_api.py
git commit -m "feat: expose main ai task api"
```

### Task 6: Add deterministic Mock A2A Agents and Docker Compose

**Files:**
- Create: `mock-agents/base/Dockerfile`
- Create: `mock-agents/base/requirements.txt`
- Create: `mock-agents/server.py`
- Create: `mock-agents/cards/workmate-agent.json`
- Create: `mock-agents/cards/video-agent.json`
- Create: `mock-agents/cards/dev-agent.json`
- Create: `mock-agents/cards/game-qa-agent.json`
- Create: `docker-compose.yml`
- Create: `backend/tests/test_compose_contract.py`

**Interfaces:**
- Each mock service exposes `GET /.well-known/agent-card.json`, `GET /health`, and a JSON-RPC A2A endpoint.
- Each mock returns a deterministic result containing `agent`, `skill`, and `summary`.

- [ ] **Step 1: Write failing compose contract tests**

Assert that the Compose file defines `main-agent`, `workmate-agent`, `video-agent`, `dev-agent`, and `game-qa-agent`, with the expected internal ports.

- [ ] **Step 2: Run the test and verify it fails because Compose is missing**

Run: `cd backend; python -m pytest tests/test_compose_contract.py -q`

Expected: FAIL because `docker-compose.yml` is missing.

- [ ] **Step 3: Implement the mock A2A server and four Agent Cards**

Keep the server deterministic and free of external model calls. Select the response skill from the incoming request and return a completed task result.

- [ ] **Step 4: Add Compose services and environment configuration**

Build Main AI and the mock server image with service-specific `AGENT_NAME`, `AGENT_PORT`, and `CARD_FILE` values. Do not place API keys in the repository.

- [ ] **Step 5: Run contract tests and a Compose smoke test**

Run: `cd backend; python -m pytest tests/test_compose_contract.py -q`

Then run: `docker compose config`

Expected: PASS and valid Compose configuration.

- [ ] **Step 6: Commit the local runtime**

```bash
git add docker-compose.yml mock-agents backend/tests/test_compose_contract.py
git commit -m "feat: add local mock a2a agents"
```

### Task 7: Implement the reference Viewer UI

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/components/TaskTable.tsx`
- Create: `frontend/src/components/ChatPanel.tsx`
- Create: `frontend/src/components/StatusBadge.tsx`
- Create: `frontend/src/App.test.tsx`

**Interfaces:**
- `TaskTable` consumes `TaskRecord[]` and `onSelectTask(taskId)`.
- `ChatPanel` consumes messages and emits `onSubmit(request)`.
- `api.createTask(request)` returns `TaskRecord`.
- `api.getTask(taskId)` returns `TaskRecord`.

- [ ] **Step 1: Write failing component tests**

Test that the app renders Home/Roles/Skills/Meetings/My Tasks navigation, task rows with Owner/Status/Agent columns, and a chat input with a send control.

- [ ] **Step 2: Run frontend tests and verify they fail**

Run: `cd frontend; npm test -- --run`

Expected: FAIL because the components are not implemented.

- [ ] **Step 3: Implement the three-pane layout**

Use CSS Grid with a fixed dark sidebar, flexible central table, and fixed-width right chat panel. Use the reference palette: dark sidebar, pale main background, white cards, blue Agent buttons, and green/orange/red status badges. Ensure the layout collapses to one column below 960px.

- [ ] **Step 4: Connect task submission and polling**

Submit chat requests to `POST /api/tasks`, append the returned task to the table, and poll `GET /api/tasks/{task_id}` every 1 second until the task reaches a terminal state. Display events and results in the chat panel.

- [ ] **Step 5: Run frontend tests and build**

Run: `cd frontend; npm test -- --run; npm run build`

Expected: PASS and successful build.

- [ ] **Step 6: Commit the Viewer**

```bash
git add frontend
git commit -m "feat: add task viewer and ai chat"
```

### Task 8: Verify end-to-end orchestration and document operations

**Files:**
- Create: `backend/tests/test_e2e_local.py`
- Create: `README.md`
- Create: `.env.example`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write the failing end-to-end test**

Start the local stack and test: agent discovery returns four cards, a game Q&A request selects `game-qa-agent`, a compound video request produces multiple events, and a simulated failing Agent leaves a partial result.

- [ ] **Step 2: Run the test against the stack and verify the missing behavior**

Run: `docker compose up --build -d; python -m pytest backend/tests/test_e2e_local.py -q`

Expected: FAIL only for not-yet-wired behavior.

- [ ] **Step 3: Implement the minimum wiring and health checks**

Configure the frontend API base URL, add Compose health checks, and ensure Main AI waits for service health before discovery.

- [ ] **Step 4: Run the complete verification suite**

Run: `cd backend; python -m pytest -q`

Run: `cd frontend; npm test -- --run; npm run build`

Run: `docker compose config`

Expected: all tests pass, frontend builds, and Compose validates.

- [ ] **Step 5: Document local startup and branch checkout**

README must include the five-folder layout, how to place each Agent branch, how to start the stack, how to inspect Agent Cards, how to run a task, and how to replace a Mock Agent with a real A2A service.

- [ ] **Step 6: Commit the verification and documentation**

```bash
git add README.md .env.example docker-compose.yml backend/tests/test_e2e_local.py
git commit -m "docs: add local orchestration runbook"
```

## Self-Review

- The plan covers Main AI API, A2A discovery and calls, multi-agent sequential/parallel execution, task persistence, Docker runtime, reference Viewer UI, failure handling, and operations documentation.
- No production feature is introduced without a preceding failing test in its task.
- The A2A client boundary is explicit, so specialist Agent internals can be replaced without changing the orchestrator contract.
- Mock Agents are used first to keep the first milestone local and deterministic; real Agent branches are an integration step after the contract is stable.
