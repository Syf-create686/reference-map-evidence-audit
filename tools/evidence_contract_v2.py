"""Versioned offline evidence contract; historical V1 parsers remain unchanged."""
from __future__ import annotations

import math
import re
from pathlib import Path
from statistics import median

from tools import parse_m2_directional_proxy_log as legacy

AXES = ("association_ratio", "geometric_retention_ratio", "directional_geometry_proxy")
SPATIAL = re.compile(
    r"M2_DIAG_NATIVE_SPATIAL frame_id=(?P<frame_id>\d+) "
    r"valid_points=(?P<points>\d+) occupied_cells=(?P<cells>\d+) "
    r"normalized_entropy=(?P<entropy>[-+0-9.eE]+|nan)"
)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_axis(value):
    return finite(value) and 0 <= value <= 1


def parse_log(path: Path):
    """Reject duplicate markers/reset identities instead of silently overwriting."""
    seen = set()
    frame_ids = []
    spatial = {}
    patterns = (legacy.FRAME, legacy.NATIVE, legacy.OLD_PROXY, legacy.NEW_PROXY, SPATIAL)
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        for kind, pattern in enumerate(patterns):
            match = pattern.search(line)
            if match is None:
                continue
            fid = int(match["frame_id"])
            if (kind, fid) in seen:
                raise ValueError(f"duplicate marker kind={kind}, frame_id={fid}")
            seen.add((kind, fid))
            if kind == 0:
                frame_ids.append(fid)
            if kind == 4:
                h = float(match["entropy"])
                cells, points = int(match["cells"]), int(match["points"])
                spatial[fid] = {
                    "spatial_valid_points": points,
                    "occupied_cells": cells,
                    "grid_occupancy": cells / 12 if points > 0 and 0 <= cells <= 12 else None,
                    "normalized_entropy": h if points > 0 and valid_axis(h) else None,
                }
            break
    if any(b <= a for a, b in zip(frame_ids, frame_ids[1:])):
        raise ValueError("non-increasing FRAME markers: separate run/reset identity required")
    result = legacy.parse_log(path)
    for record in result:
        reasons = []
        fid = record["frame_id"]
        record["frame_marker_available"] = (0, fid) in seen
        for axis in AXES:
            if not valid_axis(record.get(axis)):
                record[axis] = None
                reasons.append(f"{axis}:missing_or_invalid")
        points = record.get("directional_geometry_proxy_valid_points")
        depth = record.get("directional_geometry_proxy_median_depth_m")
        low = record.get("directional_geometry_proxy_rotation_singular_min")
        high = record.get("directional_geometry_proxy_rotation_singular_max")
        if not (isinstance(points, int) and points >= 6 and finite(depth) and depth > 0
                and finite(low) and finite(high) and 0 <= low <= high and high > 0):
            record[AXES[2]] = None
            reasons.append("directional_proxy:invalid_geometry_metadata")
        elif record[AXES[2]] is not None and not math.isclose(record[AXES[2]], low / high, abs_tol=1e-6, rel_tol=1e-5):
            record[AXES[2]] = None
            reasons.append("directional_proxy:ratio_eigenvalue_mismatch")
        record.update(spatial.get(fid, {"grid_occupancy": None, "normalized_entropy": None}))
        record["evidence_reasons"] = reasons
    return result


def input_rows(association_path: Path):
    """Frame IDs follow the verified rgbd_tum runner's ordered association loop."""
    rows = []
    for line in association_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("association must contain RGB time/path and depth time/path")
        t, td = float(fields[0]), float(fields[2])
        if not finite(t) or not finite(td) or (rows and t <= rows[-1]["timestamp_s"]):
            raise ValueError("invalid/non-increasing input timestamps")
        rows.append({"frame_id": len(rows), "timestamp_s": t, "depth_timestamp_s": td})
    if not rows:
        raise ValueError("empty input")
    return rows


def reference_medians(records):
    """Keep valid zero evidence; a zero median makes normalization unavailable."""
    result = {}
    for axis in AXES:
        values = [r[axis] for r in records if valid_axis(r.get(axis))]
        result[axis] = median(values) if values else None
    return result


def join_evidence(inputs, records, references=None, threshold=0.8, confirm=3):
    if not finite(threshold) or not 0 < threshold <= 1 or type(confirm) is not int or confirm < 1:
        raise ValueError("invalid candidate parameters")
    ids = [r["frame_id"] for r in inputs]
    if len(set(ids)) != len(ids) or any(b != a + 1 for a, b in zip(ids, ids[1:])):
        raise ValueError("inputs must be a complete consecutive frame-id manifest")
    if any(not finite(r.get("timestamp_s")) for r in inputs) or any(
            b["timestamp_s"] <= a["timestamp_s"] for a, b in zip(inputs, inputs[1:])):
        raise ValueError("input timestamps must be finite and increasing")
    by_id = {r["frame_id"]: r for r in records}
    if len(by_id) != len(records) or set(by_id) - set(ids):
        raise ValueError("duplicate or out-of-manifest evidence frame")
    medians = reference_medians(references) if references is not None else None
    rows, segments = [], []
    start = None
    for index, inp in enumerate(inputs):
        native = by_id.get(inp["frame_id"], {})
        row = {**inp, **native}
        row["evidence_reasons"] = list(native.get("evidence_reasons", []))
        if not native.get("frame_marker_available", False):
            row["evidence_reasons"].append("missing_frame_marker")
        complete = native.get("frame_marker_available", False) and all(valid_axis(native.get(a)) for a in AXES)
        row["evidence_available"] = bool(complete)
        row["native_lost"] = native.get("tracking_state") == 3 if "tracking_state" in native else None
        row["strict_joint_candidate"] = None
        row["relative_evidence"] = None
        if medians is None:
            row["candidate_unknown_reason"] = "reference_not_assigned"
        elif any(not finite(v) or v <= 0 for v in medians.values()):
            row["candidate_unknown_reason"] = "invalid_reference_median"
        elif not complete:
            row["candidate_unknown_reason"] = "incomplete_evidence"
        else:
            relative = {a: native[a] / medians[a] for a in AXES}
            row["relative_evidence"] = relative
            row["strict_joint_candidate"] = sum(x <= threshold for x in relative.values()) >= 2
            row["candidate_unknown_reason"] = None
        candidate = row["strict_joint_candidate"] is True
        if candidate and start is None:
            start = index
        if not candidate and start is not None:
            if index - start >= confirm:
                segments.append({"start_frame_id": ids[start], "end_frame_id": ids[index - 1],
                                 "valid_frame_count": index - start})
            start = None
        rows.append(row)
    if start is not None and len(rows) - start >= confirm:
        segments.append({"start_frame_id": ids[start], "end_frame_id": ids[-1], "valid_frame_count": len(rows) - start})
    return {"rows": rows, "reference_medians": medians, "confirmed_segments": segments,
            "input_count": len(inputs), "evidence_count": sum(r["evidence_available"] for r in rows),
            "candidate_count": sum(r["strict_joint_candidate"] is True for r in rows),
            "candidate_unknown_count": sum(r["strict_joint_candidate"] is None for r in rows)}
