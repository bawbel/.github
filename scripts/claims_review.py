#!/usr/bin/env python3
"""Build the body of the monthly "Claims review YYYY-MM" issue from claims/STATUS.md.

The review workflow runs scripts/verify_claims.py, then this script, then opens the issue.
The issue changes nothing. It lists every FAIL claim and every UNVERIFIED claim by id so that
none stays unverified in silence, and a person closes each by fixing the surface or the
register (docs/CLAIMS.md).

No network and no clock: the month is an argument, so the same file gives the same body.
Exit 0 on success, 2 when an input cannot be read or is not a claims status file.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "claims" / "STATUS.md"
TITLE = "Claims review {month}"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ROW_RE = re.compile(r"^\|\s*(C-\d+)\s*\|\s*(.*?)\s*\|\s*\*\*(PASS|FAIL|UNVERIFIED)\*\*\s*\|", re.M)
# GitHub rejects an issue body over 65536 characters. Stay clear of it.
MAX_BODY = 60000

INTRO = (
    "Opened by `.github/workflows/claims-review.yml` from the last run of "
    "`scripts/verify_claims.py`. This issue changes nothing. A person closes each failing "
    "claim by fixing the surface or the register (`docs/CLAIMS.md`), then closes this issue "
    "when the list is empty."
)


class Row(NamedTuple):
    id: str
    claim: str
    result: str


def title(month: str) -> str:
    if not MONTH_RE.match(month):
        raise ValueError(f"month must look like 2026-10, got {month!r}")
    return TITLE.format(month=month)


def parse_rows(text: str) -> list[Row]:
    """The claim rows of the table in claims/STATUS.md."""
    return [Row(*m.groups()) for m in ROW_RE.finditer(text)]


def _listing(rows: list[Row], result: str) -> str:
    chosen = [r for r in rows if r.result == result]
    heading = f"## {result} ({len(chosen)})"
    if not chosen:
        return f"{heading}\n\nNone.\n"
    return heading + "\n\n" + "\n".join(f"- {r.id}: {r.claim}" for r in chosen) + "\n"


def build_body(status_text: str, month: str) -> str:
    title(month)  # validates the month
    rows = parse_rows(status_text)
    if not rows:
        raise ValueError("no claims found in the status file")
    counts = {r: sum(1 for row in rows if row.result == r) for r in ("FAIL", "UNVERIFIED", "PASS")}
    head = (
        f"{INTRO}\n\n"
        f"Result: {counts['FAIL']} FAIL, {counts['UNVERIFIED']} UNVERIFIED, {counts['PASS']} PASS\n\n"
        f"{_listing(rows, 'FAIL')}\n{_listing(rows, 'UNVERIFIED')}\n"
    )
    opening = "<details>\n<summary>claims/STATUS.md</summary>\n\n"
    closing = "\n</details>\n"
    room = MAX_BODY - len(head) - len(opening) - len(closing)
    report = status_text
    if len(report) > room:
        note = "\n\n[report cut to fit the issue size limit; the full file is claims/STATUS.md]"
        report = report[: max(room - len(note), 0)] + note
    return head + opening + report + closing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--status", type=Path, default=STATUS)
    parser.add_argument("--month", help="YYYY-MM; default the current month in UTC")
    parser.add_argument("--print-title", action="store_true", help="print the issue title only")
    args = parser.parse_args(argv)
    month = args.month or datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        if args.print_title:
            print(title(month))
            return 0
        sys.stdout.write(build_body(args.status.read_text(encoding="utf-8"), month))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
