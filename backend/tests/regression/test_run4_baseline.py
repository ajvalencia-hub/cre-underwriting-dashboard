"""J0: the Run-4 regression baseline (supersedes the Run-3 baseline).

For six representative deals — analytic acquisition + development, the
parity commercial NNN case, a rollover-heavy commercial roll, the H2
mixed-use fixture, and a value-add-shaped multifamily deal (the J1/J2
surface) — the FULL /api/compute?detail=true payload is recorded to JSON.
This test asserts the live payload is identical (floats to 1e-9) with
every Run-5 input at its default — it must pass after EVERY J-series
commit. If a feature cannot keep this green at defaults, the feature stops
and goes to BLOCKED.md; the baseline is never loosened to fit.

Regenerate (Run-4 behavior changes are NOT a valid reason; payload
EXPANSION with a verified key-only diff is):
    UPDATE_BASELINE=1 pytest tests/regression -q
The regeneration is guarded (ported from Run 6): it REFUSES to write a case
whose existing values moved. For an owner-approved value move (the DECISIONS
entry names the cases and why), name the cases — or 1 for all — in
BASELINE_ALLOW_VALUE_CHANGES:
    UPDATE_BASELINE=1 BASELINE_ALLOW_VALUE_CHANGES=commercial_rollover pytest tests/regression -q
"""

import json
import math
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import compute_cache

_HERE = Path(__file__).parent
_FIXTURES = _HERE / "fixtures"
_BASELINE = _HERE / "run4_baseline"
_PARITY_CORPUS = _HERE.parent / "parity" / "corpus"
_ENGINE_FIXTURES = _HERE.parent / "fixtures"

CASES = {
    "analytic_acquisition": _ENGINE_FIXTURES / "analytic_acquisition.json",
    "analytic_development": _ENGINE_FIXTURES / "analytic_development.json",
    "commercial_nnn": _PARITY_CORPUS / "commercial_nnn" / "inputs.json",
    "commercial_rollover": _FIXTURES / "commercial_rollover.json",
    "mixed_use": _FIXTURES / "mixed_use.json",
    "value_add_multifamily": _FIXTURES / "value_add_multifamily.json",
    # Run 6 (re-created on later-items): the value-add deal with its optional
    # features switched ON (floating debt + cap, mezz, renovation, loss-to-
    # lease, reserves, escrows, fees, prepayment cost), so the feature paths
    # themselves are pinned, not only their defaults.
    "feature_on_value_add": _FIXTURES / "feature_on_value_add.json",
}

FLOAT_TOL = 1e-9


def _compute_payload(inputs: dict) -> dict:
    compute_cache.clear()  # the baseline must exercise the real engine
    client = TestClient(app)
    response = client.post("/api/compute?detail=true", json={"values": inputs})
    assert response.status_code == 200, response.text
    return response.json()


def _diff(expected, actual, path: str, problems: list[str]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                problems.append(f"{path}.{key}: unexpected new key")
            elif key not in actual:
                problems.append(f"{path}.{key}: key disappeared")
            else:
                _diff(expected[key], actual[key], f"{path}.{key}", problems)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            problems.append(f"{path}: length {len(expected)} -> {len(actual)}")
            return
        for i, (e, a) in enumerate(zip(expected, actual)):
            _diff(e, a, f"{path}[{i}]", problems)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool) and isinstance(
        actual, (int, float)
    ) and not isinstance(actual, bool):
        if not math.isclose(expected, actual, rel_tol=FLOAT_TOL, abs_tol=FLOAT_TOL):
            problems.append(f"{path}: {expected!r} -> {actual!r}")
    elif expected != actual:
        problems.append(f"{path}: {expected!r} -> {actual!r}")


def expansion_violations(expected, actual, name: str) -> list[str]:
    """Pure guard for UPDATE_BASELINE: the differences between `actual` and
    `expected` that are NOT pure key additions. New dict keys (at any depth)
    are the only permitted difference; changed values, vanished keys, type
    changes and list-length changes are violations. Empty = regenerate."""
    problems: list[str] = []
    _diff(expected, actual, name, problems)
    return [p for p in problems if not p.endswith(": unexpected new key")]


def value_changes_allowed(name: str) -> bool:
    """Owner-approval escape: BASELINE_ALLOW_VALUE_CHANGES=1 (every case) or
    a comma-separated list of case names whose value moves are approved."""
    raw = os.environ.get("BASELINE_ALLOW_VALUE_CHANGES", "").strip()
    if not raw:
        return False
    if raw == "1":
        return True
    return name in {part.strip() for part in raw.split(",")}


@pytest.mark.parametrize("name", sorted(CASES))
def test_run4_baseline(name: str):
    inputs = json.loads(CASES[name].read_text())
    payload = _compute_payload(inputs)

    baseline_path = _BASELINE / f"{name}.json"
    if os.environ.get("UPDATE_BASELINE") == "1":
        # Regeneration is an EXPANSION-only operation unless the owner
        # approved this case's value move (see value_changes_allowed).
        if baseline_path.exists() and not value_changes_allowed(name):
            violations = expansion_violations(
                json.loads(baseline_path.read_text()), payload, name
            )
            if violations:
                raise AssertionError(
                    f"UPDATE_BASELINE refused for {name}: {len(violations)} existing "
                    "value(s) differ — only key additions may regenerate the baseline "
                    "(an owner-approved move needs BASELINE_ALLOW_VALUE_CHANGES; "
                    "first 20):\n" + "\n".join(violations[:20])
                )
        _BASELINE.mkdir(exist_ok=True)
        baseline_path.write_text(json.dumps(payload, indent=1, sort_keys=True))
        pytest.skip(f"baseline regenerated: {baseline_path.name}")

    assert baseline_path.exists(), (
        f"No baseline for {name} — run UPDATE_BASELINE=1 pytest tests/regression"
    )
    expected = json.loads(baseline_path.read_text())
    problems: list[str] = []
    _diff(expected, payload, name, problems)
    assert not problems, (
        f"{len(problems)} divergence(s) from the Run-4 baseline "
        f"(first 20):\n" + "\n".join(problems[:20])
    )
