#!/usr/bin/env bash
# scripts/video_agent_smoke_test.sh
#
# Manual/local cross-repo smoke test. Drives the full video-agent task
# lifecycle through MAIN's new /api/video-agent/* routes, against
# video-agent's zero-cost fake server (no billing).
#
# Usage: scripts/video_agent_smoke_test.sh [path-to-video_draft_pipeline-checkout]
set -euo pipefail

VIDEO_DRAFT_PIPELINE_DIR="${1:-../proj}"
VIDEO_SERVICE_TOKEN="smoke-test-token"
MAIN_PORT=8000
VIDEO_AGENT_PORT=8002

if [ ! -f "$VIDEO_DRAFT_PIPELINE_DIR/scripts/fake_video_agent_server.py" ]; then
  echo "fake_video_agent_server.py not found under $VIDEO_DRAFT_PIPELINE_DIR — pass the checkout path as \$1" >&2
  exit 1
fi

echo "Starting video-agent fake server on :$VIDEO_AGENT_PORT..."
(
  cd "$VIDEO_DRAFT_PIPELINE_DIR"
  VIDEO_SERVICE_TOKEN="$VIDEO_SERVICE_TOKEN" python scripts/fake_video_agent_server.py --port "$VIDEO_AGENT_PORT" &
  echo $! > /tmp/video_agent_smoke_fake_server.pid
)
sleep 2

echo "Starting MAIN backend on :$MAIN_PORT..."
(
  cd backend
  VIDEO_AGENT_URL="http://127.0.0.1:$VIDEO_AGENT_PORT" VIDEO_SERVICE_TOKEN="$VIDEO_SERVICE_TOKEN" \
    python -m uvicorn app.main:app --port "$MAIN_PORT" &
  echo $! > /tmp/video_agent_smoke_main_server.pid
)
sleep 2

cleanup() {
  echo "Stopping servers..."
  kill "$(cat /tmp/video_agent_smoke_fake_server.pid)" 2>/dev/null || true
  kill "$(cat /tmp/video_agent_smoke_main_server.pid)" 2>/dev/null || true
}
trap cleanup EXIT

echo "1. Creating a task via MAIN..."
# Written to a file and sent via --data-binary rather than passed inline to -d:
# some shells/terminals mangle multi-byte UTF-8 (e.g. Korean) when it travels
# through argv, which corrupts the JSON body before curl ever sees it.
printf '%s' '{"message": "할로윈 이벤트 영상 15초로 만들어줘"}' > /tmp/video_agent_smoke_create_body.json
CREATE_RESPONSE=$(curl -sf -X POST "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/video_agent_smoke_create_body.json)
echo "$CREATE_RESPONSE"
TASK_ID=$(echo "$CREATE_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['id'])")
echo "Task ID: $TASK_ID"

echo "2. Polling until INPUT_REQUIRED (fake server always needs a manual fix)..."
for _ in $(seq 1 10); do
  POLL_RESPONSE=$(curl -sf "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks/$TASK_ID")
  STATE=$(echo "$POLL_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['status']['state'])")
  echo "  state=$STATE"
  [ "$STATE" = "TASK_STATE_INPUT_REQUIRED" ] && break
  sleep 2
done
[ "$STATE" = "TASK_STATE_INPUT_REQUIRED" ] || { echo "FAIL: never reached INPUT_REQUIRED" >&2; exit 1; }

SCENE_ID=$(echo "$POLL_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['status']['unresolvedScenes'][0]['sceneId'])")
echo "3. Resuming scene $SCENE_ID with a fixed image..."
# The server validates the upload is a genuine readable image (PIL-based
# check), so this must be a real PNG, not placeholder bytes.
ffmpeg -y -f lavfi -i "color=c=orange:s=64x64" -frames:v 1 -update 1 /tmp/video_agent_smoke_fixed.png >/dev/null 2>&1
curl -sf -X POST "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks/$TASK_ID/scenes/$SCENE_ID/resume" \
  -F "file=@/tmp/video_agent_smoke_fixed.png"

echo "4. Polling until COMPLETED..."
for _ in $(seq 1 10); do
  POLL_RESPONSE=$(curl -sf "http://127.0.0.1:$MAIN_PORT/api/video-agent/tasks/$TASK_ID")
  STATE=$(echo "$POLL_RESPONSE" | python -c "import json,sys; print(json.load(sys.stdin)['task']['status']['state'])")
  echo "  state=$STATE"
  [ "$STATE" = "TASK_STATE_COMPLETED" ] && break
  sleep 2
done
[ "$STATE" = "TASK_STATE_COMPLETED" ] || { echo "FAIL: never reached COMPLETED" >&2; exit 1; }

echo "PASS: full SUBMITTED -> INPUT_REQUIRED -> resume -> COMPLETED lifecycle verified through MAIN's proxy routes."
