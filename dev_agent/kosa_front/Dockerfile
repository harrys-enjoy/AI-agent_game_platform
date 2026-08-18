FROM python:3.13-slim

WORKDIR /app

# 배포 현황 탭이 호스트 Docker를 docker CLI로 조회한다(docker-compose.yml에서 소켓을 마운트해줘야 함).
# docker-cli만 필요 — docker.io는 dockerd(데몬)까지 같이 깔려서 이미지만 커진다.
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli && find /var/lib/apt/lists -mindepth 1 -delete

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
