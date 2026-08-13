# Video-agent 씬 재개 업로드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MAIN에서 video-agent의 미해결 씬을 표시하고 수정 이미지를 업로드해 씬 재개 처리를 수행한다.

**Architecture:** 기존 `chat_reply()` 결과를 확장하고, `AgentRegistry` 설정을 재사용하는 FastAPI multipart 프록시를 추가한다. React 채팅은 `unresolved-scenes` 메시지와 순수 유틸 모듈로 업로드 상태를 관리한다.

**Tech Stack:** FastAPI, httpx, pytest, React, TypeScript, Vite, Node `node:test`

## Global Constraints

- 기존 스토리 검토/승인 및 Workmate 연동 코드는 유지한다.
- video-agent 프록시 요청 timeout은 300초로 설정한다.
- 실제 video-agent 유료 API 호출은 테스트하지 않고 mock transport/monkeypatch로 대체한다.
- 업로드 후 자동 polling은 추가하지 않는다.

### Task 1: 백엔드 응답·프록시 endpoint

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_api.py`

- [ ] `chat_reply()`가 `task.status.unresolvedScenes`가 있을 때만 `taskId`와 `unresolvedScenes`를 반환하는 테스트를 추가한다.
- [ ] multipart 업로드 성공, video-agent 구조화 오류 전달, 연결 실패 502 테스트를 추가한다.
- [ ] `UploadFile`/`File` route를 구현하고 `registry.config("video-agent")`, `registry.headers("video-agent")`를 사용한다.
- [ ] `python-multipart>=0.0.9`를 requirements와 pyproject에 추가한다.
- [ ] `python -m pytest backend/tests/test_api.py -q`와 `python -m pytest -q`를 실행한다.

### Task 2: 프론트엔드 resume 유틸

**Files:**
- Create: `frontend/src/resume-utils.ts`
- Create: `frontend/scripts/resume-utils-test.mjs`
- Modify: `frontend/package.json`

- [ ] 씬 목록 생성·상태 갱신·resume 결과 병합·FormData 생성·완료 메시지 유틸을 작성한다.
- [ ] 각 유틸의 정상 및 경계 동작을 `node:test`로 검증한다.
- [ ] `test:resume` npm script를 등록하고 `npm run test:resume`를 실행한다.

### Task 3: 채팅 카드 및 업로드 UI

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/task-form.css`

- [ ] `ChatMessage`에 `unresolved-scenes` 타입을 추가하고 API 응답의 씬 목록을 카드로 표시한다.
- [ ] 파일 선택 시 `/api/video-agent/tasks/{taskId}/scenes/{sceneId}/resume`로 FormData를 POST한다.
- [ ] 업로드 중·실패·남은 씬·최종 영상 URL 상태를 UI에 반영한다.
- [ ] 카드 썸네일과 이슈 목록 스타일을 추가한다.
- [ ] 기존 story review UI와 기존 채팅 동작이 유지되는지 확인한다.
- [ ] `npm run build`와 전체 프론트엔드 테스트를 실행한다.
