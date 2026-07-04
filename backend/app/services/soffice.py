"""Shared LibreOffice headless launcher.

One implementation of soffice discovery + per-invocation-profile conversion,
used by recalc_service (xlsx recalc round-trip) and the memo PDF export.
Concurrent soffice processes contend for the shared user-profile lock, so
every invocation gets its own scratch profile inside its scratch dir.
"""

import shutil
import subprocess
import time
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


def build_convert_command(path: Path, tmp_dir: Path, target_format: str) -> list[str]:
    # Short name on purpose: the profile tree LibreOffice bootstraps inside is
    # deep, and Writer's exceeds Windows MAX_PATH under long storage paths —
    # which crashes soffice with 0xC0000409 (empirically diagnosed; Calc's
    # shallower tree happened to fit).
    profile_dir = tmp_dir / "lp"
    return [
        LIBREOFFICE_BIN or "soffice",
        "--headless",
        f"-env:UserInstallation={profile_dir.as_uri()}",
        "--convert-to",
        target_format,
        "--outdir",
        str(tmp_dir),
        str(path),
    ]


_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0


def convert_file(path: Path, target_format: str, timeout: int = 60) -> Path:
    """Convert `path` to `target_format` in a scratch dir next to it and
    return the converted file's path INSIDE that scratch dir — the caller
    reads/moves it and the scratch dir is cleaned up by remove_scratch().
    Raises RuntimeError on failure or when soffice is missing.

    Retries: soffice on Windows intermittently fail-fasts (0xC0000409) when
    relaunched while a previous instance is still tearing down. Each attempt
    gets a fresh scratch dir + profile, so retrying is safe and idempotent.
    """
    if not is_available():
        raise RuntimeError("LibreOffice not found on PATH")

    last_error = "unknown"
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_RETRY_DELAY_SECONDS)
        tmp_dir = path.parent / f".so-{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            build_convert_command(path, tmp_dir, target_format),
            timeout=timeout,
            capture_output=True,
        )
        converted = tmp_dir / (path.stem + "." + target_format.split(":")[0])
        if proc.returncode == 0 and converted.exists():
            return converted
        shutil.rmtree(tmp_dir, ignore_errors=True)
        stderr = proc.stderr.decode(errors="replace").strip()
        last_error = stderr or f"LibreOffice exited with code {proc.returncode}"
    raise RuntimeError(f"{last_error} (after {_ATTEMPTS} attempts)")


def remove_scratch(converted_path: Path) -> None:
    shutil.rmtree(converted_path.parent, ignore_errors=True)
