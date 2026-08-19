# Main AI Multi-Orchestrator 설계

## 목표

단일 컴퓨터에서 Docker로 실행되는 4개의 전문 Agent를 Main AI가 A2A 프로토콜로 연결하고, 사용자의 요청을 적절한 Agent에 배분한 뒤 실행 상태와 결과를 작업 관리형 Viewer로 제공한다.

## 범위

### 포함

- Main AI API와 멀티 오케스트레이터
- 4개 전문 Agent의 로컬 Docker 연결
- A2A Agent Card 조회 및 Agent Registry
- 단일, 순차, 병렬 작업 실행
- 작업 상태·로그·결과 저장
- 작업 테이블과 우측 AI Chat 중심의 Viewer UI
- 로컬 실행을 위한 Docker Compose

### 제외

- 유료 외부 Agent 플랫폼
- 사용자 인증·권한 관리
- 실제 전문 Agent 내부 기능의 전면 재구현
- 클라우드 배포

## 아키텍처

```text
Browser
  |
  v
Main AI UI/API :8000
  |
  +-- Request Parser
  +-- Multi-Orchestrator
  +-- Agent Registry
  +-- A2A Client
  +-- Task Manager
  +-- Result Aggregator
  |
  +--> workmate-agent :8001
  +--> video-agent    :8002
  +--> dev-agent      :8003
  +--> game-qa-agent  :8004
```

전문 Agent는 내부 모델 구현을 외부에 노출하지 않는다. Main AI는 Agent Card와 A2A 엔드포인트를 사용해 기능을 탐색하고 작업을 요청한다. 초기 바인딩은 JSON-RPC over HTTP를 사용하며, 스트리밍이 필요한 Agent는 SSE를 선언적으로 지원한다.

## Git 및 Docker 구조

```text
main-agent/
├── main-ai/          # Main AI 애플리케이션
├── workmate-agent/   # 업무지원 Agent 체크아웃 폴더
├── video-agent/      # 영상 생성 Agent 체크아웃 폴더
├── dev-agent/        # 개발 보조 Agent 체크아웃 폴더
├── game-qa-agent/    # 게임 Q&A Agent 체크아웃 폴더
└── docker-compose.yml
```

개발 단위는 Main Agent 1개와 전문 Agent 4개로 구성한다. 각 폴더는 독립 Git 브랜치 또는 저장소를 체크아웃할 수 있으며, Compose 서비스명으로 컨테이너 간 통신한다.

## 오케스트레이션 동작

1. 사용자가 Chat 또는 작업 입력창에서 요청을 제출한다.
2. Main AI가 요청을 검증하고 실행 의도를 추출한다.
3. Registry가 등록된 Agent Card와 skill 목록을 확인한다.
4. Orchestrator가 단일·순차·병렬 실행 계획을 만든다.
5. A2A Client가 각 Agent에 task를 전달한다.
6. Task Manager가 대기·실행·완료·실패·취소 상태를 추적한다.
7. Result Aggregator가 결과, 출처, 로그, 오류를 공통 형식으로 합친다.
8. Viewer가 작업 테이블과 Chat 패널에 결과를 표시한다.

## UI 설계

참고 UI의 3단 레이아웃을 사용한다.

### 좌측 사이드바

- Home
- Roles
- Skills
- Meetings
- My Tasks
- More
- AI Chats 목록
- Spaces 및 Channels

### 중앙 작업 영역

- 프로젝트 제목
- 작업 체크박스
- Task 이름
- Owner
- Status 배지
- 연결된 Agent 버튼
- 하단 Add task
- Agent 실행 중에는 상태, 진행률, 마지막 이벤트를 표시

### 우측 AI Chat

- 대화 메시지 영역
- 실행 중인 Agent와 Task ID 표시
- 결과 요약 및 원문 결과 전환
- 메시지 입력창과 전송 버튼
- 실패 시 재시도 버튼

초기 Viewer는 실제 데이터베이스 없이도 Mock task와 Mock Agent Card로 동작할 수 있어야 한다. 이후 SQLite 저장소와 실제 A2A Agent를 연결한다.

## 공통 작업 상태

```text
queued -> running -> succeeded
                  \-> failed
                  \-> cancelled
```

각 작업은 `task_id`, `request`, `selected_agents`, `status`, `events`, `result`, `error`, `created_at`, `updated_at`을 가진다.

## 실패 처리

- Agent Card 조회 실패: 해당 Agent를 unavailable로 표시하고 다른 Agent만 사용
- 연결 timeout: 제한된 횟수로 재시도한 뒤 failed 처리
- 부분 실패: 성공한 결과를 보존하고 실패한 Agent와 원인을 함께 표시
- 전체 계획 실패: 사용자에게 실행 계획과 실패 지점을 제공
- 컨테이너 비정상: health 상태를 UI에 표시하고 호출 전에 차단

## MVP 성공 기준

- `docker compose up`으로 Main AI와 4개 Mock Agent가 실행된다.
- Main AI가 4개 Agent의 Agent Card를 조회한다.
- 단일 Agent 요청이 A2A 형식으로 전달되고 결과가 작업 테이블과 Chat에 표시된다.
- 2개 이상의 Agent를 순차 또는 병렬 실행할 수 있다.
- 한 Agent가 실패해도 나머지 결과와 실패 정보가 Viewer에 표시된다.
- UI가 참고 이미지와 같은 좌측 네비게이션·중앙 테이블·우측 Chat 구조를 갖는다.

## 기술 선택

- Backend: Python FastAPI
- Orchestration: 명시적 Python 실행 계획 및 상태 머신
- A2A: JSON-RPC over HTTP, 필요 시 SSE
- Storage: SQLite
- UI: React 또는 초기 MVP용 Streamlit 중 하나를 구현 단계에서 확정
- Runtime: Docker Compose
- 테스트: pytest 및 API 통합 테스트

## 결정이 필요한 항목

UI 구현 기술은 React 기반의 정교한 참고 UI 재현과 Streamlit 기반의 빠른 MVP 중 하나를 구현 계획 단계에서 확정해야 한다. 권장안은 참고 이미지의 레이아웃과 상호작용을 유지하기 쉬운 React + FastAPI 조합이다.
