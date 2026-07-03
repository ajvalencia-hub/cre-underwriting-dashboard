"""Startup cleanup for backend/storage/generated/ (FINDINGS.md M10).

Generated workbooks are deleted right after they're streamed back, and
recalc scratch dirs (.recalc-*) right after conversion — but a crash or
kill between create and delete leaves them behind forever. Everything in
GENERATED_DIR is transient by design, so anything old enough that no
in-flight request can still be using it is safe to remove.
"""

import shutil
import time
from pathlib import Path

from app.config import GENERATED_DIR


def sweep_generated_files(directory: Path = GENERATED_DIR, max_age_hours: float = 24) -> int:
    """Delete files/dirs in `directory` untouched for `max_age_hours`. Returns
    how many entries were removed. Never raises: a locked or vanished entry is
    someone else's business, not a startup failure.
    """
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    if not directory.exists():
        return removed
    for entry in directory.iterdir():
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed
