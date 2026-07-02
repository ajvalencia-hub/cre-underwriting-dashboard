"""Regression tests for FINDINGS.md H4/H5: injection edge cases that crashed
the whole generate flow (multi-cell named ranges, merged-cell targets).
"""

import openpyxl
import pytest
from openpyxl.workbook.defined_name import DefinedName

from app.services.excel_writer import inject_values, read_output_values


@pytest.fixture
def template(tmp_path):
    """A workbook with a multi-cell named range, a scalar named range, and a
    merged region — the exact shapes that used to raise AttributeError."""
    path = tmp_path / "template.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "My Sheet"  # space on purpose
    ws["B1"] = 0
    ws["D1"] = "=B1*2"
    ws.merge_cells("A3:C3")
    ws["A3"] = None
    wb.defined_names.add(DefinedName("ScalarName", attr_text="'My Sheet'!$B$1"))
    wb.defined_names.add(DefinedName("RangeName", attr_text="'My Sheet'!$B$1:$C$2"))
    wb.save(path)
    return path


def test_multi_cell_named_range_is_skipped_with_warning_not_crash(template, tmp_path):
    out = tmp_path / "out.xlsx"
    mappings = {
        "badField": {"target": "namedRange", "ref": "RangeName"},
        "goodField": {"target": "namedRange", "ref": "ScalarName"},
    }
    result = inject_values(template, out, mappings, {"badField": 5, "goodField": 7})

    assert "badField" not in result["written"]
    assert any("multi-cell range" in w and "badField" in w for w in result["warnings"])
    # The rest of the injection still happened:
    assert "goodField" in result["written"]
    wb = openpyxl.load_workbook(out)
    assert wb["My Sheet"]["B1"].value == 7


def test_read_output_values_skips_multi_cell_named_range(template):
    mappings = {"m": {"target": "namedRange", "ref": "RangeName"}}
    assert read_output_values(template, mappings, ["m"]) == {}
