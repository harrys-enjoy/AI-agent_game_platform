# 독자 세계관 데이터 설계

## 목적

게임 Q&A의 `lore` 모드를 확장하되, 외부 게임의 인물·고유명사·줄거리를 복제하지 않고 독자 세계관을 제공한다. CC0 오픈 게임 자료는 시각적 분위기와 자산 분류 참고로만 사용하며, 라이선스 출처는 별도로 보관한다.

## 범위

- 포함: 세계의 기원, 주요 세력, 핵심 사건의 초기 3개 세계관 항목
- 포함: 각 항목의 독자 작성 여부와 참고 출처 기록
- 제외: 외부 게임의 서사·대사·캐릭터·고유명사 복제
- 제외: 이미지·에셋 파일 다운로드 및 배포

## 데이터 모델

`data/knowledge.json`의 `lore` 항목에는 기존 `id`, `name`, `keywords`, `answer`, `sourceRef`에 아래 필드를 추가한다.

```json
{
  "originalContent": true,
  "inspirationSources": ["oga-starfields"]
}
```

- `originalContent`: 이 저장소에서 새로 작성한 서사임을 나타낸다.
- `inspirationSources`: 분위기·자산 분류 참고에만 사용한 CC0 출처 ID다.

`data/sources.json`의 기존 원본 URL과 CC0 라이선스 정보를 그대로 사용한다.

## 초기 세계관

1. **유리별의 기원**: 하늘에 떠 있는 유리별과 지상 항로의 탄생
2. **항로 감시단**: 유리별의 파편을 관리하는 중립 세력
3. **빛바랜 항로 사건**: 오래된 항로가 끊기며 발생한 탐사 갈등

위 명칭과 서사는 독자 설정이다. 특정 상용·오픈 게임의 설정, 인물, 지명, 사건을 참조하거나 재현하지 않는다.

## 응답과 출처

기존 `sources` 배열에는 `lore:<id>`와 CC0 원본 URL이 유지된다. 독자 서사임을 호출자가 알 수 있도록 `original:lore` 표식을 추가한다.

예:

```json
{
  "sources": [
    "lore:glass-star-origin",
    "original:lore",
    "https://opengameart.org/content/starfields"
  ]
}
```

## 검증

- 세 항목을 각각 키워드로 직접 조회하는 테스트를 추가한다.
- 각 응답에 `original:lore`와 CC0 원본 URL이 포함되는지 검증한다.
- 기존 CC0 카탈로그·도감 조회와 전체 테스트가 계속 통과해야 한다.
