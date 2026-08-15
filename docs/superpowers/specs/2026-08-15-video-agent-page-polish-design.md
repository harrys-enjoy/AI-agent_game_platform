# Video-agent 페이지 시각적 정합성 개선 설계

## 목표

video-agent 페이지(`영상 생성`)를 다른 세 Agent(Workmate AI, Game Q&A, Development Assistant)와 동일한 페이지 구조 관례를 따르도록 다듬는다. 새 컴포넌트를 만들지 않고, 이미 다른 Agent들이 쓰고 있는 공유 클래스와 CSS 패턴을 그대로 재사용한다.

## 배경 / 결정 사항

- **재사용 우선**: `.eyebrow`, `.title-row`, `.chat-panel`, `.reset-chat` 등은 이미 `frontend/src/styles.css` / `chat-answer.css`에 정의되어 있고, Preflight가 `.video-agent-host` 범위에서 꺼져 있어(사이드바 통합 작업에서 이미 처리) 그대로 상속받는다. 새 클래스를 새로 정의하지 않고 기존 클래스명을 그대로 재사용한다 — Game Q&A가 `.title-row h1`을 CSS `::after`로 오버라이드하는 것과 같은 원리.
- **오버사이즈 원인 확인 완료**: `VideoAgentPage`의 루트 div가 `h-full`이고, `.video-agent-host`가 `.shell`(`min-height:100vh`, grid)의 유일한 row-1 아이템이라 grid 기본 `align-items:stretch`로 인해 두 패널이 뷰포트 전체 높이까지 늘어난다. 다른 Agent의 패널들(`.workmate-detail{min-height:520px}`, `.chat-panel{height:calc(100vh - 120px)}`)은 이렇게 늘어나지 않는다 — `h-full` 제거와 자연스러운 `min-height`로 교체한다.
- **라우팅 챗봇은 실제 `.chat-panel`과 다른 스타일**: `.briefing-chatbot`은 `position:fixed;width:320px;height:calc(100vh - 122px)`로 다른 Agent의 진짜 `.chat-panel`(`height:calc(100vh - 120px)`, grid-column 배치, `overflow:hidden` + 내부 스크롤)과 다르다. 오늘 브리핑 화면에서 이미 grid 배치로 오버라이드하는 패턴(`styles.css:42`)이 있으므로, Video Generation 전용으로 동일한 패턴을 하나 더 추가한다.
- **Reset 버튼은 로컬 상태만 초기화**: `MainBriefingChatbot`은 백엔드 세션이 없는 순수 로컬 컴포넌트이므로(`/api/chats/{agent}/reset`과 무관), Reset 버튼은 `setMessages([])`만 수행한다.
- **영어/한국어 구분 원칙**: 범용 UI 문구(placeholder, 라벨)는 다른 Agent와 맞춰 영어로, 이 페이지에서만 의미 있는 안내문(라우팅 챗봇의 contextHint, 브리프 작성 placeholder의 $5/30초 제약 안내)은 한국어를 유지한다.

## 범위

- `frontend/src/video-agent/VideoAgentPage.tsx`: 상단에 `.title-row`/`.eyebrow`/`<h1>` 블록 추가, 루트 grid에서 `h-full` 제거하고 자연스러운 `min-height`로 교체.
- `frontend/src/styles.css`:
  - `.video-agent-host`에 `.workspace`와 동일한 페이지 패딩(`45px 32px`) 추가.
  - Video Generation 전용 `.briefing-chatbot` 그리드 배치/크기 오버라이드 추가(오늘 브리핑과 동일 패턴 재사용).
- `frontend/src/MainUiPanels.tsx`: `MainBriefingChatbot`에서 `contextHint`가 있을 때(= Video Generation 전용) 헤더를 `AI Chat · Video Generation` + `Reset chat` 버튼으로 교체, placeholder를 `Type a message...`로 교체. `contextHint` 없을 때(오늘 브리핑)는 기존 그대로.

## 비범위

- `ChatComposer.tsx`/`FormComposer.tsx`의 브리프 작성 필드, placeholder($5/30초 안내 포함) — 어제 확정한 내용, 건드리지 않는다.
- `TaskCanvas.tsx`의 상태별 렌더링 로직 — 구조는 그대로, 패널이 담기는 컨테이너 크기만 바뀐다. working/input-required/completed/error 각 상태 모두 동일한 컨테이너 크기 조정의 영향을 받으므로 상태별로 별도 처리하지 않는다.
- 오늘 브리핑에서 쓰이는 기본 `MainBriefingChatbot`(문구, 크기, 헤더) — 전혀 변경하지 않는다.
- video-agent 백엔드/A2A 로직 — 변경 없음.

## 설계

### 1. 페이지 타이틀 (eyebrow + bold h1)

`VideoAgentPage.tsx` 최상단에 다른 Agent와 동일한 마크업 재사용:

