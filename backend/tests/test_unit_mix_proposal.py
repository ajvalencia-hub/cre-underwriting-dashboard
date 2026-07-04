"""G5: rent roll -> unit mix aggregation. Groupings from the golden Yardi and
RealPage fixtures, occupancy math, provenance counts, the hostile
inconsistent-label fallback, and the extraction-result plumbing."""

import pytest

from app.services.extraction import excel_extractor, rent_roll_parser
from tests.extraction_corpus import builders


def _rows_from_fixture(build_fn, tmp_path, name: str) -> list[dict]:
    path = tmp_path / name
    build_fn(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    return rent_roll_parser.parse_rows(grid["headers"], grid["rows"], name, grid["sheet"])["rows"]


def test_yardi_grouping_and_occupancy(tmp_path):
    """The golden Yardi roll: 3x 1BR/1BA (1 vacant by VACANT marker) and
    3x 2BR/2BA (1 blank vacant row); subtotal rows must not become units."""
    rows = _rows_from_fixture(builders.build_yardi_rent_roll, tmp_path, "yardi.xlsx")
    proposal = rent_roll_parser.propose_unit_mix(rows)

    assert proposal["groupedBy"] == "label"
    assert proposal["warnings"] == []
    by_type = {r["unitType"]: r for r in proposal["rows"]}
    assert set(by_type) == {"1BR/1BA", "2BR/2BA"}

    one_bed = by_type["1BR/1BA"]
    assert one_bed["unitCount"] == 3
    assert one_bed["occupiedCount"] == 2
    assert one_bed["occupancyPct"] == pytest.approx(2 / 3, abs=1e-4)
    assert one_bed["sourceRowCount"] == 3
    assert one_bed["avgSf"] == 750
    assert one_bed["inPlaceRent"] == round((1450 + 1480) / 2)  # occupied only
    assert one_bed["marketRent"] == 1500

    two_bed = by_type["2BR/2BA"]
    assert two_bed["unitCount"] == 3
    assert two_bed["occupiedCount"] == 2
    assert two_bed["inPlaceRent"] == round((2050 + 2080) / 2)


def test_realpage_grouping_by_floorplan_label(tmp_path):
    """RealPage floorplan codes (A1/B2) don't parse to bed/bath — grouping
    stays label-keyed with explicit-status occupancy."""
    rows = _rows_from_fixture(builders.build_realpage_rent_roll, tmp_path, "realpage.xlsx")
    proposal = rent_roll_parser.propose_unit_mix(rows)

    assert proposal["groupedBy"] == "label"
    by_type = {r["unitType"]: r for r in proposal["rows"]}
    assert by_type["A1"]["unitCount"] == 3
    assert by_type["A1"]["occupiedCount"] == 2  # Vacant-Ready row is vacant
    assert by_type["B2"]["unitCount"] == 2
    # "Notice" status is not vacant -> occupied per the status inference.
    assert by_type["B2"]["occupiedCount"] == 2


def test_inconsistent_labels_fall_back_to_bed_bath_grouping():
    """Hostile roll: the same 1-bed/1-bath type labeled three different ways
    must collapse into ONE group, with a warning naming the fallback."""
    def unit(unit_type, rent, status="occupied"):
        return {
            "unit": "x", "tenant": "t" if status == "occupied" else None, "sf": 700,
            "unitType": unit_type, "status": status, "inPlaceRentMonthly": rent,
            "marketRentMonthly": rent, "sourceRef": {},
        }

    rows = [
        unit("1BR/1BA", 1400),
        unit("1x1", 1420),
        unit("1 Bed 1 Bath", 1380),
        unit("2BR/2BA", 2000),
        unit("PH-A", 3000),  # unparseable label keeps its own group
    ]
    proposal = rent_roll_parser.propose_unit_mix(rows)

    assert proposal["groupedBy"] == "bedBath"
    assert any("inconsistent" in w.lower() for w in proposal["warnings"])
    by_type = {r["unitType"]: r for r in proposal["rows"]}
    assert by_type["1 BR / 1 BA"]["unitCount"] == 3
    assert by_type["1 BR / 1 BA"]["inPlaceRent"] == round((1400 + 1420 + 1380) / 3)
    assert by_type["2 BR / 2 BA"]["unitCount"] == 1
    assert by_type["PH-A"]["unitCount"] == 1


def test_bed_bath_parsing_variants():
    cases = {
        "1BR/1BA": (1, 1.0),
        "2 bd / 2 ba": (2, 2.0),
        "3x2.5": (3, 2.5),
        "Studio": (0, 1.0),
        "Efficiency": (0, 1.0),
        "2 Bed 1 Bath": (2, 1.0),
        "1BR": (1, None),
        "A1": None,
        "": None,
        None: None,
    }
    for label, expected in cases.items():
        assert rent_roll_parser._bed_bath_key(label) == expected, label


def test_extraction_result_carries_the_proposal(tmp_path):
    """End-to-end through extraction_service: a multifamily rent roll yields
    a top-level unitMixProposal alongside the legacy unitMix field, using the
    same grouping."""
    from app.models import Document
    from app.services import extraction_service

    path = tmp_path / "yardi.xlsx"
    builders.build_yardi_rent_roll(path)
    doc = Document(
        filename="yardi.xlsx", file_hash="h", stored_path=str(path), file_ext="xlsx",
        document_type="rent_roll", type_confidence=1.0,
    )
    outcome = extraction_service.run_extraction([doc])

    proposal = outcome["unitMixProposal"]
    assert proposal is not None
    assert {r["unitType"] for r in proposal["rows"]} == {"1BR/1BA", "2BR/2BA"}
    legacy = outcome["fields"]["unitMix"]["value"]
    assert [r["unitType"] for r in legacy] == [r["unitType"] for r in proposal["rows"]]
    # provenance columns exist on the proposal but never on the legacy field
    assert "sourceRowCount" in proposal["rows"][0]
    assert "sourceRowCount" not in legacy[0]
