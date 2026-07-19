#!/usr/bin/env python3
"""Run the complete trusted repository quality gate."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Check:
    """One fixed repository quality check."""

    name: str
    argv: tuple[str, ...]


CHECKS: Final = (
    Check("lock", ("uv", "lock", "--check")),
    Check("lint", ("uv", "run", "--frozen", "ruff", "check", ".")),
    Check("format", ("uv", "run", "--frozen", "ruff", "format", "--check", ".")),
    Check("typing", ("uv", "run", "--frozen", "pyright")),
    Check("tests", ("uv", "run", "--frozen", "pytest")),
    Check("security", ("uv", "run", "--frozen", "bandit", "-q", "-r", "src", "-ll")),
    Check(
        "dependencies",
        (
            "uv",
            "run",
            "--frozen",
            "pip-audit",
            "--cache-dir",
            "build/pip-audit-cache",
        ),
    ),
    Check(
        "architecture",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "tests/test_architecture.py",
        ),
    ),
)


def _parse_checks() -> tuple[str, ...]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="append",
        choices=tuple(check.name for check in CHECKS),
        help="Run only the named check; repeat to select multiple checks.",
    )
    checks = cast(list[str] | None, parser.parse_args().check)
    return tuple(checks or ())


def _resolve_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    executable = shutil.which(argv[0])
    if executable is None:
        raise RuntimeError(f"required executable is unavailable: {argv[0]}")
    return (executable, *argv[1:])


def main() -> int:
    """Run selected checks and return a process-style status code."""
    selected = set(_parse_checks())
    checks = tuple(check for check in CHECKS if not selected or check.name in selected)
    failures: list[str] = []

    for check in checks:
        print(f"==> {check.name}", flush=True)
        try:
            argv = _resolve_argv(check.argv)
        except RuntimeError as error:
            print(f"FAIL {check.name}: {error}", flush=True)
            failures.append(check.name)
            continue

        completed = subprocess.run(argv, cwd=ROOT, check=False)
        if completed.returncode != 0:
            print(f"FAIL {check.name}: exit {completed.returncode}", flush=True)
            failures.append(check.name)

    if failures:
        print(f"Quality gate failed: {', '.join(failures)}", flush=True)
        return 1

    print("Quality gate passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
