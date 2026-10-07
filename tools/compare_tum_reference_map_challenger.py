#!/usr/bin/env python3
"""Run a descriptive, same-input challenger comparison on a TUM reference-map pair.

This tool deliberately reports group-level evidence and external trajectory endpoints.
It does not select a threshold, fit a model, or produce detector metrics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from bisect import bisect_left
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
from scipy.stats import spearmanr

from tools.evidence_contract_v2 import AXES, input_rows, join_evidence, parse_log, reference_medians
from tools.audit_openloris_reference_map_pilot import _pose_matrix, _remap_native_records, _read_tum


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def nearest_index(values: np.ndarray, timestamp: float, tolerance: float) -> int | None:
    index = bisect_left(values[:, 0], timestamp)
    candidates = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(values)]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda candidate: (abs(values[candidate, 0] - timestamp), values[candidate, 0]))
    return chosen if abs(values[chosen, 0] - timestamp) <= tolerance else None


def stats(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    array = np.asarray(values, dtype=float)
    return {
        "count": int(len(array)),
        "median": float(np.median(array)),
        "rmse": float(np.sqrt(np.mean(array * array))),
        "max": float(np.max(array)),
    }


def rho(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(set(left)) < 2 or len(set(right)) < 2:
        return None
    value = float(spearmanr(left, right).statistic)
    return value if math.isfinite(value) else None


def read_support(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["input_index"]): str(row["support_state"]) for row in payload["rows"]}


def frame_errors(
    inputs: list[dict[str, object]],
    estimate_path: Path,
    groundtruth_path: Path,
    anchor: np.ndarray | None,
    tolerance: float,
) -> tuple[dict[int, dict[str, float]], np.ndarray]:
    estimate = _read_tum(estimate_path)
    groundtruth = _read_tum(groundtruth_path)
    estimate_indices = {index: nearest_index(estimate, float(item["timestamp_s"]), 1e-4)
                        for index, item in enumerate(inputs)}
    gt_indices = {index: nearest_index(groundtruth, float(item["timestamp_s"]), tolerance)
                  for index, item in enumerate(inputs)}
    if anchor is None:
        common = [index for index in range(len(inputs)) if estimate_indices[index] is not None and gt_indices[index] is not None]
        if not common:
            raise ValueError("no build frame has both estimate and ground truth")
        estimate_pose = _pose_matrix(estimate[estimate_indices[common[0]]])
        gt_pose = _pose_matrix(groundtruth[gt_indices[common[0]]])
        anchor = gt_pose @ np.linalg.inv(estimate_pose)
    rows: dict[int, dict[str, float]] = {}
    previous: tuple[int, np.ndarray, np.ndarray] | None = None
    for index, item in enumerate(inputs):
        estimate_index = estimate_indices[index]
        gt_index = gt_indices[index]
        if estimate_index is None or gt_index is None:
            previous = None
            continue
        estimate_pose = anchor @ _pose_matrix(estimate[estimate_index])
        gt_pose = _pose_matrix(groundtruth[gt_index])
        error_pose = np.linalg.inv(gt_pose) @ estimate_pose
        record = {
            "translation_error_m": float(np.linalg.norm(gt_pose[:3, 3] - estimate_pose[:3, 3])),
            "yaw_error_deg": abs(float(math.degrees(math.atan2(error_pose[1, 0], error_pose[0, 0])))),
        }
        if previous is not None and index == previous[0] + 1:
            relative_error = np.linalg.inv(np.linalg.inv(previous[1]) @ gt_pose) @ (
                np.linalg.inv(previous[2]) @ estimate_pose
            )
            record["rpe_translation_m"] = float(np.linalg.norm(relative_error[:3, 3]))
            record["rpe_yaw_deg"] = abs(float(math.degrees(math.atan2(relative_error[1, 0], relative_error[0, 0]))))
        previous = (index, gt_pose, estimate_pose)
        rows[index] = record
    return rows, anchor


def axis_values(row: dict[str, object], medians: dict[str, float | None]) -> dict[str, float | None]:
    result = {}
    for axis in AXES:
        value = row.get(axis)
        median_value = medians.get(axis)
        result[axis] = (float(value) / float(median_value)
                        if isinstance(value, (int, float)) and math.isfinite(float(value))
                        and isinstance(median_value, (int, float)) and median_value > 0 else None)
    return result


def compare_group(
    name: str,
    association_path: Path,
    log_path: Path,
    support_path: Path,
    trajectory_path: Path,
    groundtruth_path: Path,
    medians: dict[str, float | None],
    anchor: np.ndarray | None,
    tolerance: float,
) -> tuple[dict[str, object], np.ndarray]:
    inputs = input_rows(association_path)
    records = _remap_native_records(parse_log(log_path), len(inputs))
    joined = join_evidence(inputs, records, references=None, threshold=0.8, confirm=3)
    support = read_support(support_path)
    errors, anchor = frame_errors(inputs, trajectory_path, groundtruth_path, anchor, tolerance)
    feature_names = [
        "support_only", "geometry_only", "direction_only",
        "support_geometry", "support_direction", "geometry_direction",
        "full_three_axis", "scalar_three_axis_mean", "spatial_entropy",
    ]
    rows = []
    for row in joined["rows"]:
        index = int(row["frame_id"])
        relative = axis_values(row, medians)
        complete = all(value is not None for value in relative.values())
        features: dict[str, float | None] = {
            "support_only": relative[AXES[0]],
            "geometry_only": relative[AXES[1]],
            "direction_only": relative[AXES[2]],
            "support_geometry": (relative[AXES[0]] + relative[AXES[1]]) / 2 if complete else None,
            "support_direction": (relative[AXES[0]] + relative[AXES[2]]) / 2 if complete else None,
            "geometry_direction": (relative[AXES[1]] + relative[AXES[2]]) / 2 if complete else None,
            "full_three_axis": min(relative.values()) if complete else None,
            "scalar_three_axis_mean": sum(relative.values()) / 3 if complete else None,
            "spatial_entropy": row.get("normalized_entropy"),
        }
        rows.append({
            "input_index": index,
            "support_state": support.get(index, "UNKNOWN"),
            "evidence_available": bool(row["evidence_available"]),
            "features": features,
            "errors": errors.get(index),
        })
    comparisons: dict[str, object] = {}
    for feature in feature_names:
        eligible = [row for row in rows if row["support_state"] == "MAP_SUPPORTED"
                    and row["errors"] is not None and row["features"][feature] is not None]
        result = {
            "map_supported_count": sum(row["support_state"] == "MAP_SUPPORTED" for row in rows),
            "feature_available_count": len(eligible),
            "coverage_over_input": len(eligible) / len(rows),
            "outcomes": {},
        }
        for outcome in ("translation_error_m", "yaw_error_deg", "rpe_translation_m", "rpe_yaw_deg"):
            common = [row for row in eligible if outcome in row["errors"]]
            result["outcomes"][outcome] = {
                "count": len(common),
                "spearman_rho": rho([float(row["features"][feature]) for row in common],
                                     [float(row["errors"][outcome]) for row in common]),
                "median": stats([float(row["errors"][outcome]) for row in common]),
            }
        comparisons[feature] = result
    return {
        "group": name,
        "input_count": len(rows),
        "support_state_counts": {state: sum(row["support_state"] == state for row in rows)
                                  for state in ("MAP_SUPPORTED", "VO_FALLBACK", "INVALID_OR_LOST", "UNKNOWN")},
        "complete_evidence_count": sum(row["evidence_available"] for row in rows),
        "comparisons": comparisons,
        "no_detector_metrics": True,
        "rows": rows,
    }, anchor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-association", type=Path, required=True)
    parser.add_argument("--revisit-association", type=Path, required=True)
    parser.add_argument("--build-log", type=Path, required=True)
    parser.add_argument("--revisit-log", type=Path, required=True)
    parser.add_argument("--build-support", type=Path, required=True)
    parser.add_argument("--revisit-support", type=Path, required=True)
    parser.add_argument("--build-trajectory", type=Path, required=True)
    parser.add_argument("--revisit-trajectory", type=Path, required=True)
    parser.add_argument("--groundtruth", type=Path, required=True)
    parser.add_argument(
        "--revisit-groundtruth",
        type=Path,
        help="Optional separate GT stream for a revisit acquisition; defaults to --groundtruth for same-sequence TUM windows.",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"fail-if-exists: {args.out}")
    build_inputs = input_rows(args.build_association)
    build_records = _remap_native_records(parse_log(args.build_log), len(build_inputs))
    medians = reference_medians(build_records)
    groups = []
    build_result, anchor = compare_group(
        "window0_build", args.build_association, args.build_log, args.build_support,
        args.build_trajectory, args.groundtruth, medians, None, 0.02
    )
    revisit_result, _ = compare_group(
        "window1_revisit", args.revisit_association, args.revisit_log, args.revisit_support,
        args.revisit_trajectory, args.revisit_groundtruth or args.groundtruth, medians, anchor, 0.02
    )
    groups.extend((build_result, revisit_result))
    result = {
        "schema": "tum_reference_map_challenger_comparison_v1",
        "status": "PASS_DESCRIPTIVE_GROUP_COMPARISON",
        "threshold_identity": {"tau": 0.8, "role": "exploratory_relative_display_only"},
        "reference_medians": medians,
        "groups": groups,
        "interpretation": {
            "frames_are_repeated_observations": True,
            "independent_sequence_groups": 1,
            "no_p_values": True,
            "no_winner_selected": True,
            "formal_detector_metrics": False,
            "external_challenger": "spatial_entropy_proxy_logged by the same native run",
            "claim_boundary": "descriptive same-input contrast only; no superiority or generalization",
        },
        "sources": {name: sha256(path) for name, path in {
            "build_association": args.build_association, "revisit_association": args.revisit_association,
            "build_log": args.build_log, "revisit_log": args.revisit_log,
            "build_support": args.build_support, "revisit_support": args.revisit_support,
            "build_trajectory": args.build_trajectory, "revisit_trajectory": args.revisit_trajectory,
            "groundtruth": args.groundtruth,
            "revisit_groundtruth": args.revisit_groundtruth or args.groundtruth,
        }.items()},
    }
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
