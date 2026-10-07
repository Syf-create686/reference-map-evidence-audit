#!/usr/bin/env python3
"""Unify descriptive challenger comparisons across already-recorded groups.

The tool deliberately accepts only existing audit artifacts.  It computes
same-frame rank associations for the three evidence axes and fixed summaries;
it does not tune thresholds, train a model, or produce detector metrics.
OpenLORIS audit CSVs and the TUM challenger JSON are normalized into one
schema.  A source with no complete s/g/d rows must be reported as excluded,
not imputed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr


AXES = ("support", "geometry", "direction")
FEATURES = (
    "support_only",
    "geometry_only",
    "direction_only",
    "support_geometry",
    "support_direction",
    "geometry_direction",
    "full_three_axis",
    "scalar_three_axis_mean",
    "spatial_entropy",
)
OUTCOME_DEFINITIONS = {
    "translation_error_m": "Source-defined anchored translation-error norm, metres.",
    "yaw_error_deg": "Absolute atan2(R_error[1,0], R_error[0,0]), degrees; not an SO(3) angle.",
    "rotation_error_deg_so3": "Magnitude of the source rotation-error matrix on SO(3), degrees; not yaw.",
    "rpe_translation_m": "Source-defined one-input-step relative translation-error norm, metres.",
    "rpe_yaw_deg": "Absolute atan2(R_relative_error[1,0], R_relative_error[0,0]), degrees; not an SO(3) angle.",
    "rpe_rotation_deg_so3": "Magnitude of the source one-input-step relative rotation-error matrix on SO(3), degrees; not yaw.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def rho(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(set(left)) < 2 or len(set(right)) < 2:
        return None
    value = float(spearmanr(left, right).statistic)
    return value if math.isfinite(value) else None


def median(values: list[float]) -> float | None:
    return float(np.median(np.asarray(values, dtype=float))) if values else None


def build_features(row: dict[str, float | None], reference: dict[str, float]) -> dict[str, float | None]:
    ratios = {
        "support": row["support"] / reference["support"] if row["support"] is not None else None,
        "geometry": row["geometry"] / reference["geometry"] if row["geometry"] is not None else None,
        "direction": row["direction"] / reference["direction"] if row["direction"] is not None else None,
    }
    features: dict[str, float | None] = {
        "support_only": ratios["support"],
        "geometry_only": ratios["geometry"],
        "direction_only": ratios["direction"],
        "support_geometry": None,
        "support_direction": None,
        "geometry_direction": None,
        "full_three_axis": None,
        "scalar_three_axis_mean": None,
        "spatial_entropy": row.get("spatial_entropy"),
    }
    if ratios["support"] is not None and ratios["geometry"] is not None:
        features["support_geometry"] = (ratios["support"] + ratios["geometry"]) / 2.0
    if ratios["support"] is not None and ratios["direction"] is not None:
        features["support_direction"] = (ratios["support"] + ratios["direction"]) / 2.0
    if ratios["geometry"] is not None and ratios["direction"] is not None:
        features["geometry_direction"] = (ratios["geometry"] + ratios["direction"]) / 2.0
    if all(value is not None for value in ratios.values()):
        values = [float(ratios[key]) for key in AXES]
        features["full_three_axis"] = min(values)
        features["scalar_three_axis_mean"] = sum(values) / 3.0
    return features


def reference_medians(rows: list[dict[str, float | None]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for axis in AXES:
        values = [float(row[axis]) for row in rows if row[axis] is not None]
        if not values:
            raise ValueError(f"no reference values for {axis}")
        result[axis] = float(np.median(np.asarray(values, dtype=float)))
        if not math.isfinite(result[axis]) or result[axis] <= 0:
            raise ValueError(f"nonpositive or invalid reference median for {axis}")
    return result


def summarize(rows: list[dict[str, Any]], *, input_count: int | None = None) -> dict[str, Any]:
    denominator = len(rows) if input_count is None else input_count
    if denominator < len(rows):
        raise ValueError("input denominator cannot be smaller than retained rows")
    result: dict[str, Any] = {}
    for feature in FEATURES:
        feature_rows = [row for row in rows if row["features"].get(feature) is not None]
        feature_result: dict[str, Any] = {
            "feature_count": len(feature_rows),
            "feature_over_input": len(feature_rows) / denominator if denominator else None,
            "feature_over_map_supported": len(feature_rows) / len(rows) if rows else None,
            "outcomes": {},
        }
        for outcome in OUTCOME_DEFINITIONS:
            common = [row for row in feature_rows if row.get(outcome) is not None]
            fv = [float(row["features"][feature]) for row in common]
            ov = [float(row[outcome]) for row in common]
            if common:
                order = sorted(range(len(common)), key=lambda index: (fv[index], common[index]["input_index"]))
                q = max(1, math.ceil(len(common) * 0.25))
                weak = [ov[index] for index in order[:q]]
                strong = [ov[index] for index in order[-q:]]
            else:
                q, weak, strong = 0, [], []
            feature_result["outcomes"][outcome] = {
                "count": len(common),
                "spearman_rho": rho(fv, ov),
                "weak_quartile_count": q,
                "weak_median": median(weak),
                "strong_median": median(strong),
                "weak_minus_strong": (median(weak) - median(strong)) if weak and strong else None,
            }
        result[feature] = feature_result
    return result


def load_support_state_audits(paths: list[Path]) -> dict[str, dict[int, str]]:
    """Load frozen support-state rows keyed by the audit mode and input index.

    E1's native evidence CSV predates the support audit and only contains an
    ``evidence_available`` flag.  The dedicated support audits are therefore
    authoritative for distinguishing VO fallback from UNKNOWN.  The audit
    schema uses ``mode=build`` or ``mode=revisit``; this mapping is intentionally
    limited to those two roles and fails closed on duplicate input indices.
    """
    by_mode: dict[str, dict[int, str]] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = str(data.get("mode", "")).strip().lower()
        if mode not in {"build", "revisit"}:
            raise ValueError(f"unsupported support-audit mode in {path}: {mode!r}")
        state_by_index = by_mode.setdefault(mode, {})
        for raw in data.get("rows", []):
            index = int(raw["input_index"])
            state = str(raw["support_state"])
            if index in state_by_index and state_by_index[index] != state:
                raise ValueError(f"duplicate support state for mode={mode} input_index={index}")
            state_by_index[index] = state
    return by_mode


def load_e1(
    path: Path,
    label_prefix: str,
    support_states_by_mode: dict[str, dict[int, str]] | None = None,
) -> list[dict[str, Any]]:
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["sequence"], row["role"])
            mode = "build" if row["role"] == "map_build" else "revisit" if row["role"] == "revisit_diagnostic" else None
            fallback_state = "MAP_SUPPORTED" if row.get("evidence_available") == "True" else "UNKNOWN"
            support_state = (
                support_states_by_mode.get(mode, {}).get(int(row["input_index"]), fallback_state)
                if support_states_by_mode is not None and mode is not None
                else fallback_state
            )
            if support_states_by_mode is not None and mode is not None:
                if mode not in support_states_by_mode or int(row["input_index"]) not in support_states_by_mode[mode]:
                    raise ValueError(
                        f"support audit does not cover E1 mode={mode} input_index={row['input_index']}"
                    )
            entry = {
                "input_index": int(row["input_index"]),
                "support": number(row.get("association_support")),
                "geometry": number(row.get("geometric_retention")),
                "direction": number(row.get("directional_proxy")),
                "spatial_entropy": number(row.get("spatial_entropy_proxy")),
                "translation_error_m": number(row.get("translation_error_m")),
                "rotation_error_deg_so3": number(row.get("rotation_error_deg_so3")),
                "rpe_translation_m": number(row.get("rpe_1frame_translation_m")),
                "rpe_rotation_deg_so3": number(row.get("rpe_1frame_rotation_deg")),
                "support_state": support_state,
            }
            by_group.setdefault(key, []).append(entry)
    result: list[dict[str, Any]] = []
    build_key = next((key for key in by_group if key[1] == "map_build"), None)
    if build_key is None:
        raise ValueError("E1 CSV has no map_build group")
    reference = reference_medians(by_group[build_key])
    for (sequence, role), raw_rows in sorted(by_group.items()):
        rows = []
        for row in raw_rows:
            if row["support_state"] != "MAP_SUPPORTED":
                continue
            row = dict(row)
            row["features"] = build_features(row, reference)
            rows.append(row)
        result.append({
            "group": f"{label_prefix}:{sequence}:{role}",
            "source": str(path),
            "source_sha256": sha256(path),
            "input_count": len(raw_rows),
            "map_supported_count": len(rows),
            "non_map_supported_count": len(raw_rows) - len(rows),
            "support_state_counts": {
                "MAP_SUPPORTED": len(rows),
                "VO_FALLBACK": sum(row["support_state"] == "VO_FALLBACK" for row in raw_rows),
                "INVALID_OR_LOST": sum(row["support_state"] == "INVALID_OR_LOST" for row in raw_rows),
                "UNKNOWN": sum(row["support_state"] == "UNKNOWN" for row in raw_rows),
            },
            "support_state_source": (
                "dedicated_support_audit"
                if support_states_by_mode is not None
                else "evidence_available_fallback"
            ),
            "rotation_outcome": "rotation_error_deg_so3",
            "relative_rotation_outcome": "rpe_rotation_deg_so3",
            "reference_medians": reference,
            "rows": rows,
        })
    return result


def load_challenger_json(path: Path, label_prefix: str) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for group in data["groups"]:
        reference = {
            "support": data["reference_medians"]["association_ratio"],
            "geometry": data["reference_medians"]["geometric_retention_ratio"],
            "direction": data["reference_medians"]["directional_geometry_proxy"],
        }
        rows = []
        for raw in group["rows"]:
            if raw.get("support_state") != "MAP_SUPPORTED":
                continue
            features = dict(raw["features"])
            errors = raw.get("errors") or {}
            rows.append({
                "input_index": int(raw["input_index"]),
                "support": None,
                "geometry": None,
                "direction": None,
                "spatial_entropy": features.get("spatial_entropy"),
                "translation_error_m": number(errors.get("translation_error_m")),
                "yaw_error_deg": number(errors.get("yaw_error_deg")),
                "rpe_translation_m": number(errors.get("rpe_translation_m")),
                "rpe_yaw_deg": number(errors.get("rpe_yaw_deg")),
                "support_state": raw["support_state"],
                "features": features,
            })
        result.append({
            "group": f"{label_prefix}:{group['group']}",
            "source": str(path),
            "source_sha256": sha256(path),
            "input_count": int(group["input_count"]),
            "map_supported_count": len(rows),
            "non_map_supported_count": int(group["input_count"]) - len(rows),
            "support_state_counts": group.get("support_state_counts", {
                "MAP_SUPPORTED": len(rows),
                "VO_FALLBACK": 0,
                "INVALID_OR_LOST": 0,
                "UNKNOWN": int(group["input_count"]) - len(rows),
            }),
            "rotation_outcome": "yaw_error_deg",
            "relative_rotation_outcome": "rpe_yaw_deg",
            "reference_medians": reference,
            "rows": rows,
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--e1-audit", type=Path, required=True)
    parser.add_argument(
        "--e1-support-audit",
        type=Path,
        action="append",
        default=[],
        help="Dedicated E1 support-audit JSON(s); required to preserve VO_FALLBACK vs UNKNOWN.",
    )
    parser.add_argument("--p1-json", type=Path, required=True)
    parser.add_argument("--p2-json", type=Path)
    parser.add_argument("--e2-json", type=Path)
    parser.add_argument("--e2-support-audit", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"fail-if-exists: {args.out}")
    support_states = load_support_state_audits(args.e1_support_audit) if args.e1_support_audit else None
    groups = load_e1(args.e1_audit, "E1_OpenLORIS", support_states)
    groups += load_challenger_json(args.p1_json, "P1_TUM")
    if args.e2_json is not None:
        groups += load_challenger_json(args.e2_json, "E2_Cafe")
    if args.p2_json is not None:
        groups += load_challenger_json(args.p2_json, "P2_TUM")
    e2_exclusions = []
    for path in args.e2_support_audit:
        data = json.loads(path.read_text(encoding="utf-8"))
        if args.e2_json is None:
            e2_exclusions.append({
                "source": str(path),
                "source_sha256": sha256(path),
                "group": f"E2_Cafe:{data.get('mode', 'unknown')}",
                "input_count": data.get("input_count"),
                "support_state_counts": data.get("support_state_counts"),
                "excluded_reason": "support audit has no native axis fields; no imputation",
            })
    output = {
        "schema": "unified_reference_map_challenger_audit_v2",
        "status": (
            "PASS_DESCRIPTIVE_CROSS_SOURCE_COMPARISON"
            if args.e2_json is not None
            else "PASS_DESCRIPTIVE_CROSS_SOURCE_COMPARISON_WITH_E2_EXCLUDED"
        ),
        "interpretation": {
            "role": "same-input descriptive challenger audit",
            "no_threshold_tuning": True,
            "no_detector_metrics": True,
            "no_superiority_claim": True,
            "frames_are_not_independent_replicates": True,
            "e2_not_comparable": args.e2_json is None,
            "e2_axes_source": "native_stdout_log" if args.e2_json is not None else None,
            "rotation_outcomes_interchangeable": False,
            "absent_outcomes": "count=0 and null summaries; never inferred from another rotation metric",
        },
        "outcome_definitions": OUTCOME_DEFINITIONS,
        "groups": [
            {
                **{key: value for key, value in group.items() if key != "rows"},
                "comparisons": summarize(group["rows"], input_count=group["input_count"]),
            }
            for group in groups
        ],
        "excluded_groups": e2_exclusions,
        "source_hashes": {
            "e1_audit": sha256(args.e1_audit),
            "e1_support_audits": [sha256(path) for path in args.e1_support_audit],
            "p1_json": sha256(args.p1_json),
            "e2_json": sha256(args.e2_json) if args.e2_json is not None else None,
            "p2_json": sha256(args.p2_json) if args.p2_json is not None else None,
            "e2_support_audits": [sha256(path) for path in args.e2_support_audit],
        },
    }
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "groups": len(groups), "e2_excluded": len(e2_exclusions)}))


if __name__ == "__main__":
    main()