```tsx
<div className="title-row">
  <div>
    <p className="eyebrow">MAIN AGENT / VIDEO GENERATION</p>
    <h1>영상 생성</h1>
  </div>
</div>
```

`.title-row`/`.eyebrow`는 전역 `styles.css`에 이미 정의되어 있으므로 별도 CSS 불필요. 기존에 aside 안에 있던 `<h1 className="text-lg font-semibold ...">영상 생성</h1>`는 페이지 레벨 타이틀과 중복되므로 제거한다.

### 2. 패널 크기 정상화

루트 div를 `h-full` 대신 자연스러운 높이로:

```tsx
// before: <div className="grid h-full grid-cols-[minmax(280px,360px)_1fr] gap-4 bg-brief-bg p-4">
// after:
<div className="grid grid-cols-[minmax(280px,360px)_1fr] gap-4 bg-brief-bg">
```

`p-4`는 제거하고 페이지 패딩을 `.video-agent-host`(styles.css)로 옮긴다. 기존 규칙(`styles.css:45`)에 `padding`만 추가하는 것이며 `grid-column`/`grid-row`는 그대로 유지한다:

```css
/* styles.css:45, 기존 규칙에 padding 추가 */
.agent-content-updated[data-active-chat="Video Generation"] .video-agent-host{grid-column:2;grid-row:1;padding:45px 32px}
```

좌측 aside/우측 main 패널에 `min-h-[520px]`를 추가해 다른 Agent의 상세 패널(`.workmate-detail{min-height:520px}`)과 동일한 최소 크기를 갖도록 한다. `TaskCanvas`의 각 상태(`h-full` 사용)는 부모가 더 이상 뷰포트 전체 높이가 아니므로 자동으로 정상 크기가 된다.

### 3. 라우팅 챗봇 크기/타이틀/Reset

`styles.css`에 Video Generation 전용 오버라이드 추가(오늘 브리핑의 `styles.css:42` 패턴과 동일):

```css
.agent-content-updated[data-active-chat="Video Generation"] .briefing-chatbot{position:static;grid-column:3;grid-row:1;width:auto;height:calc(100vh - 120px);margin:90px 32px 32px 0}
```

`MainUiPanels.tsx`의 `MainBriefingChatbot`:

```tsx
export function MainBriefingChatbot({ contextHint }: { contextHint?: string } = {}) {
  const [messages, setMessages] = useState<...>([]);
  ...
  return (
    <section className="briefing-chatbot">
      {contextHint ? (
        <h3>AI Chat · Video Generation<button className="reset-chat" type="button" onClick={() => setMessages([])}>Reset chat</button></h3>
      ) : (
        <h3>Main Chatbot <span>업무 라우터</span></h3>
      )}
      <div className="briefing-chat-messages">
        {messages.length === 0 && <p className="briefing-chat-empty">{contextHint ?? "간단한 질문이나 업무 내용을 입력하세요."}</p>}
        ...
      </div>
      <form className="briefing-chat-composer" onSubmit={submit}>
        <input ... placeholder={contextHint ? "Type a message..." : "무엇을 도와드릴까요?"} />
        <button type="submit">➤</button>
      </form>
    </section>
  );
}
```

`contextHint` 자체(라우팅 대상이 아닌 안내문)는 그대로 한국어 유지 — placeholder만 영어로 바뀐다.

## 검증 기준

- 오늘 브리핑 화면의 `MainBriefingChatbot`(문구, 헤더, 크기, Reset 버튼 없음)은 기존과 완전히 동일하게 유지되어야 한다 — 회귀 테스트로 검증.
- Video Generation 페이지에서: 상단에 `MAIN AGENT / VIDEO GENERATION` eyebrow + `영상 생성` bold h1이 보인다.
- Video Generation 페이지에서: 좌측 브리프 작성 박스와 우측 캔버스 박스가 더 이상 뷰포트 전체 높이로 늘어나지 않는다(`min-h-[520px]` 근처의 자연스러운 크기).
- Video Generation 페이지에서: 우측 라우팅 챗봇이 `AI Chat · Video Generation` 헤더와 `Reset chat` 버튼을 가지며, 실제 `.chat-panel`과 비슷한 크기/위치(그리드 3번째 컬럼, `calc(100vh - 120px)`)로 배치된다.
- 라우팅 챗봇의 입력창 placeholder가 Video Generation에서는 `Type a message...`(영어), 안내 문구(contextHint)는 한국어 그대로.
- `Reset chat` 클릭 시 라우팅 챗봇의 로컬 메시지 목록만 비워지고, 백엔드 호출은 없다.
- 기존 `video-agent/*.test.tsx`, `App.test.tsx`, `MainUiPanels.test.tsx`의 기존 테스트는 타이틀/헤더 마크업 변경에 맞춰 셀렉터가 깨지지 않는 선에서 통과해야 한다(깨지는 경우 해당 테스트를 새 마크업에 맞게 갱신).
- 프론트엔드 빌드(`npm run build`) 통과.
