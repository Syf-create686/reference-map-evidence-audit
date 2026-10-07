#!/usr/bin/env python3
"""Audit the frozen OpenLORIS build/revisit reference-map pilot."""

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

from tools.evidence_contract_v2 import input_rows, join_evidence, parse_log, reference_medians
from tools.evaluate_openloris_trajectory import _pose_matrix, _read_tum, _stats


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nearest(rows: np.ndarray, timestamp: float, tolerance: float, start: int = 0) -> int | None:
    index = bisect_left(rows[:, 0], timestamp, lo=start)
    candidates = [candidate for candidate in (index - 1, index) if start <= candidate < len(rows)]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda candidate: (abs(rows[candidate, 0] - timestamp), rows[candidate, 0]))
    return chosen if abs(rows[chosen, 0] - timestamp) <= tolerance else None


def _remap_native_records(records: list[dict[str, object]], input_count: int) -> list[dict[str, object]]:
    """Map global ORB frame IDs to the adapter's ordered input indices."""
    if len(records) != input_count:
        raise ValueError(f"FRAME marker count {len(records)} != input count {input_count}")
    native_ids = [int(record["frame_id"]) for record in records]
    if any(right != left + 1 for left, right in zip(native_ids, native_ids[1:])):
        raise ValueError("native frame IDs are not consecutive")
    remapped = []
    for input_index, record in enumerate(records):
        item = dict(record)
        item["native_frame_id"] = item["frame_id"]
        item["frame_id"] = input_index
        remapped.append(item)
    return remapped


def _read_status(path: Path, expected_count: int) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != expected_count:
        raise ValueError(f"status rows {len(rows)} != expected {expected_count}")
    result = []
    for index, row in enumerate(rows):
        if int(row["input_index"]) != index:
            raise ValueError("non-consecutive input_status index")
        result.append(
            {
                "image_read_ok": bool(int(row["image_read_ok"])),
                "submitted": bool(int(row["submitted"])),
                "tracking_state_after_submit": int(row["tracking_state"]),
                "valid_pose": bool(int(row["valid_pose"])),
                "map_id": int(row["map_id"]),
                "keyframes": int(row["keyframes"]),
                "map_points": int(row["map_points"]),
                "trackrgbd_ms": float(row["trackrgbd_ms"]),
                "read_and_track_ms": float(row["read_and_track_ms"]),
            }
        )
    return result


def _map_inputs_to_poses(inputs: list[dict[str, object]], poses: np.ndarray, tolerance: float) -> dict[int, int]:
    result: dict[int, int] = {}
    cursor = 0
    for item in inputs:
        match = _nearest(poses, float(item["timestamp_s"]), tolerance, cursor)
        if match is not None:
            result[int(item["frame_id"])] = match
            cursor = match + 1
    return result


def _rotation_error_deg(error_pose: np.ndarray) -> float:
    return float(math.degrees(Rotation.from_matrix(error_pose[:3, :3]).magnitude()))


