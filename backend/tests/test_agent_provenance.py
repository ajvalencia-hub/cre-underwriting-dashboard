"""K5: the anti-hallucination guarantee. A fabricated figure with no
supporting tool call must be flagged; every figure that traces to a tool
result must be clean; numbers inside the assistant's own quoted echoes of
the user's text must not be flagged. This is a first-class, build-gating
test file — if these fail, the guarantee doesn't hold."""

from app.services.agent import provenance


def _tool_call(name: str, arguments: dict, result: dict) -> dict:
    return {"name": name, "arguments": arguments, "result": result, "privilege": "read"}


def test_fabricated_dscr_with_no_supporting_tool_call_is_flagged():
    log = [_tool_call("compute", {"values": {}}, {"outputs": {"leveredIrr": 0.115718, "equityMultiple": 1.55}})]
    text = "This deal has a strong DSCR of 1.9, well above lender minimums."

    unverified = provenance.check_provenance(text, log)

    assert len(unverified) == 1
    assert unverified[0]["kind"] == "bare"
    assert unverified[0]["value"] == 1.9


def test_turn_where_every_figure_traces_to_a_tool_result_is_clean():
    log = [_tool_call(
        "compute", {"values": {}},
        {"outputs": {"leveredIrr": 0.115718, "equityMultiple": 1.55, "minDscr": 1.6}},
    )]
    text = "The levered IRR is 11.6%, the equity multiple is 1.55x, and the DSCR is 1.6."

    assert provenance.check_provenance(text, log) == []


def test_number_inside_quoted_echo_of_user_text_is_not_flagged():
    log = [_tool_call("compute", {"values": {}}, {"outputs": {"leveredIrr": 0.115718}})]
    text = (
        'You asked about "a $5,000 rent bump" — I ran the numbers and the '
        "resulting levered IRR is 11.6%."
    )

    assert provenance.check_provenance(text, log) == []


def test_dollar_claim_with_million_suffix_matches_within_rounding_tolerance():
    log = [_tool_call("compute", {}, {"outputs": {"terminalValue": 19292819.45}})]
    text = "The exit value is approximately $19.3M."

    assert provenance.check_provenance(text, log) == []


def test_unmatched_dollar_claim_is_flagged():
    log = [_tool_call("compute", {}, {"outputs": {"terminalValue": 19292819.45}})]
    text = "The exit value is approximately $50.0M."

    unverified = provenance.check_provenance(text, log)
    assert len(unverified) == 1
    assert unverified[0]["kind"] == "dollar"


def test_unmatched_percent_claim_is_flagged():
    log = [_tool_call("compute", {}, {"outputs": {"leveredIrr": 0.115718}})]
    text = "This deal should hit a 25% IRR easily."

    unverified = provenance.check_provenance(text, log)
    assert len(unverified) == 1
    assert unverified[0]["kind"] == "percent"


def test_multiple_claim_matches_equity_multiple_output():
    log = [_tool_call("compute", {}, {"outputs": {"equityMultiple": 1.55}})]
    assert provenance.check_provenance("Equity multiple comes out to 1.55x.", log) == []
    unverified = provenance.check_provenance("Equity multiple comes out to 2.10x.", log)
    assert len(unverified) == 1
    assert unverified[0]["kind"] == "multiple"


def test_claim_value_can_come_from_tool_arguments_not_just_results():
    # A solve target the model itself specified (e.g. "targeting a 15% IRR")
    # is grounded in its own tool call this turn, not fabricated.
    log = [_tool_call(
        "solve",
        {"targetMetric": "leveredIrr", "targetValue": 0.15},
        {"fieldValue": 0.079, "metricValue": 0.15},
    )]
    text = "Targeting a 15% IRR, the exit cap would need to be about 7.9%."
    assert provenance.check_provenance(text, log) == []


def test_no_tool_calls_flags_every_claim():
    text = "The levered IRR is 11.6%."
    unverified = provenance.check_provenance(text, [])
    assert len(unverified) == 1


def test_known_values_flattens_nested_dicts_and_lists_and_skips_bools_and_strings():
    log = [_tool_call(
        "run_sensitivity",
        {"drivers": [{"fieldId": "exitCapRatePct", "values": [0.07, 0.08]}]},
        {"points": [
            {"driverValues": {"exitCapRatePct": 0.07}, "outputs": {"leveredIrr": 0.13}, "warnings": []},
            {"driverValues": {"exitCapRatePct": 0.08}, "outputs": {"leveredIrr": 0.1157}, "flag": True},
        ]},
    )]
    known = provenance.known_values_from_tool_calls(log)
    assert 0.07 in known
    assert 0.08 in known
    assert 0.13 in known
    assert 0.1157 in known
    assert not any(isinstance(k, bool) for k in known)
