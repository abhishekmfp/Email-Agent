#!/usr/bin/env python
"""Enforce per-layer coverage floors from a coverage.py JSON report.

M8 hardening gate. `pytest --cov --cov-report=json` produces the report; this
script aggregates it by top-level package layer and exits non-zero if any layer
drops below its threshold. Complements `--cov-fail-under=80` (overall) by
locking the per-layer floors required by PLAN.md / DONE.html §2:

    domain      ~100%
    application   >= 90%
    infrastructure >= 80%
    overall       >= 80%

Usage:
    uv run pytest --cov=email_agent --cov-report=json -q
    uv run python scripts/check_coverage.py coverage.json

Exits 0 when all floors are met, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Layer -> minimum coverage percent (0-100). Key matches the second path segment
# of "src/email_agent/<layer>/...". Files outside a known layer (e.g. config/,
# interface/, main.py) are rolled into "overall" only, not a separate floor.
LAYER_FLOORS: dict[str, float] = {
    "domain": 100.0,
    "application": 90.0,
    "infrastructure": 80.0,
}
OVERALL_FLOOR = 80.0


def _layer_of(path: str) -> str | None:
    parts = Path(path).parts
    # Expect: ('src', 'email_agent', <layer>, ...)
    if len(parts) >= 3 and parts[0] == "src" and parts[1] == "email_agent":
        return parts[2]
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_coverage.py <coverage.json>", file=sys.stderr)
        return 2

    report_path = Path(argv[1])
    if not report_path.is_file():
        print(f"coverage report not found: {report_path}", file=sys.stderr)
        return 2

    data = json.loads(report_path.read_text(encoding="utf-8"))
    files = data.get("files", {})

    # Aggregate per layer: weighted by num_statements.
    layer_stmts: dict[str, int] = {}
    layer_cov: dict[str, int] = {}
    total_stmts = 0
    total_cov = 0
    for path, info in files.items():
        summary = info.get("summary", {})
        stmts = summary.get("num_statements", 0)
        covered = summary.get("covered_lines", 0)
        if stmts == 0:
            continue
        total_stmts += stmts
        total_cov += covered
        layer = _layer_of(path)
        if layer in LAYER_FLOORS:
            layer_stmts[layer] = layer_stmts.get(layer, 0) + stmts
            layer_cov[layer] = layer_cov.get(layer, 0) + covered

    failures: list[str] = []

    overall_pct = (total_cov / total_stmts * 100.0) if total_stmts else 100.0
    print(f"overall        : {overall_pct:5.1f}%  (floor {OVERALL_FLOOR:.0f}%)")
    if overall_pct < OVERALL_FLOOR:
        failures.append(f"overall {overall_pct:.1f}% < {OVERALL_FLOOR:.0f}%")

    for layer, floor in LAYER_FLOORS.items():
        stmts = layer_stmts.get(layer, 0)
        if stmts == 0:
            print(f"{layer:<15}:   n/a  (no statements)")
            continue
        pct = layer_cov.get(layer, 0) / stmts * 100.0
        mark = "OK " if pct >= floor else "FAIL"
        print(f"{layer:<15}: {pct:5.1f}%  (floor {floor:.0f}%)  [{mark}]")
        if pct < floor:
            failures.append(f"{layer} {pct:.1f}% < {floor:.0f}%")

    if failures:
        print("\nCOVERAGE FLOOR VIOLATIONS:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll coverage floors met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
