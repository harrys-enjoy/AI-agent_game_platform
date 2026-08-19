# Video-agent 페이지 사이드바 통합 및 리스킨 설계

## 목표

기존에 별도 Vite 엔트리(`video-agent.html`)로 격리되어 있던 video-agent 페이지를 MAIN 프론트엔드의 단일 React 앱(`App.tsx`)에 통합하고, 이미 존재하는 사이드바 "Video Generation" 항목에서 바로 접근할 수 있게 한다. 동시에 페이지 디자인을 "오늘 브리핑" 화면의 색상·스타일에 맞춰 재스킨한다.

## 배경 / 결정 사항

- **사이드바 통합**: `App.tsx`의 `chats` 배열(`App.tsx:28`)에 "Video Generation"이 이미 존재하며, 클릭 시 기존 범용 채팅 패널(`/api/chats/video-agent/reply`)이 렌더링된다. 새 항목을 추가하는 것이 아니라, `activeChat === "Video Generation"`일 때 렌더링되는 내용을 `VideoAgentPage`로 교체한다 — `activeSection === "Today Briefing" && !activeChat`가 `ReferenceBriefingPanel`을 단락 렌더링하는 기존 패턴과 동일한 방식.
- **단일 엔트리로 통합 (명시적 결정)**: `video-agent.html`/`video-agent-main.tsx`와 `vite.config.ts`의 `videoAgent` 빌드 엔트리를 제거한다. 사이드바로 접근 가능해진 이상 별도 URL을 유지할 이유가 없다는 사용자의 명시적 선택.
- **Tailwind 격리 재검토**: 별도 엔트리로 Tailwind를 격리했던 이유(Preflight가 기존 순수 CSS 앱에 영향을 주지 않도록)가 단일 번들 병합으로 다시 문제가 된다. `corePlugins: { preflight: false }`로 Tailwind의 전역 리셋을 비활성화해 해결한다 — 유틸리티 클래스 자체는 Preflight에 의존하지 않으므로 기능에는 영향이 없다.
- **리스킨 방식 (명시적 결정, 3안 중 선택)**: Tailwind를 걷어내고 순수 CSS로 다시 쓰거나(B), 공유 CSS 변수를 새로 도입하는 대신(C), 기존 Tailwind 설정에 "오늘 브리핑"의 색상 토큰을 추가하고 컴포넌트 클래스명만 교체하는 방식(A)을 선택 — 이미 검증된 Tailwind 아키텍처를 유지하면서 룩만 바꾼다.
- **색상 팔레트 출처**: `styles.css`의 `.report-dashboard`/`.priority-card`/`.briefing-list`/`.signal-strip` 규칙(대략 12-43번째 줄)에서 추출.
  - 배경 `#f7f9f6`, 강조(기본) `#397454`, 강조(진함/featured) `#2f624b`, 테두리 `#dfe7e1`, 본문 텍스트 `#19352c`/`#18352b`, 보조 텍스트 `#75867f`/`#81948b`
  - 카드: 흰 배경, `#dfe7e1` 테두리, **15px** 라운드 (`.priority-card`, `.briefing-list`)
  - 섹션 제목: 작은 대문자 초록 라벨 + 큰 제목 (`.briefing-section-title`)
  - 주요 액션 버튼: 진한 초록 배경, 흰 텍스트, 8px 라운드 (`.refresh-report`)
  - 상태 표시: 점(dot) + 라벨 형태의 필(pill) (`.signal-strip`의 `● Task 최신` 패턴)
- **로직/동작 변경 없음**: 이번 작업은 라우팅 통합 + 시각적 리스킨에 한정한다. 컴포저 제출, 폴링, 에러 배너, 수동 수정 업로드 등 기존 로직·props·상태 관리는 전혀 건드리지 않는다.
- **부작용 정리**: 기존 채팅 클릭 핸들러(`handleChatClick`)는 "Video Generation" 클릭 시에도 `activateChatTask()`와 `/api/chats/Video Generation/session` fetch를 계속 실행한다. `VideoAgentPage`는 이 세션을 사용하지 않으므로, "Video Generation"에 한해 이 부수 효과를 건너뛰도록 분기한다.

## 범위

- `App.tsx`: `activeChat === "Video Generation"`일 때 `VideoAgentPage`를 렌더링하는 분기 추가, 해당 케이스에서 세션 fetch/`activateChatTask` 스킵.
- `video-agent-main.tsx`, `video-agent.html` 삭제. `vite.config.ts`에서 `videoAgent` 빌드 엔트리 제거.
- `VideoAgentPage.tsx`에서 `./video-agent/styles.css`를 직접 import (단일 번들에 포함되도록).
- `tailwind.config.js`: `content`에서 `video-agent.html` 제거, `corePlugins.preflight = false` 추가, "오늘 브리핑" 색상 토큰을 `theme.extend.colors`에 추가.
- `video-agent/` 하위 컴포넌트(`VideoAgentPage`, `ComposerTabs`, `ChatComposer`, `FormComposer`, `StatusBadge`, `TaskCanvas`)의 Tailwind 클래스명을 새 토큰/패턴으로 교체 (props·로직 변경 없음).
- 신규 테스트: 사이드바에서 "Video Generation" 클릭 시 `VideoAgentPage`가 렌더링되고 기존 범용 채팅 패널은 렌더링되지 않음을 확인.

