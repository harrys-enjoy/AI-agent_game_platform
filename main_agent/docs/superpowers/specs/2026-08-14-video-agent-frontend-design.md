# Video-agent 전용 프론트엔드 페이지 설계

## 목표

video-agent(`video_draft_pipeline`)와 직접 상호작용하는 전용 페이지를 MAIN 프론트엔드에 추가한다. 사용자는 자유 채팅 또는 구조화된 폼 중 하나로 영상 생성 브리프를 작성하고, 제출부터 완료(또는 수동 수정, 실패, 취소)까지 전체 생명주기를 이 페이지 한 곳에서 확인·처리할 수 있다.

## 배경 / 결정 사항

- **위치**: `frontend/src/` 내 신규 독립 페이지. 기존 `App.tsx`의 4-에이전트 통합 채팅 뷰는 건드리지 않는다. 사이드바에서 이 페이지로 라우팅하는 로직(수동 선택 vs. LLM 자동 라우팅)은 별도 작업 범위이며, 여기서는 페이지 자체만 다룬다.
- **통신 경로**: 프론트엔드는 video-agent에 직접 접속하지 않고 반드시 MAIN 백엔드를 경유한다. `2026-08-13-a2a-protocol-migration-design.md` §18(원문: *A2A endpoints own protocol/schema validation; UI API owns file uploads and screen requests*)과 기존 resume 프록시(`2026-08-10-video-agent-resume-scene-upload-design.md`) 선례를 따른 것으로, 서비스 토큰을 브라우저에 노출하지 않고 기존 라우팅/인증 계층과 일관성을 유지한다.
- **입력 방식**: 채팅형과 폼형 둘 다 이 페이지 안에서 지원한다(탭 전환). 두 방식 모두 최종적으로는 video-agent가 이해하는 자유 텍스트 한 문장으로 변환되어 전송된다 — video-agent 서버에는 별도의 구조화 스키마 입력 경로가 없고, `brief_intake.py`가 정규식 힌트 + Gemini 판단으로 자유 텍스트만 파싱하기 때문이다.
- **작업 범위**: 전체 생명주기(SUBMITTED → WORKING → INPUT_REQUIRED ↔ resume → COMPLETED/FAILED/CANCELED/REJECTED). 이번 페이지에서는 동시에 하나의 활성 작업만 다룬다 — 작업 히스토리/다중 작업 목록은 비범위. (참고: 향후 MAIN에 DB 기반 영속 저장이 도입되면 이 범위 결정을 재검토할 수 있음 — 아직 확정된 계획 아님.)
- **컴포넌트 스택**: 이 페이지에 한해 Tailwind CSS + Radix 기반 컴포넌트 프리미티브(shadcn 스타일로 레포에 직접 복사, npm 의존성 아님)를 새로 도입한다. MAIN 프론트엔드의 나머지 부분(라우터 없음, UI 라이브러리 없음)과는 의도적으로 다른 스타일 — 이 페이지만의 결정이며 전면 마이그레이션이 아니다.
- **테스트 스택**: 이 페이지와 신규 백엔드 라우트에 한해 Vitest + React Testing Library를 도입한다. 기존 손으로 짠 Node 테스트 스크립트 방식은 이 페이지 범위 밖에서는 그대로 둔다.
- **기존 `A2AClient` 버그**: Explore 조사로 확인된 세 가지 결함(폴링 GET에 `A2A-Version` 헤더 누락 → 401, `messageId`가 하드코딩된 `"main-agent"` 리터럴이라 중복제거 로직이 이후 모든 요청에 첫 결과를 재생, 8개 상태 중 3개만 인식)은 **새 라우트에서 기존 클라이언트를 재사용하지 않는 것으로 회피**한다. `A2AClient`/`registry.py` 자체는 수정하지 않는다(비범위) — 다른 에이전트가 이미 그 코드를 쓰고 있고, `LIVE_AGENT_DISCOVERY`가 기본 꺼짐이라 현재는 휴면 버그이기 때문. 새 라우트는 처음부터 올바르게 구현한다.

## 범위

