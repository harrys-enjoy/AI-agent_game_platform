# 담당자 선택 확장 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 기존 단일 담당자 선택바에서 현재 담당자를 변경할 수 있고, 이후 담당자 목록을 쉽게 추가·수정할 수 있도록 담당자 데이터를 명확히 분리한다.

**Architecture:** 담당자 이름·역할·AI Chat 연결값은 `assignee.ts`의 단일 목록에서 관리한다. `AssigneeSwitcher`는 이 목록만 읽어 선택 UI를 렌더링하며, App은 선택된 이름을 localStorage에 저장한다.

**Tech Stack:** React, TypeScript, Vite, Node test script

## Global Constraints

- 역할별 선택바 4개를 추가하지 않는다.
- 현재 UI의 단일 담당자 선택바를 유지한다.
- 담당자 목록 변경은 `assignee.ts`의 목록 수정으로 가능해야 한다.

### Task 1: 담당자 목록과 선택 UI 정리

**Files:**
- Modify: `frontend/src/assignee.ts`
- Modify: `frontend/src/AssigneeSwitcher.tsx`
- Modify: `frontend/scripts/assignee-test.mjs`

- [ ] 담당자 타입과 이름 조회 함수를 명확히 한다.
- [ ] 선택 UI가 이름 목록을 표시하고 선택된 담당자의 역할을 보여주는지 검증한다.
- [ ] 잘못 저장된 이름은 첫 번째 담당자로 안전하게 대체한다.

### Task 2: App 연결 및 검증

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] 선택된 담당자를 localStorage에 저장한다.
- [ ] 보고서 확인 완료 시 선택 담당자의 연결된 AI Chat으로 이동한다.
- [ ] 담당자 테스트와 Vite 빌드를 실행한다.