## 비범위

- 컴포저·폴링·에러 처리·업로드 등 기존 video-agent 페이지의 동작 로직 변경.
- 백엔드 변경 (`/api/video-agent/tasks*`, `/api/chats/video-agent/reply` 등 전부 그대로 유지).
- "Video Generation" 이외의 다른 사이드바 항목/에이전트 페이지에 대한 리스킨 확대.
- LLM 기반 자동 라우팅 (별도 향후 작업).

## 설계

### 통합

`App.tsx`의 `<main className="workspace">` 렌더링 블록에 `activeSection === "Today Briefing" && !activeChat && <ReferenceBriefingPanel .../>`와 동일한 위치·패턴으로 다음을 추가한다:

```
{activeChat === "Video Generation" && <VideoAgentPage />}
```

기존 태스크 테이블 + `PreviewPanel` 렌더링은 이 조건이 참일 때 표시되지 않도록 분기한다. `handleChatClick`에서 `chatName === "Video Generation"`인 경우 세션 fetch(`/api/chats/${chatName}/session`)와 `activateChatTask(chatName)` 호출을 건너뛴다.

### 빌드/엔트리 정리

`video-agent.html`, `src/video-agent-main.tsx` 삭제. `vite.config.ts`의 `build.rollupOptions.input`을 `{ main: "index.html" }` 단일 항목으로 되돌린다 (`test` 블록은 그대로 유지 — Vitest 설정은 빌드 엔트리와 무관).

`VideoAgentPage.tsx` 최상단에 `import "./styles.css";`를 추가해 Tailwind 스타일시트가 (엔트리와 무관하게) 이 컴포넌트를 import하는 `App.tsx` → `main.tsx`를 통해 번들에 포함되도록 한다.

### Tailwind 설정

```js
// tailwind.config.js
export default {
  content: ["./src/video-agent/**/*.{ts,tsx}"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        "brief-bg": "#f7f9f6",
        "brief-accent": "#397454",
        "brief-accent-dark": "#2f624b",
        "brief-border": "#dfe7e1",
        "brief-text": "#19352c",
        "brief-muted": "#75867f",
      },
    },
  },
  plugins: [],
};
```

### 컴포넌트 리스킨

로직·props·인터페이스는 전부 동일하게 유지하고, 클래스명만 교체한다:

- **페이지 배경**: `bg-slate-50` → `bg-brief-bg`.
- **카드류** (컴포저 패널, 캔버스, 씬 카드): `border-slate-300`/`rounded-lg` → `border-brief-border rounded-[15px]`, 배경은 흰색 유지.
- **섹션 제목** (예: "영상 생성" 헤더): 작은 대문자 `brief-accent` 라벨 + 본문 `brief-text` 제목 조합으로 재구성 — `.briefing-section-title` 패턴 참고.
- **`StatusBadge`**: 현재의 단순 회색 배지를 점(dot) + 라벨 필 형태로 교체 — 상태별 점 색상(작업 중=`brief-accent`, 실패=기존 red-600 유지, 완료=`brief-accent-dark` 등).
- **주요 액션 버튼** (생성 요청, 활성 탭): `bg-slate-900` → `bg-brief-accent`, hover는 `brief-accent-dark`, 흰 텍스트, `rounded-lg` → `rounded-[8px]`.
- **보조 텍스트** (플레이스홀더, 안내 문구): `text-slate-400`/`text-slate-600` → `text-brief-muted`.

### 테스트

`frontend/src/App.test.tsx` 신규 생성 (기존에 App.tsx에 대한 테스트가 없으므로 신규 파일). "Video Generation" 사이드바 버튼 클릭 시 `VideoAgentPage`의 식별 가능한 콘텐츠(예: 컴포저 탭)가 렌더링되고, 기존 범용 채팅 패널(`briefing-chatbot` 등 관련 셀렉터)이 렌더링되지 않음을 확인한다.

기존 `video-agent/*.test.tsx` 전부는 컴포넌트 동작이 변경되지 않았으므로 그대로 통과해야 한다 — 클래스명 변경은 `data-testid` 기반 쿼리에 영향을 주지 않는다.

`npm run build` 실행 시 `dist/index.html`만 생성되고 `dist/video-agent.html`은 더 이상 생성되지 않음을 확인한다.
