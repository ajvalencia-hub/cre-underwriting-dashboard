import shutil
import subprocess
import uuid
from pathlib import Path

_FALLBACK_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def _find_libreoffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for candidate in _FALLBACK_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


LIBREOFFICE_BIN = _find_libreoffice()


def is_available() -> bool:
    return LIBREOFFICE_BIN is not None


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
    if not is_available():
        raise RuntimeError("LibreOffice not found on PATH")

    # LibreOffice's --convert-to refuses to overwrite a file in place (source == dest
    # path), so convert into a scratch subdirectory and move the result back.
    tmp_dir = path.parent / f".recalc-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [
                LIBREOFFICE_BIN,
                "--headless",
                "--convert-to",
                path.suffix.lstrip("."),
                "--outdir",
                str(tmp_dir),
                str(path),
            ],
            timeout=timeout,
            capture_output=True,
        )
        converted = tmp_dir / path.name
        if proc.returncode != 0 or not converted.exists():
            stderr = proc.stderr.decode(errors="replace").strip()
            raise RuntimeError(stderr or f"LibreOffice exited with code {proc.returncode}")
        shutil.move(str(converted), str(path))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
