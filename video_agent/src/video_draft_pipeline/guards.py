from .schema import Scene


class DurationExceededError(Exception):
    pass


class BudgetExceededError(Exception):
    pass


def duration_guard(scenes: list[Scene], max_duration_sec: float) -> float:
    total = sum(scene.duration_sec for scene in scenes)
    if total > max_duration_sec:
        raise DurationExceededError(
            f"Total scene duration {total}s exceeds cap of {max_duration_sec}s"
        )
    return total


def budget_guard(current_cost_usd: float, additional_cost_usd: float, max_budget_usd: float) -> float:
    if additional_cost_usd < 0:
        raise BudgetExceededError(
            f"Additional cost ${additional_cost_usd:.2f} is negative; "
            "a render may never credit the running budget"
        )

    projected = current_cost_usd + additional_cost_usd
    if projected > max_budget_usd:
        raise BudgetExceededError(
            f"Projected cost ${projected:.2f} exceeds budget cap of ${max_budget_usd:.2f}"
        )
    return projected
