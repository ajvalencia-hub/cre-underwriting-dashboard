"""Server-side workbook recalculation via LibreOffice headless.

Discovery and the per-invocation-profile launch live in the shared
app.services.soffice module (also used by the memo PDF export); this module
keeps the xlsx-specific round-trip semantics.
"""

import shutil
from pathlib import Path

from app.services import soffice

# Re-exported for compatibility with existing call sites/tests.
LIBREOFFICE_BIN = soffice.LIBREOFFICE_BIN


def is_available() -> bool:
    return soffice.is_available()


def _build_convert_command(path: Path, tmp_dir: Path) -> list[str]:
    return soffice.build_convert_command(path, tmp_dir, path.suffix.lstrip("."))


def recalc_with_libreoffice(path: Path, timeout: int = 60) -> None:
    """Round-trip the workbook through LibreOffice headless so the download already
    shows computed values instead of relying on the user's copy of Excel to recalc.

    Tradeoff: LibreOffice re-serializes the file with its own xlsx writer, which can
    occasionally shift formatting/chart details that openpyxl's in-place edit would
    have preserved exactly. wb.calculation.fullCalcOnLoad (set unconditionally in
    excel_writer.inject_values) already guarantees correct values the moment the file
    is opened in real Excel, so this step is a nice-to-have preview, not a requirement
    for correctness — callers should treat a failure here as non-fatal.
    """
    converted = soffice.convert_file(path, path.suffix.lstrip("."), timeout=timeout)
    try:
        shutil.move(str(converted), str(path))
    finally:
        soffice.remove_scratch(converted)
