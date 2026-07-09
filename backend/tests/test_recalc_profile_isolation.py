"""Regression tests for FINDINGS.md M12: concurrent LibreOffice recalcs
contend for the shared user-profile lock and fail intermittently. Every
soffice invocation must carry its own -env:UserInstallation scratch profile.
"""


from app.services.recalc_service import _build_convert_command


def _profile_arg(cmd: list[str]) -> str:
    matches = [a for a in cmd if a.startswith("-env:UserInstallation=")]
    assert len(matches) == 1
    return matches[0]


def test_command_carries_a_scratch_profile(tmp_path):
    cmd = _build_convert_command(tmp_path / "book.xlsx", tmp_path / "scratch")
    arg = _profile_arg(cmd)
    # Must be a file URI (soffice requirement), inside the scratch dir so the
    # existing cleanup removes it.
    assert arg.split("=", 1)[1].startswith("file://")
    assert (tmp_path / "scratch").name in arg


def test_concurrent_invocations_get_distinct_profiles(tmp_path):
    cmd_a = _build_convert_command(tmp_path / "a.xlsx", tmp_path / "scratch-a")
    cmd_b = _build_convert_command(tmp_path / "b.xlsx", tmp_path / "scratch-b")
    assert _profile_arg(cmd_a) != _profile_arg(cmd_b)


def test_convert_arguments_preserved(tmp_path):
    scratch = tmp_path / "scratch"
    cmd = _build_convert_command(tmp_path / "book.xlsm", scratch)
    assert "--headless" in cmd
    assert cmd[cmd.index("--convert-to") + 1] == "xlsm"
    assert cmd[cmd.index("--outdir") + 1] == str(scratch)
    assert cmd[-1] == str(tmp_path / "book.xlsm")
