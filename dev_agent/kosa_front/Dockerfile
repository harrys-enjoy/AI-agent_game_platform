FROM python:3.13-slim

WORKDIR /app

# 배포 현황 탭이 호스트 Docker를 docker CLI로 조회하고, 삭제 버튼은 compose 배포를
# `docker compose -p <project> down`으로 지운다(호스트 소켓 마운트는 main_agent 쪽
# compose 파일에서). docker.io는 dockerd(데몬)까지 같이 깔려서 이미지만 커진다 —
# docker-cli만 있으면 된다.
#
# Debian 기본 저장소엔 `docker-compose-plugin`이 없고 standalone `docker-compose`
# 바이너리만 있다 — 실제로는 같은 V2 엔진이라, CLI 플러그인 검색 경로에 같은 이름으로
# 심볼릭 링크해두면 `docker compose`로도 그대로 인식한다(dev_agent/Dockerfile과 동일한
# 조치 — apt 저장소 추가 불필요).
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli docker-compose \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && ln -s "$(command -v docker-compose)" /usr/local/lib/docker/cli-plugins/docker-compose \
    && find /var/lib/apt/lists -mindepth 1 -delete

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
