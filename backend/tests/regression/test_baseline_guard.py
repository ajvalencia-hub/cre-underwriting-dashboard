"""The UPDATE_BASELINE=1 guard: regenerating the Run-4 baseline is allowed
only when the live payload is a pure EXPANSION of the recorded one (new dict
keys). Any changed value, vanished key, or resized list is a behavior change
and must be refused — the baseline is never loosened to fit."""

from tests.regression.test_run4_baseline import expansion_violations


def test_identical_payload_has_no_violations():
    payload = {"outputs": {"noi": 80000.0, "irr": 0.083}, "rows": [1, 2, 3]}
    assert expansion_violations(payload, payload, "case") == []


def test_new_keys_anywhere_are_allowed():
    expected = {"outputs": {"noi": 80000.0}, "nested": [{"a": 1}]}
    actual = {
        "outputs": {"noi": 80000.0, "newMetric": 1.0},  # new leaf key
        "nested": [{"a": 1, "b": 2}],  # new key inside a list element
        "newBlock": {"x": 1},  # new top-level key
    }
    assert expansion_violations(expected, actual, "case") == []


def test_changed_value_is_refused():
    expected = {"outputs": {"noi": 80000.0}}
    actual = {"outputs": {"noi": 80000.5}}
    violations = expansion_violations(expected, actual, "case")
    assert violations == ["case.outputs.noi: 80000.0 -> 80000.5"]


def test_float_noise_within_tolerance_is_not_a_change():
    expected = {"irr": 0.1}
    actual = {"irr": 0.1 + 1e-12}
    assert expansion_violations(expected, actual, "case") == []


def test_disappeared_key_is_refused():
    expected = {"outputs": {"noi": 1.0, "irr": 0.1}}
    actual = {"outputs": {"noi": 1.0}}
    assert expansion_violations(expected, actual, "case") == ["case.outputs.irr: key disappeared"]


def test_list_length_change_is_refused_even_when_longer():
    expected = {"rows": [1, 2]}
    actual = {"rows": [1, 2, 3]}
    assert expansion_violations(expected, actual, "case") == ["case.rows: length 2 -> 3"]


def test_type_change_is_refused():
    expected = {"governingConstraint": "ltv"}
    actual = {"governingConstraint": 1}  # string -> number is a contract change
    assert expansion_violations(expected, actual, "case") == [
        "case.governingConstraint: 'ltv' -> 1"
    ]


def test_dict_replaced_by_scalar_is_refused():
    expected = {"debt": {"ltv": 0.6}}
    actual = {"debt": None}
    assert expansion_violations(expected, actual, "case") == ["case.debt: {'ltv': 0.6} -> None"]


def test_mixed_addition_and_change_reports_only_the_change():
    expected = {"a": 1, "b": {"c": 2}}
    actual = {"a": 1, "b": {"c": 3, "d": 4}, "e": 5}
    assert expansion_violations(expected, actual, "case") == ["case.b.c: 2 -> 3"]
