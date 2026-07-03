"""Ad-hoc parity CLI: python -m tests.parity.run (from backend/).

Runs every corpus case (built-in synthetics + dropin templates) through both
calculation paths and prints a divergence table. Exit code 1 on any
divergence or injection problem.
"""

import sys
import tempfile
from pathlib import Path

from tests.parity.cases import load_all_cases
from tests.parity.harness import format_diff_table, run_case


def main() -> int:
    failures = 0
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
                continue

            print(format_diff_table(case.name, result["diffs"]))
            failures += sum(1 for d in result["diffs"] if not d.ok)
            print()

    if failures:
        print(f"{failures} divergence(s)/problem(s).")
        return 1
    print("Parity clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
