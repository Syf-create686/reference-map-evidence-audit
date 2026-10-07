#!/usr/bin/env python3
"""Classify finite, map-supported, VO-fallback, and unknown pose populations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from tools.evidence_contract_v2 import input_rows


EXPECTED_HEALTH_COLUMNS = {
    "timestamp_sec",
    "frame_id",
    "tracking_state_code",
    "current_map_id",
    "map_point_associations",
    "valid_tracked_map_points",
    "local_map_inliers",
    "current_map_points",
    "current_map_keyframes",
    "last_relocalization_frame_id",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader)


def _health_by_input(
    inputs: list[dict[str, object]],
    health: list[dict[str, str]],
    tolerance: float,
) -> dict[int, dict[str, str]]:
    if health and not EXPECTED_HEALTH_COLUMNS.issubset(health[0]):
        raise ValueError("tracking-health schema missing required columns")
    result: dict[int, dict[str, str]] = {}
    cursor = 0
    for input_row in inputs:
        timestamp = float(input_row["timestamp_s"])
        matches = []
        while cursor < len(health) and float(health[cursor]["timestamp_sec"]) < timestamp - tolerance:
            cursor += 1
        for index in (cursor, cursor + 1):
            if index < len(health) and abs(float(health[index]["timestamp_sec"]) - timestamp) <= tolerance:
                matches.append(index)
        if len(matches) > 1:
            raise ValueError(f"ambiguous tracking-health timestamp near {timestamp}")
        if matches:
            index = matches[0]
            result[int(input_row["frame_id"])] = health[index]
            cursor = index + 1
    return result


def classify(
    associations_path: Path,
    input_status_path: Path,
    tracking_health_path: Path,
    definition_path: Path,
    mode: str,
) -> dict[str, object]:
    if mode not in ("build", "revisit"):
        raise ValueError("mode must be build or revisit")
    definition = json.loads(definition_path.read_text(encoding="utf-8"))
    tolerance = float(definition["join_policy"]["health_timestamp_tolerance_sec"])
    inputs = input_rows(associations_path)
    status = _read_csv(input_status_path)
    if len(status) != len(inputs):
        raise ValueError("input-status row count does not equal complete input count")
    for index, row in enumerate(status):
        if int(row["input_index"]) != index:
            raise ValueError("input-status indices are not complete and consecutive")
        if abs(float(row["rgb_timestamp"]) - float(inputs[index]["timestamp_s"])) > tolerance:
            raise ValueError("input-status timestamp mismatch")
    health = _read_csv(tracking_health_path)
    health_by_input = _health_by_input(inputs, health, tolerance)
    rows = []
    for index, (input_row, status_row) in enumerate(zip(inputs, status)):
        health_row = health_by_input.get(index)
        submitted = status_row["submitted"] == "1"
        finite_pose = status_row["valid_pose"] == "1" and int(status_row["tracking_state"]) == 2
        map_identity_stable = False
        local_map_evaluated = None
        relocalized_this_frame = None
        reasons: list[str] = []
        if health_row is None:
            reasons.append("missing_tracking_health")
        else:
            fields = [
                "frame_id",
                "tracking_state_code",
                "current_map_id",
                "local_map_inliers",
                "current_map_points",
                "current_map_keyframes",
                "last_relocalization_frame_id",
            ]
            try:
                values = {name: int(health_row[name]) for name in fields}
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid integer tracking-health field at input {index}") from error
            local_map_evaluated = values["local_map_inliers"] >= 0
            relocalized_this_frame = values["last_relocalization_frame_id"] == values["frame_id"]
            map_identity_stable = (
                values["current_map_id"] == int(status_row["map_id"])
                and values["current_map_keyframes"] == int(status_row["keyframes"])
                and values["current_map_points"] == int(status_row["map_points"])
            )
            if not map_identity_stable:
                reasons.append("health_status_map_summary_mismatch")
        if not submitted or not finite_pose:
            state = "INVALID_OR_LOST"
        elif health_row is None or not map_identity_stable:
            state = "UNKNOWN"
        elif int(health_row["tracking_state_code"]) != 2:
            state = "INVALID_OR_LOST"
            reasons.append("health_state_not_ok")
        elif local_map_evaluated:
            state = "MAP_SUPPORTED"
        elif mode == "revisit":
            state = "VO_FALLBACK"
        else:
            state = "UNKNOWN"
            reasons.append("build_without_local_map_evaluation")
        rows.append(
            {
                "input_index": index,
                "timestamp_s": input_row["timestamp_s"],
                "native_frame_id": int(health_row["frame_id"]) if health_row else None,
                "submitted": submitted,
                "finite_system_pose": finite_pose,
                "map_identity_stable": map_identity_stable,
                "local_map_evaluated": local_map_evaluated,
                "local_map_inliers": int(health_row["local_map_inliers"]) if health_row else None,
                "valid_tracked_map_points": int(health_row["valid_tracked_map_points"]) if health_row else None,
                "relocalized_this_frame": relocalized_this_frame,
                "support_state": state,
                "reasons": reasons,
            }
        )
    counts = {state: sum(row["support_state"] == state for row in rows) for state in (
        "MAP_SUPPORTED", "VO_FALLBACK", "INVALID_OR_LOST", "UNKNOWN"
    )}
    finite_count = sum(row["finite_system_pose"] for row in rows)
    return {
        "schema": "reference_map_pose_support_audit_v1",
        "mode": mode,
        "input_count": len(inputs),
        "tracking_health_row_count": len(health),
        "tracking_health_mapped_count": len(health_by_input),
        "finite_system_pose_count": finite_count,
        "support_state_counts": counts,
        "map_supported_over_input": counts["MAP_SUPPORTED"] / len(inputs),
        "map_supported_over_finite_pose": counts["MAP_SUPPORTED"] / finite_count if finite_count else None,
        "sources": {
            "associations_sha256": _sha256(associations_path),
            "input_status_sha256": _sha256(input_status_path),
            "tracking_health_sha256": _sha256(tracking_health_path),
            "definition_sha256": _sha256(definition_path),
        },
        "rows": rows,
        "groundtruth_used": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--associations", type=Path, required=True)
    parser.add_argument("--input-status", type=Path, required=True)
    parser.add_argument("--tracking-health", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--mode", choices=("build", "revisit"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"fail-if-exists: {args.out}")
    result = classify(
        args.associations,
        args.input_status,
        args.tracking_health,
        args.definition,
        args.mode,
    )
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
