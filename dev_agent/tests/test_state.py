from graph.state import merge_results


def test_merge_results_combines_new_keys():
    existing = {"review": "L1: 문제 없음"}
    update = {"ci": "빌드 성공"}

    merged = merge_results(existing, update)

    assert merged == {"review": "L1: 문제 없음", "ci": "빌드 성공"}


def test_merge_results_overwrites_same_key():
    existing = {"review": "이전 결과"}
    update = {"review": "새 결과"}

    merged = merge_results(existing, update)

    assert merged == {"review": "새 결과"}


def test_merge_results_does_not_mutate_existing():
    existing = {"review": "L1: 문제 없음"}
    update = {"ci": "빌드 성공"}

    merge_results(existing, update)

    assert existing == {"review": "L1: 문제 없음"}
