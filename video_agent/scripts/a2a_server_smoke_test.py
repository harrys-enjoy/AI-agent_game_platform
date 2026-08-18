"""Manual smoke test: drive the real A2A server exactly the way the
teammate's A2AClient does, over real HTTP.

Not a pytest test — it makes real, billed Gemini/Veo API calls against a
server you must already have running, so it is not part of `pytest -v` and
should be run by hand:

    # terminal 1 (standalone run — set SELF_INTERNAL_URL to localhost for agent card discovery)
    VIDEO_SERVICE_TOKEN=dev-secret SELF_INTERNAL_URL=http://localhost:8002 uvicorn video_draft_pipeline.a2a_server.app:app --host 0.0.0.0 --port 8002

    # terminal 2
    VIDEO_SERVICE_TOKEN=dev-secret python scripts/a2a_server_smoke_test.py --message "할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"

For docker-compose deployment, the default SELF_INTERNAL_URL=http://video-agent:8002 is correct
and this override is not needed.

This does not import the teammate's A2AClient (it lives in a separate,
non-installable repo) — instead it replicates its exact request/response
handling in ~30 lines of httpx, matching AI-agent_game_platform's
backend/app/a2a_client.py:send_message/poll_task byte-for-byte in the
fields that matter (messageId, ROLE_USER, parts, content-type, task
derivation, terminal-state polling), so a pass here is real evidence the
wire contract matches his client, not just our own test fixtures.
"""

import argparse
import os
import sys
import time

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8002")
    parser.add_argument("--message", required=True)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--poll-timeout", type=float, default=600.0)
    parser.add_argument("--service-token", default=os.environ.get("VIDEO_SERVICE_TOKEN", ""))
    return parser.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    card_url = f"{args.base_url}/.well-known/agent-card.json"
    card = httpx.get(card_url, timeout=5.0).raise_for_status().json()
    print(f"agent card: {card['name']}")
    interfaces = [i for i in card["supportedInterfaces"] if i["protocolBinding"] == "HTTP+JSON"]
    if not interfaces:
        raise SystemExit("Agent card has no HTTP+JSON supportedInterfaces entry")
    base_url = interfaces[0]["url"]
    message_send_url = f"{base_url}/message:send"

    payload = {
        "message": {
            "messageId": "smoke-test",
            "role": "ROLE_USER",
            "parts": [{"text": args.message}],
        },
        "metadata": {"mode": "video_draft", "locale": "ko", "context": {}, "evidence": []},
    }
    headers = {
        "content-type": "application/json",
        "Authorization": f"Bearer {args.service_token}",
        "A2A-Version": "1.0",
    }
    print(f"POST {message_send_url}")
    response = httpx.post(message_send_url, json=payload, headers=headers, timeout=10.0)
    response.raise_for_status()
    body = response.json()

    if body.get("message"):
        print(f"\nsynchronous answer (no render triggered):\n{body['message']['parts'][0]['text']}")
        return 0

    task_id = body["task"]["id"]
    task_url = f"{base_url}/tasks/{task_id}"
    print(f"task created: {task_id}, polling {task_url}")

    deadline = time.monotonic() + args.poll_timeout
    while True:
        task_response = httpx.get(task_url, headers=headers, timeout=5.0)
        task_response.raise_for_status()
        task = task_response.json()["task"]
        state = task["status"]["state"]
        if state == "TASK_STATE_INPUT_REQUIRED":
            answer = task["status"].get("message", {}).get("parts", [{}])[0].get("text", "")
            unresolved_scenes = task["status"].get("unresolvedScenes", [])
            print(f"\n{state}:\n{answer}")
            print(f"unresolvedScenes: {unresolved_scenes}")
            return 2
        if state in {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}:
            answer = task["status"].get("message", {}).get("parts", [{}])[0].get("text", "")
            print(f"\n{state}:\n{answer}")
            return 0 if state == "TASK_STATE_COMPLETED" else 1
        if time.monotonic() >= deadline:
            raise SystemExit(f"Polling timed out after {args.poll_timeout}s, last state: {state}")
        print(f"  ...{state}, waiting {args.poll_interval}s")
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    sys.exit(main())
