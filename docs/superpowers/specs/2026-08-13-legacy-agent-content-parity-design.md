# 변경전 Agent 본문 변경후 UI 일치 설계

## 목표

좌측 메뉴와 Works 하위 목록은 현재 Rev1 구조를 유지한다. UI 전환기에서 `변경전`을 선택하더라도 Works 하위의 네 Agent 본문은 `변경후`에서 사용 중인 Agent별 화면과 동일하게 표시한다.

## 범위

포함:

- Workmate AI 본문을 변경후 Workmate 업무 화면과 동일하게 표시
- Video Generation 본문을 변경후 Task 테이블과 Workspace Preview 구성으로 표시
- Development Assistant 본문을 변경후 Task 테이블과 Workspace Preview 구성으로 표시
- Game Q&A 본문을 변경후 Task 테이블과 Story Review Workspace 구성으로 표시
- 각 Agent의 기존 채팅, 입력, reset, Game Q&A 명령어 및 스토리 검토 동작 유지

제외:

- 좌측 사이드바, Works 하위 목록, Agent Work 목록의 구조와 스타일 변경
- 담당자 설정 및 보고서 화면 변경
- Agent 라우팅 규칙 변경

## 화면 규칙

Agent가 활성화된 경우 본문 레이아웃은 UI 전환값과 무관하게 변경후 스타일을 사용한다. 좌측 메뉴는 기존 UI 전환값에 따라 현재 Rev1 동작을 유지한다.

| Agent | 본문 구성 |
| --- | --- |
| Workmate AI | 4개 업무 카드/탭, Workmate 업무 화면, 우측 AI Chat |
| Video Generation | Task 테이블, Add task, Workspace Preview, 우측 AI Chat |
| Development Assistant | Task 테이블, Add task, Workspace Preview, 우측 AI Chat |
| Game Q&A | Task 테이블, Add task, Story Review Workspace, 우측 AI Chat |

## 구현 방식

현재 Agent 본문을 렌더링하는 분기에서 `activeChat`이 존재하는 경우 변경후 본문 컴포넌트와 스타일을 선택하도록 한다. 사이드바 렌더링 분기에는 변경을 가하지 않는다. 기존 `TaskQuickActions`, `PreviewPanel`, Game Q&A 스토리 폼 및 채팅 패널을 재사용해 중복 구현을 피한다.

## 동작 및 오류 처리

- Agent 선택 시 기존 `activeChat` 전환과 채팅 세션 로딩을 그대로 사용한다.
- 채팅 응답 오류는 기존 Agent 오류 메시지를 유지한다.
- Game Q&A 스토리 검토 오류 및 명령어 도움말 동작은 기존 동작을 유지한다.
- UI 전환 후 새로고침해도 좌측 메뉴의 선택 상태 저장 방식은 변경하지 않는다.

## 검증

- TypeScript/Vite 빌드 통과
- 변경전에서 네 Agent를 각각 열어 변경후 화면과 본문 구성이 같은지 확인
- 좌측 메뉴 항목과 Works 펼침/접힘 동작이 변경되지 않았는지 확인
- Agent 채팅 입력 및 Game Q&A 명령어/스토리 검토 동작 확인
