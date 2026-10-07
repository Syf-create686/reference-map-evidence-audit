#!/usr/bin/env python3
"""Evaluate an OpenLORIS RGB-D trajectory with a fixed extrinsic and first-pose anchor."""

from __future__ import annotations

import argparse
import json
import math
from bisect import bisect_left
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def _read_tum(path: Path) -> np.ndarray:
    values = np.loadtxt(str(path), ndmin=2)
    if values.shape[1] != 8 or not np.isfinite(values).all():
        raise ValueError(f"invalid TUM trajectory: {path}")
    if len(values) < 1 or not np.all(np.diff(values[:, 0]) > 0.0):
        raise ValueError(f"non-increasing TUM timestamps: {path}")
    norms = np.linalg.norm(values[:, 4:8], axis=1)
    if not np.all(np.abs(norms - 1.0) < 1e-3):
        raise ValueError(f"non-unit TUM quaternions: {path}")
    return values


def _pose_matrix(row: np.ndarray) -> np.ndarray:
    pose = np.eye(4)
    pose[:3, :3] = Rotation.from_quat(row[4:8]).as_matrix()
    pose[:3, 3] = row[1:4]
    return pose


def _stats(values: np.ndarray) -> dict[str, float | int]:
    return {
        "count": int(len(values)),
        "rmse": float(np.sqrt(np.mean(values * values))),
        "median": float(np.median(values)),
        "max": float(np.max(values)),
    }


def _associate(gt: np.ndarray, estimate: np.ndarray, tolerance: float) -> list[tuple[int, int]]:
    result = []
    last_gt = -1
    for estimate_index, timestamp in enumerate(estimate[:, 0]):
        index = bisect_left(gt[:, 0], timestamp)
        candidates = [candidate for candidate in (index - 1, index) if candidate > last_gt and candidate < len(gt)]
        if not candidates:
            continue
        gt_index = min(candidates, key=lambda candidate: (abs(gt[candidate, 0] - timestamp), gt[candidate, 0]))
        if abs(gt[gt_index, 0] - timestamp) <= tolerance:
            result.append((gt_index, estimate_index))
            last_gt = gt_index
    return result


def evaluate(gt_path: Path, estimate_path: Path, protocol_path: Path) -> dict[str, object]:
    gt = _read_tum(gt_path)
    estimate = _read_tum(estimate_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    extrinsic = np.asarray(protocol["truth_to_color_extrinsic"]["T_parent_child"], dtype=float)
    if extrinsic.shape != (4, 4) or not np.allclose(extrinsic[3], [0.0, 0.0, 0.0, 1.0]):
        raise ValueError("invalid base-to-color extrinsic")
    matches = _associate(gt, estimate, float(protocol["time_tolerance_sec"]))
    if not matches:
        return {"status": "NO_MATCHES", "matched": 0}
    gt_poses = [_pose_matrix(gt[gt_index]) @ extrinsic for gt_index, _ in matches]
    estimate_poses = [_pose_matrix(estimate[estimate_index]) for _, estimate_index in matches]
    anchor = gt_poses[0] @ np.linalg.inv(estimate_poses[0])
    aligned_estimate = [anchor @ pose for pose in estimate_poses]
    translation_errors = np.asarray(
        [np.linalg.norm(gt_pose[:3, 3] - estimate_pose[:3, 3]) for gt_pose, estimate_pose in zip(gt_poses, aligned_estimate)]
    )
    yaw_errors = []
    for gt_pose, estimate_pose in zip(gt_poses, aligned_estimate):
        gt_yaw = math.atan2(gt_pose[1, 0], gt_pose[0, 0])
        estimate_yaw = math.atan2(estimate_pose[1, 0], estimate_pose[0, 0])
        delta = (estimate_yaw - gt_yaw + math.pi) % (2.0 * math.pi) - math.pi
        yaw_errors.append(abs(math.degrees(delta)))
    yaw_errors_array = np.asarray(yaw_errors)
    translation_threshold = float(protocol["translation_threshold_m"])
    yaw_threshold = float(protocol["yaw_threshold_deg"])
    return {
        "status": "EVALUATED_FIXED_EXTRINSIC_FIRST_POSE_ANCHOR",
        "matched": len(matches),
        "estimate_count": len(estimate),
        "groundtruth_count": len(gt),
        "time_delta_s": _stats(np.asarray([abs(gt[gt_index, 0] - estimate[estimate_index, 0]) for gt_index, estimate_index in matches])),
        "translation_m": _stats(translation_errors),
        "yaw_deg": _stats(yaw_errors_array),
        "success_rate_translation_and_yaw": float(
            np.mean((translation_errors <= translation_threshold) & (yaw_errors_array <= yaw_threshold))
        ),
        "alignment": protocol["alignment"],
        "scale_fit": protocol["scale_fit"],
        "truth_used_online": protocol["truth_used_online"],
        "thresholds": {"translation_m": translation_threshold, "yaw_deg": yaw_threshold},
        "groundtruth_path": str(gt_path),
        "estimate_path": str(estimate_path),
        "protocol_path": str(protocol_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groundtruth", type=Path, required=True)
    parser.add_argument("--estimate", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"fail-if-exists: {args.out}")
    result = evaluate(args.groundtruth, args.estimate, args.protocol)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
