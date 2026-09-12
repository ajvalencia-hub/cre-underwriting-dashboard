"""Ad-hoc parity CLI: python -m tests.parity.run (from backend/).

Runs every corpus case (built-in synthetics + dropin templates) through both
calculation paths and prints a divergence table. Exit code 1 on any
divergence or injection problem.

Without LibreOffice the recalc diff is SKIPPED per case (injection checks
still run). Pass --require-libreoffice (CI does) to make a missing
LibreOffice — or any skipped case — a failure instead of a silent pass:
exit code 2 when soffice is not on PATH at all, 1 when a case skips anyway.
"""

import argparse
import sys
import tempfile
from pathlib import Path

from app.services import recalc_service
from tests.parity.cases import load_all_cases
from tests.parity.export_case import run_export_parity
from tests.parity.harness import format_diff_table, run_case


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.parity.run",
        description="Native-engine vs Excel (LibreOffice recalc) parity table.",
    )
    parser.add_argument(
        "--require-libreoffice",
        action="store_true",
        help="fail (non-zero exit) when LibreOffice is unavailable or any case is "
        "skipped, instead of printing SKIPPED",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.require_libreoffice and not recalc_service.is_available():
        print(
            "ERROR: --require-libreoffice given but LibreOffice (soffice) is not "
            "available — install libreoffice-calc or drop the flag.",
            file=sys.stderr,
        )
        return 2

    failures = 0
    skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for case in load_all_cases():
            template = case.materialize_template(workdir)
            result = run_case(template, case.mapping, case.inputs, workdir)

            for problem in result["injectionProblems"]:
                print(f"{case.name}: INJECTION PROBLEM — {problem}")
                failures += 1

            if result["diffs"] is None:
                print(f"{case.name}: SKIPPED — {result['skipReason']}")
                skipped += 1
                continue

            print(format_diff_table(case.name, result["diffs"]))
            failures += sum(1 for d in result["diffs"] if not d.ok)
            print()

        # H11: the native-exported (formula-live) workbook is its own path —
        # same recalc, same tolerances.
        for name, diffs, skip_reason in run_export_parity(workdir):
            if diffs is None:
                print(f"{name}: SKIPPED — {skip_reason}")
                skipped += 1
                continue
            print(format_diff_table(name, diffs))
            failures += sum(1 for d in diffs if not d.ok)
            print()

    if skipped and args.require_libreoffice:
        print(f"{skipped} case(s) skipped but --require-libreoffice was given.")
        failures += skipped

    if failures:
        print(f"{failures} divergence(s)/problem(s).")
        return 1
    print("Parity clean." + (f" ({skipped} skipped — no LibreOffice)" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