def _trajectory_errors(
    inputs: list[dict[str, object]],
    estimate: np.ndarray,
    groundtruth: np.ndarray,
    extrinsic: np.ndarray,
    anchor: np.ndarray,
    gt_tolerance: float,
) -> tuple[dict[int, dict[str, float]], dict[str, object]]:
    estimate_for_input = _map_inputs_to_poses(inputs, estimate, 1e-4)
    gt_for_input = _map_inputs_to_poses(inputs, groundtruth, gt_tolerance)
    rows: dict[int, dict[str, float]] = {}
    translation, rotation, rpe_translation, rpe_rotation = [], [], [], []
    previous = None
    for item in inputs:
        frame_id = int(item["frame_id"])
        if frame_id not in estimate_for_input or frame_id not in gt_for_input:
            previous = None
            continue
        estimate_pose = anchor @ _pose_matrix(estimate[estimate_for_input[frame_id]])
        gt_pose = _pose_matrix(groundtruth[gt_for_input[frame_id]]) @ extrinsic
        error_pose = np.linalg.inv(gt_pose) @ estimate_pose
        translation_error = float(np.linalg.norm(gt_pose[:3, 3] - estimate_pose[:3, 3]))
        rotation_error = _rotation_error_deg(error_pose)
        record = {
            "translation_error_m": translation_error,
            "rotation_error_deg_so3": rotation_error,
        }
        translation.append(translation_error)
        rotation.append(rotation_error)
        if previous is not None and frame_id == previous[0] + 1:
            relative_error = (
                np.linalg.inv(np.linalg.inv(previous[1]) @ gt_pose)
                @ (np.linalg.inv(previous[2]) @ estimate_pose)
            )
            record["rpe_1frame_translation_m"] = float(np.linalg.norm(relative_error[:3, 3]))
            record["rpe_1frame_rotation_deg"] = _rotation_error_deg(relative_error)
            rpe_translation.append(record["rpe_1frame_translation_m"])
            rpe_rotation.append(record["rpe_1frame_rotation_deg"])
        previous = (frame_id, gt_pose, estimate_pose)
        rows[frame_id] = record
    summary = {
        "estimate_count": len(estimate),
        "estimate_mapped_to_input": len(estimate_for_input),
        "gt_mapped_to_input": len(gt_for_input),
        "joint_estimate_gt": len(rows),
        "ape_translation_m": _stats(np.asarray(translation)) if translation else None,
        "ape_rotation_deg_so3": _stats(np.asarray(rotation)) if rotation else None,
        "rpe_1frame_translation_m": _stats(np.asarray(rpe_translation)) if rpe_translation else None,
        "rpe_1frame_rotation_deg": _stats(np.asarray(rpe_rotation)) if rpe_rotation else None,
    }
    return rows, summary


def _build_anchor(
    inputs: list[dict[str, object]],
    estimate: np.ndarray,
    groundtruth: np.ndarray,
    extrinsic: np.ndarray,
    gt_tolerance: float,
) -> tuple[np.ndarray, dict[str, object]]:
    estimate_for_input = _map_inputs_to_poses(inputs, estimate, 1e-4)
    gt_for_input = _map_inputs_to_poses(inputs, groundtruth, gt_tolerance)
    common = sorted(set(estimate_for_input) & set(gt_for_input))
    if not common:
        raise ValueError("map-build sequence has no joint estimate/GT pose")
    frame_id = common[0]
    estimate_pose = _pose_matrix(estimate[estimate_for_input[frame_id]])
    gt_pose = _pose_matrix(groundtruth[gt_for_input[frame_id]]) @ extrinsic
    return gt_pose @ np.linalg.inv(estimate_pose), {
        "source_sequence": "office1-1",
        "source_input_index": frame_id,
        "timestamp_s": inputs[frame_id]["timestamp_s"],
        "policy": "one first matched build pose defines T_truthWorld_map; unchanged for revisit",
        "scale_fit": False,
        "revisit_fit": False,
    }


def _build_position_fit_anchor(
    inputs: list[dict[str, object]],
    estimate: np.ndarray,
    groundtruth: np.ndarray,
    extrinsic: np.ndarray,
    gt_tolerance: float,
) -> np.ndarray:
    """Post-hoc diagnostic: unit-scale rigid position fit on map-build data only."""
    estimate_for_input = _map_inputs_to_poses(inputs, estimate, 1e-4)
    gt_for_input = _map_inputs_to_poses(inputs, groundtruth, gt_tolerance)
    common = sorted(set(estimate_for_input) & set(gt_for_input))
    estimated = np.asarray(
        [_pose_matrix(estimate[estimate_for_input[index]])[:3, 3] for index in common]
    )
    truth = np.asarray(
        [(_pose_matrix(groundtruth[gt_for_input[index]]) @ extrinsic)[:3, 3] for index in common]
    )
    estimated_center = estimated.mean(axis=0)
    truth_center = truth.mean(axis=0)
    left, _, right_t = np.linalg.svd(
        (estimated - estimated_center).T @ (truth - truth_center)
    )
    rotation = right_t.T @ left.T
    if np.linalg.det(rotation) < 0:
        right_t[-1] *= -1
        rotation = right_t.T @ left.T
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = truth_center - rotation @ estimated_center
    return transform


