"""Elice 모델 엔드포인트가 실제로 응답하는지 확인하는 최소 스모크 스크립트."""
import os

import requests

URL = os.getenv("ELICE_API_URL", "https://mlapi.run/e9a5f41b-fdda-44f2-9545-ed88c458da53")
MODEL = os.getenv("ELICE_MODEL", "claude-sonnet-5")


def main():
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "안녕? 너는 어떤 모델이야?"}]}
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {os.environ['ELICE_API_KEY']}",
    }
    response = requests.post(f"{URL}/v1/chat/completions", json=payload, headers=headers)
    print(response.text)


if __name__ == "__main__":
    main()
