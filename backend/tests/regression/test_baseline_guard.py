"""The UPDATE_BASELINE=1 guard: regenerating the Run-4 baseline is allowed
only when the live payload is a pure EXPANSION of the recorded one (new dict
keys). Any changed value, vanished key, or resized list is a behavior change
and is refused — unless the owner approved that case's move and the
regeneration names it in BASELINE_ALLOW_VALUE_CHANGES (ported from Run 6)."""

import pytest

from tests.regression.test_run4_baseline import expansion_violations, value_changes_allowed


def test_identical_payload_has_no_violations():
    payload = {"outputs": {"noi": 80000.0, "irr": 0.083}, "rows": [1, 2, 3]}
    assert expansion_violations(payload, payload, "case") == []


def test_new_keys_anywhere_are_allowed():
    expected = {"outputs": {"noi": 80000.0}, "nested": [{"a": 1}]}
    actual = {
        "outputs": {"noi": 80000.0, "newMetric": 1.0},
        "nested": [{"a": 1, "b": 2}],
        "newBlock": {"x": 1},
    }
    assert expansion_violations(expected, actual, "case") == []


def test_changed_value_is_refused():
    violations = expansion_violations({"outputs": {"noi": 80000.0}}, {"outputs": {"noi": 80000.5}}, "case")
    assert violations == ["case.outputs.noi: 80000.0 -> 80000.5"]


def test_float_noise_within_tolerance_is_not_a_change():
    assert expansion_violations({"irr": 0.1}, {"irr": 0.1 + 1e-12}, "case") == []


def test_disappeared_key_is_refused():
    violations = expansion_violations({"o": {"noi": 1.0, "irr": 0.1}}, {"o": {"noi": 1.0}}, "case")
    assert violations == ["case.o.irr: key disappeared"]


def test_list_length_change_is_refused_even_when_longer():
    assert expansion_violations({"rows": [1, 2]}, {"rows": [1, 2, 3]}, "case") == [
        "case.rows: length 2 -> 3"
    ]


def test_type_change_is_refused():
    assert expansion_violations({"g": "ltv"}, {"g": 1}, "case") == ["case.g: 'ltv' -> 1"]


def test_mixed_addition_and_change_reports_only_the_change():
    expected = {"a": 1, "b": {"c": 2}}
    actual = {"a": 1, "b": {"c": 3, "d": 4}, "e": 5}
    assert expansion_violations(expected, actual, "case") == ["case.b.c: 2 -> 3"]


@pytest.mark.parametrize(
    ("env", "name", "allowed"),
    [
        (None, "mixed_use", False),
        ("", "mixed_use", False),
        ("1", "mixed_use", True),  # owner-approved move of every case
        ("commercial_rollover", "commercial_rollover", True),
        ("commercial_rollover, mixed_use", "mixed_use", True),
        ("commercial_rollover", "mixed_use", False),
    ],
)
def test_owner_approval_escape(monkeypatch, env, name, allowed):
    if env is None:
        monkeypatch.delenv("BASELINE_ALLOW_VALUE_CHANGES", raising=False)
    else:
        monkeypatch.setenv("BASELINE_ALLOW_VALUE_CHANGES", env)
    assert value_changes_allowed(name) is allowed