def audit(
    results_root: Path,
    association_dir: Path,
    gt_root: Path,
    trajectory_protocol_path: Path,
    pilot_protocol_path: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    trajectory_protocol = json.loads(trajectory_protocol_path.read_text(encoding="utf-8"))
    pilot_protocol = json.loads(pilot_protocol_path.read_text(encoding="utf-8"))
    extrinsic = np.asarray(trajectory_protocol["truth_to_color_extrinsic"]["T_parent_child"], dtype=float)
    tolerance = float(trajectory_protocol["time_tolerance_sec"])
    definitions = [
        ("office1-1", "map_build", "run_build_office1_1"),
        ("office1-3", "revisit_diagnostic", "run_revisit_office1_3"),
    ]
    prepared: dict[str, dict[str, object]] = {}
    for sequence, role, directory in definitions:
        run_root = results_root / directory
        inputs = input_rows(association_dir / f"{sequence}_associations.txt")
        records = _remap_native_records(parse_log(run_root / "native_stdout.log"), len(inputs))
        statuses = _read_status(run_root / "input_status.csv", len(inputs))
        prepared[sequence] = {
            "sequence": sequence,
            "role": role,
            "run_root": run_root,
            "inputs": inputs,
            "records": records,
            "statuses": statuses,
            "estimate": _read_tum(run_root / "map_poses.tum"),
            "groundtruth": _read_tum(gt_root / sequence / "groundtruth.txt"),
        }

    build = prepared["office1-1"]
    anchor, anchor_metadata = _build_anchor(
        build["inputs"], build["estimate"], build["groundtruth"], extrinsic, tolerance
    )
    reference = build["records"]
    all_rows: list[dict[str, object]] = []
    run_summaries = []
    for sequence, _, _ in definitions:
        item = prepared[sequence]
        joined = join_evidence(item["inputs"], item["records"], reference)
        errors, trajectory = _trajectory_errors(
            item["inputs"], item["estimate"], item["groundtruth"], extrinsic, anchor, tolerance
        )
        map_summaries = {
            (row["map_id"], row["keyframes"], row["map_points"])
            for row in item["statuses"]
        }
        state_after_counts: dict[str, int] = {}
        marker_state_counts: dict[str, int] = {}
        for record, status in zip(item["records"], item["statuses"]):
            state_after_counts[str(status["tracking_state_after_submit"])] = (
                state_after_counts.get(str(status["tracking_state_after_submit"]), 0) + 1
            )
            marker_state = str(record.get("tracking_state"))
            marker_state_counts[marker_state] = marker_state_counts.get(marker_state, 0) + 1
        for row, status in zip(joined["rows"], item["statuses"]):
            frame_id = int(row["frame_id"])
            all_rows.append(
                {
                    "sequence": sequence,
                    "role": item["role"],
                    "input_index": frame_id,
                    "native_frame_id": row.get("native_frame_id"),
                    "timestamp_s": row["timestamp_s"],
                    "image_read_ok": status["image_read_ok"],
                    "submitted": status["submitted"],
                    "valid_pose": status["valid_pose"],
                    "tracking_state_after_submit": status["tracking_state_after_submit"],
                    "native_marker_tracking_state": row.get("tracking_state"),
                    "map_id": status["map_id"],
                    "keyframes": status["keyframes"],
                    "map_points": status["map_points"],
                    "association_support": row.get("association_ratio"),
                    "geometric_retention": row.get("geometric_retention_ratio"),
                    "directional_proxy": row.get("directional_geometry_proxy"),
                    "spatial_entropy_proxy": row.get("normalized_entropy"),
                    "grid_occupancy_proxy": row.get("grid_occupancy"),
                    "evidence_available": row["evidence_available"],
                    "strict_joint_candidate": row["strict_joint_candidate"],
                    "candidate_unknown_reason": row["candidate_unknown_reason"],
                    "translation_error_m": errors.get(frame_id, {}).get("translation_error_m"),
                    "rotation_error_deg_so3": errors.get(frame_id, {}).get("rotation_error_deg_so3"),
                    "rpe_1frame_translation_m": errors.get(frame_id, {}).get("rpe_1frame_translation_m"),
                    "rpe_1frame_rotation_deg": errors.get(frame_id, {}).get("rpe_1frame_rotation_deg"),
                    "trackrgbd_ms": status["trackrgbd_ms"],
                    "read_and_track_ms": status["read_and_track_ms"],
                }
            )
        run_root = item["run_root"]
        entrypoint = json.loads((run_root / "entrypoint_evidence.json").read_text(encoding="utf-8"))
        summary = {
            "sequence": sequence,
            "role": item["role"],
            "entrypoint": entrypoint,
            "counts": {
                "input": len(item["inputs"]),
                "image_read_ok": sum(row["image_read_ok"] for row in item["statuses"]),
                "submitted": sum(row["submitted"] for row in item["statuses"]),
                "valid_pose": sum(row["valid_pose"] for row in item["statuses"]),
                "frame_markers": len(item["records"]),
                "complete_evidence": joined["evidence_count"],
                "candidate": joined["candidate_count"],
                "candidate_unknown": joined["candidate_unknown_count"],
                "finite_system_pose_without_complete_map_evidence": sum(
                    status["valid_pose"] and not row["evidence_available"]
                    for row, status in zip(joined["rows"], item["statuses"])
                ),
            },
            "native_frame_id_range": [
                item["records"][0]["native_frame_id"],
                item["records"][-1]["native_frame_id"],
            ],
            "tracking_state_after_submit_counts": state_after_counts,
            "native_marker_tracking_state_counts": marker_state_counts,
            "distinct_map_summaries": [list(value) for value in sorted(map_summaries)],
            "map_stable_for_every_input": len(map_summaries) == 1,
            "trajectory": trajectory,
            "timing_ms": {
                "trackrgbd": _stats(np.asarray([row["trackrgbd_ms"] for row in item["statuses"]])),
                "read_and_track": _stats(np.asarray([row["read_and_track_ms"] for row in item["statuses"]])),
            },
            "sources": {
                name: _sha256(run_root / name)
                for name in (
                    "entrypoint_evidence.json",
                    "input_status.csv",
                    "map_poses.tum",
                    "generated_settings.yaml",
                    "native_stdout.log",
                    "native_stderr.log",
                )
            },
        }
        run_summaries.append(summary)

    revisit_summary = next(item for item in run_summaries if item["role"] == "revisit_diagnostic")
    build_summary = next(item for item in run_summaries if item["role"] == "map_build")
    atlas_before = (results_root / "run_revisit_office1_3/atlas_before.sha256").read_text().split()[0]
    atlas_after = (results_root / "run_revisit_office1_3/atlas_after.sha256").read_text().split()[0]
    build_gate = (
        build_summary["entrypoint"]["returncode"] == 0
        and build_summary["counts"]["submitted"] == 809
        and build_summary["entrypoint"]["keyframes"] > 0
    )
    revisit_gate = (
        revisit_summary["entrypoint"]["returncode"] == 0
        and revisit_summary["counts"]["submitted"] == 360
        and revisit_summary["map_stable_for_every_input"]
        and atlas_before == atlas_after
    )
    revisit_coverage = revisit_summary["counts"]["complete_evidence"] / revisit_summary["counts"]["input"]
    method_coverage_gate = revisit_summary["counts"]["complete_evidence"] == revisit_summary["counts"]["input"]
    fitted_anchor = _build_position_fit_anchor(
        build["inputs"], build["estimate"], build["groundtruth"], extrinsic, tolerance
    )
    alignment_sensitivity = {}
    for sequence, _, _ in definitions:
        item = prepared[sequence]
        _, sensitivity_summary = _trajectory_errors(
            item["inputs"], item["estimate"], item["groundtruth"],
            extrinsic, fitted_anchor, tolerance
        )
        alignment_sensitivity[sequence] = sensitivity_summary
    status = (
        "PARTIAL_REFERENCE_MAP_FEASIBILITY_VO_FALLBACK"
        if build_gate and revisit_gate and not method_coverage_gate
        else "PASS_REFERENCE_MAP_FEASIBILITY"
        if build_gate and revisit_gate and method_coverage_gate
        else "FAIL_REFERENCE_MAP_FEASIBILITY"
    )
    result = {
        "schema": "post_v1_6_openloris_reference_map_pilot_audit_v1",
        "status": status,
        "scientific_role": "DEVELOPMENT_FEASIBILITY_ONLY_NOT_INDEPENDENT_VALIDATION",
        "groundtruth_used_online": False,
        "pilot_protocol": {
            "path": str(pilot_protocol_path),
            "sha256": _sha256(pilot_protocol_path),
            "frozen_status": pilot_protocol["status"],
        },
        "trajectory_protocol": {
            "path": str(trajectory_protocol_path),
            "sha256": _sha256(trajectory_protocol_path),
            "truth_pose_convention": trajectory_protocol["truth_pose_convention"],
            "estimate_pose_convention": trajectory_protocol["estimate_pose_convention"],
            "time_tolerance_sec": tolerance,
        },
        "alignment": anchor_metadata,
        "alignment_sensitivity_post_hoc": {
            "status": "DIAGNOSTIC_ONLY_NOT_PRIMARY_AND_NOT_PREREGISTERED",
            "policy": "unit-scale rigid position fit on office1-1 build poses only; unchanged for office1-3 revisit",
            "purpose": "separate first-pose anchor sensitivity from residual trajectory and orientation error",
            "runs": alignment_sensitivity,
        },
        "reference_evidence_medians": reference_medians(reference),
        "atlas": {
            "sha256_before_revisit": atlas_before,
            "sha256_after_revisit": atlas_after,
            "unchanged": atlas_before == atlas_after,
            "size_bytes": (results_root / "run_build_office1_1/T0_reference.osa").stat().st_size,
        },
        "gates": {
            "frozen_protocol_map_build": build_gate,
            "frozen_protocol_revisit": revisit_gate,
            "complete_method_evidence_on_every_revisit_input": method_coverage_gate,
            "paper_scientific_admission": False,
        },
        "reference_map_support_audit": {
            "revisit_complete_evidence_coverage": revisit_coverage,
            "complete_evidence_frames": revisit_summary["counts"]["complete_evidence"],
            "system_finite_pose_frames": revisit_summary["counts"]["valid_pose"],
            "finite_system_pose_without_complete_map_evidence": revisit_summary["counts"]["finite_system_pose_without_complete_map_evidence"],
            "first_input_without_complete_evidence": next(
                int(row["input_index"])
                for row in all_rows
                if row["sequence"] == "office1-3" and not row["evidence_available"]
            ),
            "implementation_interpretation": "In ORB-SLAM3 localization mode, mbVO permits a motion-model visual-odometry pose when relocalization fails. TrackLocalMap is skipped while mbVO is true; the native evidence markers are emitted inside TrackLocalMap. A finite pose and state OK therefore do not by themselves prove current-frame reference-map support.",
            "required_fix_before_larger_run": "Record tracking-health local_map_inliers/map associations for every input and report map-supported pose coverage separately from finite system-pose coverage.",
        },
        "runs": run_summaries,
        "row_count": len(all_rows),
        "interpretation_boundaries": [
            "The same build-derived SE(3) anchor is applied unchanged to the revisit; the revisit is not independently aligned.",
            "Frames are repeated observations within two acquisitions and are not independent replicates.",
            "Incomplete evidence is UNKNOWN and is not counted as a negative candidate.",
            "A finite pose returned during localization-only operation can be VO fallback without current-frame reference-map support.",
            "This already-seen same-scene pilot verifies system identity and feasibility only.",
        ],
    }
    return result, all_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--association-dir", type=Path, required=True)
    parser.add_argument("--gt-root", type=Path, required=True)
    parser.add_argument("--trajectory-protocol", type=Path, required=True)
    parser.add_argument("--pilot-protocol", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()
    if args.output_json.exists() or args.output_csv.exists():
        raise SystemExit("fail-if-exists: output")
    result, rows = audit(
        args.results_root,
        args.association_dir,
        args.gt_root,
        args.trajectory_protocol,
        args.pilot_protocol,
    )
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with args.output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"status": result["status"], "rows": len(rows)}))


if __name__ == "__main__":
    main()
