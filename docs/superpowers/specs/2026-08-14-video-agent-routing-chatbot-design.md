# Video-agent 페이지 라우팅 챗봇 추가 및 브리프 안내 문구 개선 설계

## 목표

video-agent 페이지에 다른 Agent(Game Q&A, Workmate AI 등)로 라우팅해주는 보조 챗봇을 우측에 추가하고, 영상 브리프 작성창의 안내 문구를 개선해 사용자가 너무 모호한 프롬프트를 제출하지 않도록 한다.

## 배경 / 결정 사항

- **재사용, 신규 컴포넌트 아님**: 이미 구현되어 있는 `MainBriefingChatbot`(`frontend/src/MainUiPanels.tsx:36-63`)을 그대로 재사용한다. 현재 `UpdatedReportNav`(`MainUiPanels.tsx:105`)가 `activeSection === "Today Briefing" && !activeChat`일 때만 렌더링하는데, `activeChat === "Video Generation"`일 때도 렌더링하도록 조건을 하나 추가한다.
- **기존에 제거했던 범용 챗팅 패널과는 다르다**: 사이드바 통합 작업(`2026-08-14-video-agent-sidebar-merge-design.md`)에서 video-agent에 대해 제거한 `<aside className="chat-panel">`(agent별 `/api/chats/{agent}/reply`)은 그대로 제거된 채 유지한다. 이번에 추가하는 것은 그것과 무관한, Main Agent의 범용 라우팅 챗봇이다.
- **위치 결정 근거**: `MainBriefingChatbot`의 `.briefing-chatbot` 스타일은 `position:fixed;right:32px;top:90px;z-index:6`으로 CSS Grid와 무관하게 뷰포트 기준으로 오버레이된다. 다만 `VideoAgentPage`를 감싸는 `.video-agent-host`가 현재 `grid-column:2 / 4`(원래 workspace+chat-panel이 차지하던 전체 폭)를 차지하고 있어, 고정 위치 챗봇과 시각적으로 겹친다. 다른 단일 Agent 화면(`Workmate AI`, `Game Q&A`)이 `.workspace{grid-column:2}`만 차지하고 3번째 컬럼을 비워두는 것과 동일하게, `.video-agent-host`도 `grid-column:2`로 좁힌다.
- **스타일은 그대로 유지**: `MainBriefingChatbot`은 다른 화면(오늘 브리핑)에서도 쓰이는 공유 컴포넌트이므로 색상(파란색 계열)은 건드리지 않는다. video-agent 페이지의 세이지그린 톤과는 의도적으로 다르게 유지 — "이건 Main Agent의 도구지 video-agent 자체 UI가 아니다"라는 시각적 구분으로 남긴다.
- **문맥별 안내 문구**: 오늘 브리핑 화면에서 쓸 때와 video-agent 화면에서 쓸 때 사용자가 헷갈리지 않도록, `MainBriefingChatbot`에 선택적 `contextHint` prop을 추가한다. prop이 없으면(오늘 브리핑) 기존 문구 그대로, video-agent에서는 "이 챗봇은 영상 생성 프롬프트를 받는 곳이 아니다"를 명확히 알리는 문구로 교체한다.
- **실제 서버 제약값 확인 완료**: video-agent(`video_draft_pipeline`) 실제 코드 확인 결과 — 길이는 `duration_sec: int = Field(gt=0, le=30)`로 30초 초과 시 검증 오류, 예산은 하드 에러가 아니라 `SERVER_MAX_BUDGET_USD`(기본값 $5.00)로 조용히 클램프된다. UI 문구는 이 실제 값($5, 30초)을 그대로 반영한다 — 서버 쪽 제약값 자체는 변경하지 않는다(비범위).

## 범위

- `frontend/src/MainUiPanels.tsx`: `MainBriefingChatbot`에 `contextHint?: string` prop 추가, `UpdatedReportNav`에 `activeChat === "Video Generation"` 조건 추가.
- `frontend/src/styles.css`: `.video-agent-host` 규칙을 `grid-column:2 / 4` → `grid-column:2`로 좁힘(`grid-row:1`은 유지).
- `frontend/src/video-agent/ChatComposer.tsx`: placeholder 문구를 요구사항+예시 형식으로 교체, 실제 제약값($5, 30초) 명시.

## 비범위

- video-agent 백엔드(`SERVER_MAX_BUDGET_USD` 등) 변경 — 실제 $5 제약을 그대로 반영만 한다.
- `MainBriefingChatbot`의 색상/스타일 변경.
- `FormComposer.tsx`의 필드 자체 변경(placeholder 문구 개선은 `ChatComposer`에 한정 — `FormComposer`는 이미 개별 필드로 구조화되어 있어 모호한 프롬프트 문제가 상대적으로 적음).
- 사이드바 통합 작업에서 제거한 범용 `<aside className="chat-panel">`을 되살리는 것.

## 설계

### `MainBriefingChatbot`에 `contextHint` prop 추가

```tsx
export function MainBriefingChatbot({ contextHint }: { contextHint?: string } = {}) {
  ...
  return <section className="briefing-chatbot">
    <h3>Main Chatbot <span>업무 라우터</span></h3>
    <div className="briefing-chat-messages">
      {messages.length === 0 && <p className="briefing-chat-empty">{contextHint ?? "간단한 질문이나 업무 내용을 입력하세요."}</p>}
      ...
    </div>
    <form className="briefing-chat-composer" onSubmit={submit}>
      <input value={message} onChange={...} placeholder={contextHint ? "다른 업무나 질문을 입력하세요" : "무엇을 도와드릴까요?"} />
      <button type="submit">➤</button>
    </form>
  </section>;
}
```

`contextHint`가 없으면(오늘 브리핑에서 호출될 때) 기존 문구와 동작이 완전히 동일하다.

### `UpdatedReportNav`에 두 번째 렌더 조건 추가

기존 `MainUiPanels.tsx:105`:
```tsx
{activeSection === "Today Briefing" && !activeChat && <MainBriefingChatbot />}
```
아래를 이어서 추가:
```tsx
{activeChat === "Video Generation" && <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />}
```

### `.video-agent-host` 그리드 컬럼 좁히기

`frontend/src/styles.css`의 기존 규칙:
```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2 / 4;grid-row:1}
```
다음으로 변경:
```css
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2;grid-row:1}
```

3번째 컬럼 공간을 비워, 고정 위치인 `.briefing-chatbot`이 `VideoAgentPage`의 캔버스 콘텐츠와 겹치지 않게 한다.

### `ChatComposer.tsx` placeholder 개선

```tsx
placeholder="무엇을 홍보할지 구체적으로 적어주세요 (캐릭터/이벤트/게임 장면 등, 30초 이하, 예산 $5 이하). 예: 할로윈 신규 캐릭터 '루멘' 공개 이벤트, 15초로"
```

기존의 예시 전용 문구(`"예: 할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"`)를 "요구사항 명시 + 예시" 형식으로 교체 — 실제 서버 제약(30초, $5)을 문구에 그대로 노출한다.

## 검증 기준

- 오늘 브리핑 화면에서 `MainBriefingChatbot`을 여는 기존 동작(문구, 라우팅)은 변경 없이 그대로 통과해야 한다.
- `activeChat === "Video Generation"`일 때 `MainBriefingChatbot`이 `contextHint`가 적용된 상태로 렌더링됨을 검증하는 신규 테스트.
- 기존 `video-agent/*.test.tsx`, `App.test.tsx` 전부 변경 없이 그대로 통과 — `VideoAgentPage` 자체의 로직/props는 건드리지 않는다.
- 프론트엔드 빌드(`npm run build`) 통과.
