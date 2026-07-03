"""Regression tests for FINDINGS.md M10: orphaned generated workbooks and
.recalc-* scratch dirs left behind by crashes must be swept at startup —
old entries removed, anything recent (possibly in-flight) left alone.
"""

import os
import time

from app.services.storage_maintenance import sweep_generated_files

_TWO_DAYS_AGO = time.time() - 2 * 24 * 3600


def _age(path):
    os.utime(path, (_TWO_DAYS_AGO, _TWO_DAYS_AGO))


def test_old_files_and_dirs_removed_fresh_kept(tmp_path):
    old_file = tmp_path / "11111111.xlsx"
    old_file.write_bytes(b"stale")
    _age(old_file)

    old_dir = tmp_path / ".recalc-deadbeef"
    old_dir.mkdir()
    (old_dir / "leftover.xlsx").write_bytes(b"stale")
    _age(old_dir)

    fresh_file = tmp_path / "22222222.xlsx"
    fresh_file.write_bytes(b"in flight")

    removed = sweep_generated_files(directory=tmp_path, max_age_hours=24)

    assert removed == 2
    assert not old_file.exists()
    assert not old_dir.exists()
    assert fresh_file.exists()


def test_missing_directory_is_a_noop(tmp_path):
    assert sweep_generated_files(directory=tmp_path / "nope") == 0
