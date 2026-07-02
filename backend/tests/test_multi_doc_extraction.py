"""Regression tests for FINDINGS.md H7: extracting two documents of the same
type sums them into single fields — that behavior must carry a loud warning.
"""

from app.models import Document
from app.services.extraction_service import run_extraction

MONTH_HEADER = "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec"


def _t12_doc(tmp_path, name: str, gpr: float, taxes: float) -> Document:
    months = ",".join(["0"] * 12)
    path = tmp_path / name
    path.write_text(
        f"Line Item,{MONTH_HEADER},Total\n"
        f"Gross Potential Rent,{months},{gpr}\n"
        f"Real Estate Taxes,{months},{taxes}\n",
        encoding="utf-8",
    )
    return Document(
        filename=name,
        file_hash=name,
        stored_path=str(path),
        file_ext="csv",
        document_type="t12_operating_statement",
        type_confidence=1.0,
        type_source="manual",
        type_rationale="",
    )


def test_two_t12s_are_summed_with_explicit_warning(tmp_path):
    doc_a = _t12_doc(tmp_path, "t12_2025.csv", gpr=100_000, taxes=10_000)
    doc_b = _t12_doc(tmp_path, "t12_2024.csv", gpr=50_000, taxes=5_000)

    outcome = run_extraction([doc_a, doc_b])

    # The summing behavior itself (documented):
    assert outcome["fields"]["grossPotentialRent"]["value"] == 150_000
    assert outcome["fields"]["realEstateTaxes"]["value"] == 15_000
    # …and it is no longer silent:
    assert any(
        "2 T-12 documents were merged" in w and "t12_2025.csv" in w and "t12_2024.csv" in w
        for w in outcome["warnings"]
    )


def test_single_t12_produces_no_merge_warning(tmp_path):
    doc = _t12_doc(tmp_path, "t12.csv", gpr=100_000, taxes=10_000)
    outcome = run_extraction([doc])
    assert outcome["fields"]["grossPotentialRent"]["value"] == 100_000
    assert not any("documents were merged" in w for w in outcome["warnings"])
