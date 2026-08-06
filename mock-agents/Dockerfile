FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY server.py .
COPY cards ./cards
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${AGENT_PORT}"]
