"""F5: named cross-validation rules — pass/warn/fail thresholds per rule,
and the end-to-end wiring of the parse metadata that feeds them.
"""

from app.services.extraction import cross_validation as cv


def _field(value):
    return {"value": value, "sourceRef": {}, "confidence": 0.9, "source": "deterministic"}


def _by_rule(checks):
    return {c["rule"]: c for c in checks}


def test_gpr_rule_pass_warn_fail_thresholds():
    def run(rr, t12):
        fields = {"_rentRollGprAnnual": _field(rr), "grossPotentialRent": _field(t12)}
        return _by_rule(cv.run_checks(fields))["rent_roll_vs_t12_gpr"]

    assert run(105_000, 100_000)["status"] == "pass"  # 5% apart
    assert run(115_000, 100_000)["status"] == "warn"  # 15%
    check = run(130_000, 100_000)
    assert check["status"] == "fail"  # 30%
    assert check["severity"] == "error"
    assert "grossPotentialRent" in check["relatedFieldIds"]


def test_unit_count_consistency():
    fields = {
        "_rentRollTotalUnits": _field(20),
        "unitMix": _field([{"unitType": "1BR", "unitCount": 12}, {"unitType": "2BR", "unitCount": 8}]),
    }
    assert _by_rule(cv.run_checks(fields))["unit_count_consistency"]["status"] == "pass"

    fields["unitMix"] = _field([{"unitType": "1BR", "unitCount": 12}])
    assert _by_rule(cv.run_checks(fields))["unit_count_consistency"]["status"] == "fail"


def test_t12_month_coverage():
    def run(months, period):
        fields = {"_t12Months": _field(months), "_t12PeriodType": _field(period)}
        return _by_rule(cv.run_checks(fields))["t12_month_coverage"]

    full = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    assert run(full, "T12")["status"] == "pass"
    assert run(full[:10], "T12")["status"] == "fail"  # gaps
    assert run(full[:10] + ["Jan", "Feb"], "T12")["status"] == "fail"  # duplicates
    assert run(["Jan", "Feb", "Mar"], "T3")["status"] == "warn"  # annualized
    assert run(None, "annual")["status"] == "warn"


def test_occupancy_vs_vacancy_and_low_occupancy():
    fields = {"_occupancyPct": _field(0.94), "vacancyPct": _field(0.05)}
    checks = _by_rule(cv.run_checks(fields))
    assert checks["occupancy_vs_t12_vacancy"]["status"] == "pass"
    assert "low_occupancy" not in checks

    fields = {"_occupancyPct": _field(0.70), "vacancyPct": _field(0.05)}
    checks = _by_rule(cv.run_checks(fields))
    assert checks["occupancy_vs_t12_vacancy"]["status"] == "warn"
    assert checks["low_occupancy"]["status"] == "warn"


def test_expense_ratio_flags_but_never_fails():
    def run(expenses):
        fields = {
            "grossPotentialRent": _field(100_000),
            "vacancyPct": _field(0.05),
            "_totalExpenses": _field(expenses),
        }
        return _by_rule(cv.run_checks(fields))["expense_ratio_sanity"]

    assert run(40_000)["status"] == "pass"  # 42% of EGI
    assert run(70_000)["status"] == "warn"  # 74% — flagged, not failed
    assert run(70_000)["severity"] == "warning"


def test_rules_with_missing_inputs_emit_nothing():
    assert cv.run_checks({}) == []


def test_t12_metadata_flows_through_the_pipeline():
    """The month-coverage rule needs _t12Months/_t12PeriodType — assert the
    extraction service actually plants them from a deterministic parse."""
    from app.models import Document
    from app.services import extraction_service

    headers = ["Line Item", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Total"]
    rows = [
        ["Gross Potential Rent"] + [10_000] * 12 + [120_000],
        ["Real Estate Taxes"] + [1_000] * 12 + [12_000],
    ]

    doc = Document(
        filename="t12.xlsx", file_hash="h", stored_path="/tmp/t12.xlsx",
        file_ext="xlsx", document_type="t12_operating_statement",
        type_confidence=1.0,
    )
    original = extraction_service._load_grid_and_text
    extraction_service._load_grid_and_text = lambda d: (
        {"headers": headers, "rows": rows, "sheet": "Sheet1"}, "", []
    )
    try:
        outcome = extraction_service.run_extraction([doc])
    finally:
        extraction_service._load_grid_and_text = original

    by_rule = _by_rule(outcome["crossValidation"])
    assert by_rule["t12_month_coverage"]["status"] == "pass"
    # Internal fields never reach the review screen.
    assert "_t12Months" not in outcome["fields"]