- 신규 백엔드 라우트 3종 (아래 참조). 기존 `POST /api/video-agent/tasks/{task_id}/scenes/{scene_id}/resume`는 그대로 유지·재사용.
- 신규 최소 video-agent HTTP 클라이언트 (raw `httpx`, `A2AClient` 미사용).
- 신규 프론트엔드 페이지: Composer(Chat/Form 탭), StatusBadge, Canvas(상태별 뷰), 5초 폴링 훅.
- 신규 컴포넌트 프리미티브 세트(Tailwind + Radix 기반) 도입.
- 신규 Vitest + RTL 테스트 인프라(이 페이지 범위).

## 비범위

- 사이드바에서 이 페이지로의 라우팅/에이전트 선택 로직(수동 vs. LLM 자동) — 별도 작업.
- 다중 동시 작업, 작업 히스토리 목록, 영속 DB 저장.
- 기존 `A2AClient`/`registry.py`/`/api/chats/*`/`/api/tasks/*`(범용) 라우트 수정.
- video-agent 저장소(`video_draft_pipeline`) 자체 변경 — A2A 마이그레이션에서 이미 완료됨.
- MAIN 프론트엔드 다른 페이지/에이전트에 Tailwind·Radix·Vitest 확대 적용.

## 설계

### 백엔드: 신규 라우트

```
POST /api/video-agent/tasks
  body: { message: str }  # Chat/Form 두 composer 모두 최종적으로 이 하나의 문자열 필드로 수렴
  → video-agent POST /a2a/message:send 프록시 (새 UUID messageId 매 호출 생성)
  → { taskId, status, ... } 반환

GET  /api/video-agent/tasks/{task_id}
  → video-agent GET /a2a/tasks/{task_id} 를 매 호출마다 "그대로" 재조회하는 live-proxy
  → 내부적으로 폴링 루프나 타임아웃을 갖지 않는다 — 프론트엔드가 5초 간격으로 이 엔드포인트를
    반복 호출하며, 응답은 video-agent의 현재 상태를 그대로 반영한다.
  → artifacts[].parts[]의 text와 data 파트를 모두 읽어 구조화 필드(output_video_url,
    unresolvedScenes)를 누락 없이 전달한다.

POST /api/video-agent/tasks/{task_id}/cancel
  → video-agent POST /a2a/tasks/{id}:cancel 프록시
```

기존 `.../scenes/{scene_id}/resume`는 변경 없이 그대로 사용.

새 클라이언트는 모든 요청(POST/GET 공통)에 `Authorization: Bearer {VIDEO_SERVICE_TOKEN}` + `A2A-Version: 1.0` 헤더를 빠짐없이 부착하고, A2A 8개 상태 전체를 그대로 전달한다(MAIN 자체의 5-상태 `TaskStatus` enum으로 축소하지 않음 — video-agent 상태를 그대로 프론트엔드에 노출).

### live-proxy 폴링 패턴을 선택한 이유

MAIN의 기존 `/api/tasks` 패턴(백그라운드 디스패치 + 내부 폴루프 + 30초 타임아웃)은 실측 렌더 시간(~10분)보다 훨씬 짧고, `INPUT_REQUIRED` 상태를 표현할 방법도 없다(`contracts.py`의 `TaskStatus`는 5종뿐). live-proxy 방식은 MAIN이 상태를 따로 저장·판단하지 않고 매 폴링마다 video-agent에 직접 재질의하므로, INPUT_REQUIRED → resume → WORKING → COMPLETED 전이를 MAIN 쪽 로직 없이 자연스럽게 반영한다.

### 프론트엔드 레이아웃 (B안 — 좌측 컨트롤 / 우측 캔버스)

좌측 패널: `ComposerTabs`(Chat/Form 전환, 각 탭 draft 유지), `ChatComposer`(자유 텍스트), `FormComposer`(브리프 필수 + preset/scene_type/duration_sec/max_budget_usd 선택), `StatusBadge`(경과 시간 카운터 포함), `CancelButton`(SUBMITTED/WORKING에서만 노출).

우측 캔버스: 상태별 단일 뷰 — 대기 시 안내 문구, WORKING 시 불확정 스피너(video-agent가 세부 진행률을 제공하지 않으므로 가짜 프로그레스바 없음), COMPLETED 시 `<video>` 플레이어, INPUT_REQUIRED 시 씬별 업로드 카드 목록, FAILED/CANCELED/REJECTED 시 에러 뷰 + 재시도 버튼.

