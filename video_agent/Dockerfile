FROM python:3.11-slim

# ffmpeg is required by the pipeline's video assembly step (see
# src/video_draft_pipeline/assembly.py) once a real render backend is wired
# up (VeoBackend/LTXBackend) rather than the stub backend.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8002

CMD ["uvicorn", "video_draft_pipeline.a2a_server.app:app", "--host", "0.0.0.0", "--port", "8002"]
