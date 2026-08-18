from dataclasses import dataclass, field

from graph.ci_trigger import _collect_failed_jobs, _resolve_ref, ci_trigger_node
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
