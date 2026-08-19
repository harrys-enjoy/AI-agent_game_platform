# 게임 Q&A API Docker 배포 설계

## 목적

게임 Q&A API를 업무생산성 서비스와 분리된 컨테이너로 실행한다. 배포 환경은 실제 모델 키를 이미지나 저장소에 넣지 않고, 호스트 환경변수로 주입한다.

## 범위

- Node.js 20 기반 API 컨테이너를 정의한다.
- 로컬과 서버에서 같은 명령으로 실행할 수 있도록 Compose 구성을 제공한다.
- 이미지 빌드에서 `.env`, Git 메타데이터, 테스트 파일을 제외한다.
- 실행·중지·상태 확인 절차를 README에 문서화한다.

업무생산성 UI, MCP Host, 원격 에이전트 배포, 실제 Qwen 모델 키 발급은 이 작업 범위에 포함하지 않는다.

## 구성

### Dockerfile

- 공식 `node:20-alpine` 이미지를 사용한다.
- 앱 소스와 `package.json`만 복사한다.
- 런타임은 `npm start`로 `src/server.js`를 실행한다.
- 컨테이너는 포트 `3000`을 노출한다.
- 의존성 설치 단계는 현재 외부 런타임 의존성이 없으므로 두지 않는다.

### .dockerignore

`.env`, `.git`, `.worktrees`, `node_modules`, 테스트와 로컬 도구 설정을 빌드 컨텍스트에서 제외한다. 따라서 API 키와 모델 API 키는 Docker 이미지 레이어에 포함되지 않는다.

### compose.yaml

- 서비스 이름은 `game-qna-api`로 한다.
- 기본 포트 매핑은 `${PORT:-3000}:3000`으로 한다.
- `env_file: .env`로 서버 실행 환경에 키를 주입한다.
- 컨테이너 이름은 고정하지 않는다. 같은 호스트에서 여러 프로젝트를 실행할 때 충돌을 피하기 위함이다.
- 데이터는 저장소의 정적 JSON만 사용하므로 볼륨, 데이터베이스, 영속 스토리지는 추가하지 않는다.

## 환경변수와 보안

- `.env`는 계속 Git 추적에서 제외한다.
- `API_KEY`는 업무생산성 서비스가 이 API를 호출할 때의 Bearer 키다.
- `MODEL_API_KEY`는 NVIDIA Qwen 또는 이후 Elice 모델 호출용 키다.
- 키 값은 Dockerfile, Compose 파일, README 예시, 로그에 기록하지 않는다.
- 공개 경로(`/health`, `/metrics`, `/sources`, Agent Card)는 키 없이 상태와 출처 정보만 반환한다. 질문 처리 경로는 `API_KEY` 설정 시 인증을 요구한다.

## 사용 흐름

1. 운영자가 `.env.example`을 복사해 `.env`를 만들고 실제 값을 입력한다.
2. `docker compose up --build -d`로 컨테이너를 실행한다.
3. `GET /health`로 서비스 상태를 확인한다.
4. 필요 시 `GET /sources`로 CC0 콘텐츠 출처를 확인한다.
5. 업무생산성 서비스는 서버 환경변수에 보관한 `API_KEY`로 `/message:send` 또는 `/api/ask`를 호출한다.

## 오류 처리와 검증

- `.env`에 모델 설정이 일부만 있으면 기존 애플리케이션 설정 검증이 시작 단계에서 오류를 낸다.
- 모델 API가 실패하면 기존 API 계약에 따라 `MODEL_UNAVAILABLE`을 반환한다.
- Docker 파일 자체는 Node 테스트 대상이 아니므로 기존 `npm test`를 유지한다.
- 문서의 검증 절차에는 `docker compose ps`, `/health`, `/sources` 호출을 포함한다.

## 수용 기준

- `docker compose up --build`로 API가 포트 3000에서 실행된다.
- `.env`가 이미지 빌드 컨텍스트에 포함되지 않는다.
- `docker compose` 실행 환경에서 `GET /health`가 200을 반환한다.
- README만 보고 실행·상태 확인·중지 절차를 수행할 수 있다.
