FROM python:3.13-slim

WORKDIR /app

# deploy_trigger가 대상 레포를 git clone하고, 호스트 Docker(소켓 마운트, main_agent 쪽 compose
# 파일 참고)에 docker CLI로 build/run을 직접 지시한다 — 둘 다 python:3.13-slim엔 없어서 설치해야 함.
# docker.io는 dockerd(데몬)까지 같이 깔려서 이미지만 커진다 — docker-cli만 있으면 된다.
#
# 대상 레포에 compose 파일이 있으면 `docker compose ...`(V2 서브커맨드)로 띄우는데, Debian
# 기본 저장소엔 `docker-compose-plugin`이 없고 standalone `docker-compose` 바이너리만 있다 —
# 실제로는 같은 V2 엔진이라, CLI 플러그인 검색 경로에 `docker-compose`라는 이름으로 심볼릭
# 링크해두면 `docker compose`로도 그대로 인식한다(공식 문서화된 방법, apt 저장소 추가 불필요).
RUN apt-get update && apt-get install -y --no-install-recommends git docker-cli docker-compose \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && ln -s "$(command -v docker-compose)" /usr/local/lib/docker/cli-plugins/docker-compose \
    && find /var/lib/apt/lists -mindepth 1 -delete

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8003

CMD ["uvicorn", "a2a_server:app", "--host", "0.0.0.0", "--port", "8003"]
