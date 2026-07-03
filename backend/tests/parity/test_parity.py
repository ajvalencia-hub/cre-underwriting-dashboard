"""F4: parity tests. The injection layer is asserted unconditionally (right
cells through named/sheet-scoped names and merge anchors, fullCalcOnLoad);
the full native-vs-LibreOffice output diff runs when LibreOffice is
installed and skips with a reason when it isn't.
"""

import pytest

from app.services import recalc_service
from tests.parity.cases import load_builtin_cases
from tests.parity.harness import format_diff_table, run_case

CASES = load_builtin_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_injection_layer_is_always_clean(case, tmp_path):
    template = case.materialize_template(tmp_path)
    result = run_case(template, case.mapping, case.inputs, tmp_path)
    assert result["injectionProblems"] == []


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_native_engine_matches_excel(case, tmp_path):
    if not recalc_service.is_available():
        pytest.skip("LibreOffice not installed — Excel recalc parity skipped")
    template = case.materialize_template(tmp_path)
    result = run_case(template, case.mapping, case.inputs, tmp_path)
    assert result["injectionProblems"] == []
    diverged = [d for d in result["diffs"] if not d.ok]
    assert not diverged, "\n" + format_diff_table(case.name, result["diffs"])
