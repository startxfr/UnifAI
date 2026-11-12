#!/usr/bin/env python3
"""Run the unit tests of one application suite, minus the upstream test debt (fork/ci/unit-test-debt.txt).

    run_unit_tests.py multi-agent [pytest args...]
    run_unit_tests.py rag
    run_unit_tests.py shared-resources/identity

Runs `python -m pytest tests/unit` in the suite directory with the interpreter running this script. Debt entries of the
suite become `--ignore=<path>` (a path, the module does not collect) or `--deselect=<node id>`. Any other failure,
fork test or upstream test, fails the run. Used by the `unit` job of .github/workflows/fork-tests.yml.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEBT = ROOT / "fork" / "ci" / "unit-test-debt.txt"
SUITES = ("multi-agent", "rag", "shared-resources/identity")


def debt_args(suite: str, lines) -> list[str]:
    """pytest arguments that skip the debt entries of `suite`."""
    args = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        owner, _, entry = line.partition(" ")
        entry = entry.strip()
        if not entry:
            raise ValueError(f"debt entry without a test: {raw!r}")
        if owner == suite:
            args.append(f"--deselect={entry}" if "::" in entry else f"--ignore={entry}")
    return args


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in SUITES:
        print(f"usage: {pathlib.Path(__file__).name} {{{'|'.join(SUITES)}}} [pytest args...]", file=sys.stderr)
        return 2
    suite, extra = argv[0], argv[1:]
    skips = debt_args(suite, DEBT.read_text().splitlines())
    print(f"{suite}: {len(skips)} upstream debt entries skipped ({DEBT.relative_to(ROOT)})", flush=True)
    cmd = [sys.executable, "-m", "pytest", "tests/unit", "-q", "-rfE", "--color=no", "-p", "no:cacheprovider",
           *skips, *extra]
    return subprocess.run(cmd, cwd=ROOT / suite).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