`FormComposer`는 별도 전송 포맷이 없으므로 구조화 필드를 `brief_intake.py`의 정규식 힌트와 일치하는 한국어 문장으로 직접 조립한다. 예: `"{brief} {duration_sec}초로, {preset} 프리셋, {scene_type} 씬으로 만들어줘"`.

### 폴링

`GET /api/video-agent/tasks/{id}`를 5초 간격으로 호출. 종료 상태(COMPLETED/FAILED/CANCELED/REJECTED)에서 중단. INPUT_REQUIRED에서는 중단이 아니라 일시정지하며, 업로드 성공 후 자동 재개. 일시적 fetch 실패는 즉시 에러로 취급하지 않고 "재연결 중" 배너만 표시, 연속 3회 실패 시에만 해제 가능한 에러 배너로 격상.

### 오류 처리

- video-agent 연결 불가 → 502, 명확한 메시지 본문 (`"video-agent unreachable"`).
- video-agent 401(토큰 오설정) → 502로 통일하되 원인 구분 메시지("video-agent auth misconfigured").
- 예상치 못한 응답 형태 → 방어적 파싱(`.get()` 기반), 500 대신 일반화된 에러 메시지.
- 이미 종료 상태인 작업에 대한 resume/cancel → video-agent 자체 에러 envelope을 그대로 전달(MAIN에서 상태 로직 재구현 안 함).
- 프론트엔드 폼: `brief` 필수/최소 길이 클라이언트 검증. 실제 게이트는 서버(`brief_intake.py`)의 `clarifying_question` 응답 — 이는 에러가 아니라 인라인 안내로 표시.
- 제출 요청 자체 실패 → composer 내용 보존한 채 인라인 에러, 재시도 가능.
- 씬 업로드 실패 → 해당 씬 카드에만 스코프된 에러, 나머지 목록에는 영향 없음.

## 검증 기준

**백엔드 (신규 라우트, `respx`/httpx mock 기반):**
- POST/GET 모든 호출에 `A2A-Version: 1.0` 헤더 포함 (구 클라이언트의 폴링 헤더 누락 버그 회귀 방지).
- 매 전송마다 새 UUID `messageId` 생성 (구 클라이언트의 하드코딩 리터럴 버그 회귀 방지).
- A2A 8개 상태 전체를 상태별 개별 테스트로 검증.
- artifacts의 text/data 파트 모두 읽음을 검증 (구 클라이언트의 text-only 버그 회귀 방지).
- 연결 불가 → 502, 잘못된 응답 → 일반화된 에러(500 아님), 종료 작업에 대한 resume/cancel → video-agent 에러 envelope 그대로 전달.

**백엔드 통합 스모크 테스트:**
- video-agent의 기존 `fake_video_agent_server.py`(무비용 스텁)를 띄워 SUBMITTED → INPUT_REQUIRED → resume → COMPLETED 전 과정을 신규 MAIN 라우트를 통해 실제 HTTP로 구동, 목업으로는 못 잡는 배선 문제 검증.

**프론트엔드 (Vitest + RTL):**
- `FormComposer`: 구조화 필드 조합별로 조립된 문장이 `brief_intake.py`의 정규식 패턴과 실제로 매칭되는지 검증 — 조용히 깨질 경우 사용자에게 아무 에러도 없이 렌더가 실패하는 유일한 지점이므로 직접 커버.
- `ComposerTabs`: 탭 전환 시 각 탭의 draft 상태 보존.
- `StatusBadge`: 상태별 라벨/색상, 경과 시간 카운터 동작.
- Canvas: 상태별로 올바른 뷰 렌더링.
- 폴링 훅: mock fetch로 5초 간격, 종료 상태에서 중단, INPUT_REQUIRED에서 일시정지 후 업로드 후 재개, 연속 3회 실패 후에만 재연결 배너 표시(첫 실패에는 표시 안 함) 검증.
- 씬 업로드: 한 씬의 실패가 다른 씬 카드에 영향 주지 않음.

**공통:**
- 기존 백엔드 pytest 전체 통과 (회귀 없음).
- 기존 프론트엔드 테스트 스크립트 통과 (회귀 없음).
- 프론트엔드 TypeScript/Vite build 통과.
