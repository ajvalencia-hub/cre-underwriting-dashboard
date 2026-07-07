"""K0: goal-seek for the full engine. Bisection over one numeric input field
against one output metric, calling the pure engine.compute repeatedly. This
adds no new engine math — engine.compute's formulas are untouched — it only
orchestrates the existing pure function in a loop, the same way tornado_service
and the sensitivity endpoints already do."""

from app.services.proforma import engine

_MAX_ITERATIONS_CAP = 100


class SolveOutOfRangeError(Exception):
    pass


class SolveNoConvergenceError(Exception):
    pass


def _metric_at(values: dict, target_field: str, target_metric: str, field_value: float) -> float:
    trial = {**values, target_field: field_value}
    result = engine.compute(trial)
    outputs = result["outputs"]
    if target_metric not in outputs or outputs[target_metric] is None:
        raise ValueError(f"Metric '{target_metric}' is not present in compute outputs for this deal.")
    return outputs[target_metric]


def _result(field_value: float, metric_value: float, iterations: int) -> dict:
    return {"fieldValue": field_value, "metricValue": metric_value, "iterations": iterations}


def solve(
    values: dict,
    target_field: str,
    target_metric: str,
    target_value: float,
    lower_bound: float,
    upper_bound: float,
    tolerance: float = 1e-4,
    max_iterations: int = 50,
) -> dict:
    """Finds target_field's value such that compute(values)[target_metric] ==
    target_value, within [lower_bound, upper_bound]. Requires a sign change
    across the bounds (i.e. the metric crosses the target somewhere in range) —
    true for every field/metric pair the agent's solve tool is meant to be used
    with (price vs IRR, rent vs yield-on-cost, exit cap vs IRR, etc.)."""
    if lower_bound >= upper_bound:
        raise ValueError("lowerBound must be less than upperBound.")
    iterations = max(1, min(max_iterations, _MAX_ITERATIONS_CAP))

    f_low = _metric_at(values, target_field, target_metric, lower_bound) - target_value
    if abs(f_low) < tolerance:
        return _result(lower_bound, f_low + target_value, 0)
    f_high = _metric_at(values, target_field, target_metric, upper_bound) - target_value
    if abs(f_high) < tolerance:
        return _result(upper_bound, f_high + target_value, 0)
    if f_low * f_high > 0:
        raise SolveOutOfRangeError(
            f"No solution in [{lower_bound}, {upper_bound}] — '{target_metric}' never "
            f"crosses {target_value} across this range."
        )

    low, high = lower_bound, upper_bound
    for i in range(1, iterations + 1):
        mid = (low + high) / 2
        f_mid = _metric_at(values, target_field, target_metric, mid) - target_value
        if abs(f_mid) < tolerance:
            return _result(mid, f_mid + target_value, i)
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid

    raise SolveNoConvergenceError(
        f"Did not converge to '{target_metric}' = {target_value} within {iterations} "
        f"iterations (tolerance {tolerance})."
    )
