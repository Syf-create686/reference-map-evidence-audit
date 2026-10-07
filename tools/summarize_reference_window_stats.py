#!/usr/bin/env python3
"""Summarize native s/g/d evidence in frozen reference-map run logs.

The input is a set of ``name=path`` native stdout logs.  The parser accepts the
frozen E0 marker split (FRAME + NATIVE_EVIDENCE + DIRECTIONAL_PROXY) and keeps
incomplete rows out of the three-axis summary while reporting their denominator.
This is descriptive reanalysis; it does not select a threshold or a window.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FRAME = re.compile(
    r"M2_DIAG_FRAME frame_id=(?P<id>\d+) state=(?P<state>\d+) "
    r"extracted_features=(?P<features>\d+) map_associations=(?P<frame_assoc>\d+)"
)
EVIDENCE = re.compile(
    r"M2_DIAG_NATIVE_EVIDENCE frame_id=(?P<id>\d+) "
    r"map_associations=(?P<associations>\d+) geometric_inliers=(?P<inliers>\d+)"
)
PROXY = re.compile(
    r"M2_DIAG_DIRECTIONAL_PROXY frame_id=(?P<id>\d+) valid_points=(?P<points>\d+) "
    r"median_depth=(?P<depth>[-+0-9.eE]+) rotation_singular_min=(?P<min>[-+0-9.eE]+) "
    r"rotation_singular_max=(?P<max>[-+0-9.eE]+) ratio=(?P<ratio>[-+0-9.eE]+)"
)


def _quantile(values: list[float], probability: float) -> float:
    index = (len(values) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def _summary(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": _quantile(ordered, 0.5),
        "q1": _quantile(ordered, 0.25),
        "q3": _quantile(ordered, 0.75),
        "min": ordered[0],
        "max": ordered[-1],
    }


def summarize_log(path: Path) -> dict[str, Any]:
    records: dict[int, dict[str, float | int]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = FRAME.search(line)
        if match:
            values = match.groupdict()
            records.setdefault(int(values["id"]), {}).update(
                features=int(values["features"]),
                state=int(values["state"]),
            )
        match = EVIDENCE.search(line)
        if match:
            values = match.groupdict()
            records.setdefault(int(values["id"]), {}).update(
                associations=int(values["associations"]),
                inliers=int(values["inliers"]),
            )
        match = PROXY.search(line)
        if match:
            values = match.groupdict()
            records.setdefault(int(values["id"]), {}).update(d=float(values["ratio"]))

    complete: list[dict[str, float | int]] = []
    for record in records.values():
        if (
            record.get("features", 0) > 0
            and record.get("associations", 0) > 0
            and "inliers" in record
            and "d" in record
        ):
            record["s"] = float(record["associations"]) / float(record["features"])
            record["g"] = float(record["inliers"]) / float(record["associations"])
            complete.append(record)

    return {
        "source_log": str(path),
        "frame_rows": len(records),
        "complete_rows": len(complete),
        "missing_axis_rows": len(records) - len(complete),
        "stats": {axis: _summary([float(row[axis]) for row in complete]) for axis in ("s", "g", "d")},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True, metavar="NAME=LOG")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"fail-if-exists: {args.out}")
    result: dict[str, Any] = {}
    for item in args.run:
        if "=" not in item:
            raise SystemExit(f"expected NAME=LOG: {item}")
        name, raw_path = item.split("=", 1)
        path = Path(raw_path)
        if not path.is_file():
            raise SystemExit(f"missing log: {path}")
        result[name] = summarize_log(path)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
