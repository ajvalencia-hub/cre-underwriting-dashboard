"""Regression tests for FINDINGS.md C1: T-12 line items that match no
income/expense category must never vanish silently — they must be surfaced
(unmatched list + warning), and the LLM branch must not mislabel them "income".
"""

from app.models import Document
from app.services import extraction_service
from app.services.extraction import llm_extraction, t12_parser


def _item(label, amount, category=None, bucket="unknown", non_recurring=False):
    return {
        "label": label,
        "amount": amount,
        "category": category,
        "bucket": bucket,
        "isNonRecurring": non_recurring,
        "sourceRef": {"doc": "t12.xlsx", "sheet": "S", "row": 1, "page": None, "cell": None},
        "confidence": 0.9,
        "source": "deterministic",
    }


def test_unmatched_lines_are_collected_not_dropped():
    items = [
        _item("Gross Potential Rent", 1_000_000, "grossPotentialRent", "income"),
        _item("Real Estate Taxes", 120_000, "realEstateTaxes", "expense"),
        _item("Landscaping", 40_000),  # matches no alias — the C1 failure case
        _item("Pest Control", 8_000),
        _item("Net Operating Income", 600_000, bucket="noi"),
    ]
    agg = t12_parser.aggregate_categories(items)

    labels = [li["label"] for li in agg["unclassified"]]
    assert labels == ["Landscaping", "Pest Control"]
    # …and they are (documented behavior) excluded from category totals:
    assert agg["totalExpenses"] == 120_000
    assert agg["noi"] == 600_000


def test_subtotal_rows_are_not_flagged_as_unclassified():
    items = [
        _item("Real Estate Taxes", 120_000, "realEstateTaxes", "expense"),
        _item("Total Operating Expenses", 350_000),  # derivable subtotal, not lost data
        _item("Net Income Before Debt Service", 500_000),
    ]
    agg = t12_parser.aggregate_categories(items)
    assert agg["unclassified"] == []


def test_parse_t12_marks_unmatched_lines_bucket_unknown():
    headers = ["Line Item", "Total"]
    rows = [
        ["Gross Potential Rent", 1_000_000],
        ["Landscaping", 40_000],
    ]
    parsed = t12_parser.parse_t12(headers, rows, "t12.xlsx", "Sheet1")
    by_label = {li["label"]: li for li in parsed["lineItems"]}
    assert by_label["Landscaping"]["bucket"] == "unknown"
    assert by_label["Landscaping"]["category"] is None


def test_aggregate_to_fields_surfaces_unclassified_in_unmatched_and_warnings():
    merged = {
        "scalarExtractions": [],
        "rentRollRows": [],
        "t12LineItems": [
            _item("Gross Potential Rent", 1_000_000, "grossPotentialRent", "income"),
            _item("Landscaping", 40_000),
        ],
        "unmatchedExtractions": [],
        "warnings": [],
    }
    fields = extraction_service._aggregate_to_fields(merged)

    assert fields["grossPotentialRent"]["value"] == 1_000_000
    # Landscaping appears in no field…
    assert all("landscaping" not in k.lower() for k in fields)
    # …but IS surfaced in the unmatched list (review-screen shape) and a warning.
    assert any(
        u["suggestedLabel"] == "T-12 line: Landscaping" and u["value"] == 40_000
        for u in merged["unmatchedExtractions"]
    )
    assert any("40,000" in w and "NOT included" in w for w in merged["warnings"])


def test_llm_none_category_becomes_unknown_not_income(monkeypatch):
    """Pre-fix, mappedCategory=None line items were bucketed 'income' and then
    silently dropped by aggregation. They must now surface as unclassified."""

    def fake_llm(document_type, text, source_doc, schema_fields):
        return {
            "result": {
                "documentType": "t12_operating_statement",
                "scalarExtractions": [],
                "rentRollRows": [],
                "t12LineItems": [
                    {
                        "label": "Landscaping",
                        "amount": 40_000,
                        "mappedCategory": None,
                        "isNonRecurring": False,
                        "sourceRef": {"doc": source_doc, "page": 1, "sheet": None, "cell": None, "row": None},
                        "confidence": 0.8,
                    },
                    {
                        "label": "Vacancy Loss",
                        "amount": -50_000,
                        "mappedCategory": "vacancyLoss",
                        "isNonRecurring": False,
                        "sourceRef": {"doc": source_doc, "page": 1, "sheet": None, "cell": None, "row": None},
                        "confidence": 0.9,
                    },
                ],
                "unmatchedExtractions": [],
                "warnings": [],
            },
            "note": None,
        }

    monkeypatch.setattr(llm_extraction, "extract_with_llm", fake_llm)

    doc = Document(
        filename="t12.pdf",
        file_hash="hash",
        stored_path="unused",
        file_ext="pdf",
        document_type="t12_operating_statement",
        type_confidence=1.0,
        type_source="manual",
        type_rationale="",
    )
    result = extraction_service._extract_t12(doc, grid=None, text="some text", warnings=[])

    by_label = {li["label"]: li for li in result["t12LineItems"]}
    assert by_label["Landscaping"]["bucket"] == "unknown"
    assert by_label["Vacancy Loss"]["bucket"] == "income"  # real category keeps its bucket
