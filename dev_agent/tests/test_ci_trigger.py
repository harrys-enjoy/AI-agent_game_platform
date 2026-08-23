from dataclasses import dataclass, field

from graph.ci_trigger import _collect_failed_jobs, _find_mentioned_branch, _resolve_ref, ci_trigger_node
from graph.supervisor import _order_ci_before_summary


@dataclass
class FakeRepo:
    default_branch: str = "beta"


@dataclass
class FakeStep:
    name: str
    conclusion: str


@dataclass
class FakeJob:
    name: str
    conclusion: str | None
    steps: list = field(default_factory=list)


@dataclass
class FakeRun:
    job_list: list

    def jobs(self):
        return self.job_list


def test_resolve_ref_uses_pr_branch_when_pr_number_matches():
    state = {
        "pr_number": 42,
        "prs": [
            {"number": 7, "branch": "other"},
            {"number": 42, "branch": "demo/bug-1"},
        ],
    }

    assert _resolve_ref(state, FakeRepo()) == "demo/bug-1"


def test_resolve_ref_falls_back_to_default_branch_when_no_pr_number():
    assert _resolve_ref({"pr_number": None, "prs": []}, FakeRepo()) == "beta"


def test_resolve_ref_falls_back_when_pr_number_not_in_list():
    state = {"pr_number": 99, "prs": [{"number": 42, "branch": "demo/bug-1"}]}

    assert _resolve_ref(state, FakeRepo()) == "beta"


def test_find_mentioned_branch_matches_exact_name():
    assert _find_mentioned_branch("feat/x 배포해줘", ["main", "feat/x"]) == "feat/x"


def test_find_mentioned_branch_ignores_substring_inside_larger_word():
    # "main" must not match inside "main_agent" — a real directory name in this repo.
    assert _find_mentioned_branch("main_agent 폴더 상태 보여줘", ["main"]) is None


def test_find_mentioned_branch_prefers_longer_more_specific_match():
    assert _find_mentioned_branch("feat/x 배포해줘", ["feat", "feat/x"]) == "feat/x"


def test_find_mentioned_branch_returns_none_when_nothing_matches():
    assert _find_mentioned_branch("아무 브랜치도 언급 안 함", ["main", "feat/x"]) is None


def test_resolve_ref_uses_mentioned_branch_when_no_pr_number():
    state = {"pr_number": None, "prs": [], "request": "feat/x 배포해줘", "branches": ["beta", "feat/x"]}
    assert _resolve_ref(state, FakeRepo()) == "feat/x"


def test_resolve_ref_prefers_pr_branch_over_mentioned_branch():
    state = {
        "pr_number": 42,
        "prs": [{"number": 42, "branch": "demo/bug-1"}],
        "request": "feat/x 배포해줘",
        "branches": ["beta", "feat/x"],
    }
    assert _resolve_ref(state, FakeRepo()) == "demo/bug-1"


def test_resolve_ref_falls_back_to_default_when_no_branch_mentioned():
    state = {"pr_number": None, "prs": [], "request": "그냥 상태 보여줘", "branches": ["beta", "feat/x"]}
    assert _resolve_ref(state, FakeRepo()) == "beta"


def test_collect_failed_jobs_keeps_only_real_failures():
    run = FakeRun(
        job_list=[
            FakeJob(name="lint", conclusion="success"),
            FakeJob(name="running", conclusion=None),
            FakeJob(name="skipped-job", conclusion="skipped"),
            FakeJob(
                name="test-shard-1",
                conclusion="failure",
                steps=[
                    FakeStep(name="install", conclusion="success"),
                    FakeStep(name="vitest", conclusion="failure"),
                ],
            ),
        ]
    )

    logs = _collect_failed_jobs(run)

    assert logs == [
        {"name": "test-shard-1", "conclusion": "failure", "summary": "실패 스텝: vitest"}
    ]


def test_collect_failed_jobs_handles_failure_without_failed_steps():
    run = FakeRun(job_list=[FakeJob(name="build", conclusion="cancelled", steps=[])])

    logs = _collect_failed_jobs(run)

    assert logs == [{"name": "build", "conclusion": "cancelled", "summary": ""}]


def test_ci_trigger_node_reports_missing_token_without_calling_github(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def explode():
        raise AssertionError("GITHUB_TOKEN이 없으면 GitHub 클라이언트를 만들면 안 된다")

    monkeypatch.setattr("graph.ci_trigger.get_github_client", explode)

    result = ci_trigger_node({"repo": "owner/name"})

    assert result["ci_logs"] == []
    assert "GITHUB_TOKEN" in result["ci_status"]


def test_order_ci_before_summary_swaps_when_reversed():
    plan = ["fetch", "ci_agent", "ci_trigger"]

    assert _order_ci_before_summary(plan) == ["fetch", "ci_trigger", "ci_agent"]


def test_order_ci_before_summary_leaves_correct_order_untouched():
    plan = ["fetch", "ci_trigger", "ci_agent"]

    assert _order_ci_before_summary(plan) == plan


def test_order_ci_before_summary_ignores_plans_without_both_nodes():
    assert _order_ci_before_summary(["fetch", "ci_agent"]) == ["fetch", "ci_agent"]
    assert _order_ci_before_summary(["fetch", "ci_trigger"]) == ["fetch", "ci_trigger"]
