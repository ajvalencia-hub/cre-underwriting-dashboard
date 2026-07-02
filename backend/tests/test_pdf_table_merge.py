"""Regression tests for FINDINGS.md C2: a rent roll spanning multiple PDF pages
must be merged into one grid, not truncated to the single largest table.
"""

from app.services.extraction_service import _grid_from_pdf_tables


def _page(n, *tables):
    return {"pageNumber": n, "text": "", "tables": list(tables)}


HEADER = ["Unit", "SF", "Rent"]


def test_multi_page_tables_merge_with_repeated_headers_dropped():
    pages = [
        _page(1, [HEADER, ["101", "800", "950"], ["102", "850", "1000"]]),
        _page(2, [HEADER, ["103", "800", "975"], ["104", "850", "1025"]]),
        _page(3, [HEADER, ["105", "800", "990"]]),
    ]
    grid, warnings = _grid_from_pdf_tables(pages)

    assert grid["headers"] == HEADER
    assert [r[0] for r in grid["rows"]] == ["101", "102", "103", "104", "105"]
    assert grid["sheet"] == "pages 1-3"
    assert any("merged 3 tables" in w for w in warnings)


def test_continuation_pages_without_repeated_headers_are_included_fully():
    pages = [
        _page(1, [HEADER, ["101", "800", "950"]]),
        _page(2, [["102", "850", "1000"], ["103", "800", "975"]]),  # no header repeat
    ]
    grid, _ = _grid_from_pdf_tables(pages)
    assert [r[0] for r in grid["rows"]] == ["101", "102", "103"]


def test_different_shape_tables_are_excluded():
    pages = [
        _page(1, [HEADER, ["101", "800", "950"], ["102", "850", "1000"]]),
        # a 2-column summary box that must NOT be glued onto the rent roll
        _page(2, [["Total Units", "2"], ["Occupancy", "100%"]]),
        _page(2, [HEADER, ["103", "800", "975"]]),
    ]
    grid, _ = _grid_from_pdf_tables(pages)
    assert [r[0] for r in grid["rows"]] == ["101", "102", "103"]
    assert all(len(r) == 3 for r in grid["rows"])


def test_single_table_behaves_like_before_with_no_warning():
    pages = [_page(1, [HEADER, ["101", "800", "950"]])]
    grid, warnings = _grid_from_pdf_tables(pages)
    assert grid["sheet"] == "page 1"
    assert grid["rows"] == [["101", "800", "950"]]
    assert warnings == []


def test_no_tables_returns_none():
    assert _grid_from_pdf_tables([_page(1)]) == (None, [])


def test_header_only_table_returns_none():
    grid, _ = _grid_from_pdf_tables([_page(1, [HEADER])])
    assert grid is None
