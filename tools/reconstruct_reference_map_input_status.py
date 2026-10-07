#!/usr/bin/env python3
"""Reconstruct the legacy input_status schema from immutable native run logs.

The frozen ``rgbd_tum_reference`` entrypoint emits tracking health and a TUM
trajectory but does not emit the historical wrapper's ``input_status.csv``.
This tool makes that gap explicit: it derives a compatibility table from the
association list, health CSV, and trajectory, and writes provenance metadata
stating that the result is reconstructed rather than native logger output.
It does not alter SLAM outputs or infer a pose where no matching native row
exists.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from bisect import bisect_left
from pathlib import Path


HEALTH_COLUMNS = {
    "timestamp_sec",
    "frame_id",
    "tracking_state_code",
    "current_map_id",
    "current_map_points",
    "current_map_keyframes",
    "tracking_processing_time_ms",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def association_rows(path: Path) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(f"association row must have four fields: {line}")
        rgb, depth = float(fields[0]), float(fields[2])
        if rows and rgb <= rows[-1][0]:
            raise ValueError("association RGB timestamps are not increasing")
        rows.append((rgb, depth))
    if not rows:
        raise ValueError("empty association list")
    return rows


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def nearest_index(timestamps: list[float], timestamp: float, tolerance: float) -> int | None:
    index = bisect_left(timestamps, timestamp)
    candidates = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(timestamps)]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda item: (abs(timestamps[item] - timestamp), timestamps[item]))
    return chosen if abs(timestamps[chosen] - timestamp) <= tolerance else None


def read_trajectory(path: Path) -> tuple[list[float], int]:
    timestamps = []
    duplicate_rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise ValueError(f"TUM trajectory row must have eight fields: {line}")
        timestamps.append(float(fields[0]))
    if any(right < left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("trajectory timestamps are decreasing")
    unique = []
    for timestamp in timestamps:
        if unique and timestamp == unique[-1]:
            duplicate_rows += 1
            continue
        unique.append(timestamp)
    return unique, duplicate_rows


def reconstruct(
    associations: Path,
    health_path: Path,
    trajectory: Path,
    output: Path,
    metadata: Path,
    tolerance: float,
) -> None:
    inputs = association_rows(associations)
    health = csv_rows(health_path)
    if not health:
        raise ValueError("empty tracking health")
    if not HEALTH_COLUMNS.issubset(health[0]):
        missing = sorted(HEALTH_COLUMNS.difference(health[0]))
        raise ValueError(f"tracking health missing columns: {missing}")
    health_times = [float(row["timestamp_sec"]) for row in health]
    if any(right <= left for left, right in zip(health_times, health_times[1:])):
        raise ValueError("tracking health timestamps are not increasing")
    trajectory_times, trajectory_duplicate_rows = read_trajectory(trajectory)
    rows = []
    matched_health = 0
    matched_trajectory = 0
    for index, (rgb_timestamp, depth_timestamp) in enumerate(inputs):
        health_index = nearest_index(health_times, rgb_timestamp, tolerance)
        health_row = health[health_index] if health_index is not None else None
        trajectory_index = nearest_index(trajectory_times, rgb_timestamp, tolerance)
        state = int(health_row["tracking_state_code"]) if health_row else -1
        submitted = health_row is not None
        valid_pose = health_row is not None and trajectory_index is not None and state == 2
        matched_health += int(submitted)
        matched_trajectory += int(trajectory_index is not None)
        rows.append(
            {
                "input_index": index,
                "rgb_timestamp": f"{rgb_timestamp:.9f}",
                "depth_timestamp": f"{depth_timestamp:.9f}",
                "image_read_ok": int(submitted),
                "submitted": int(submitted),
                "tracking_state": state,
                "valid_pose": int(valid_pose),
                "map_id": int(health_row["current_map_id"]) if health_row else -1,
                "keyframes": int(health_row["current_map_keyframes"]) if health_row else 0,
                "map_points": int(health_row["current_map_points"]) if health_row else 0,
                "trackrgbd_ms": health_row["tracking_processing_time_ms"] if health_row else "",
                # The frozen native logger has one processing-time field.  The
                # historical wrapper field is retained as an explicit alias.
                "read_and_track_ms": health_row["tracking_processing_time_ms"] if health_row else "",
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata.write_text(
        json.dumps(
            {
                "schema": "reference_map_input_status_reconstruction_v1",
                "native_input_status_present": False,
                "reconstructed_from": ["associations", "tracking_health", "CameraTrajectory"],
                "reconstruction_reason": "frozen rgbd_tum_reference does not emit historical input_status.csv",
                "health_timestamp_tolerance_sec": tolerance,
                "submitted_definition": "a tracking-health row matches the RGB timestamp",
                "valid_pose_definition": "matching tracking-health row has state 2 and a matching TUM trajectory timestamp",
                "image_read_definition": "equal to submitted; this is an inference after native processing completed",
                "read_and_track_ms_definition": "tracking_processing_time_ms copied as a compatibility alias",
                "input_count": len(inputs),
                "health_row_count": len(health),
                "health_matched_count": matched_health,
                "trajectory_matched_count": matched_trajectory,
                "trajectory_duplicate_timestamp_rows_collapsed": trajectory_duplicate_rows,
                "sources": {
                    "associations_sha256": sha256(associations),
                    "tracking_health_sha256": sha256(health_path),
                    "trajectory_sha256": sha256(trajectory),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--associations", type=Path, required=True)
    parser.add_argument("--tracking-health", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-4)
    args = parser.parse_args()
    if args.out.exists() or args.metadata.exists():
        raise SystemExit("fail-if-exists: output or metadata already exists")
    reconstruct(args.associations, args.tracking_health, args.trajectory, args.out, args.metadata, args.tolerance)


if __name__ == "__main__":
    main()
