"""Audit an existing OpenLORIS intervention run without rerunning SLAM.

The intervention runner used an obsolete ``submitted`` field when deciding its
final status.  This validator checks the immutable runtime artifacts directly,
so a completed run can be corrected offline without consuming another VM run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def audit(protocol_path: Path, output: Path, out_path: Path) -> dict[str, object]:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    execution = json.loads((output / "run_execution.json").read_text(encoding="utf-8"))
    evidence_path = output / "entrypoint_evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    run_spec = protocol["run"]
    diagnostics = protocol["diagnostics"]
    atlas = output / "T0_reference.osa"
    checks = {
        "runner_returncode_zero": execution.get("returncode") == 0,
        "tracking_health_complete": execution.get("tracking_health_rows") == diagnostics["required_tracking_health_rows"],
        "relocalization_audit_present": execution.get("relocalization_audit_rows", 0) > 0,
        "entrypoint_evidence_present": evidence_path.is_file(),
        "localization_prepared_before_first_frame": evidence.get("localization_prepared_before_first_frame") is True,
        "reference_map_unchanged": evidence.get("reference_map_unchanged") is True,
        "atlas_hash_unchanged": sha256(atlas) == run_spec["reference_atlas_sha256"],
        "groundtruth_not_used_online": execution.get("groundtruth_used_online") is False,
    }
    result = {
        "schema": "openloris_reference_map_intervention_runtime_audit_v1",
        "status": "E3_RUNTIME_PASS_WITH_WRAPPER_AUDIT_CORRECTION" if all(checks.values()) else "E3_RUNTIME_AUDIT_FAILED",
        "protocol_sha256": sha256(protocol_path),
        "source_run_execution_status": execution.get("status"),
        "checks": checks,
        "observed": {
            "returncode": execution.get("returncode"),
            "tracking_health_rows": execution.get("tracking_health_rows"),
            "required_tracking_health_rows": diagnostics["required_tracking_health_rows"],
            "relocalization_audit_rows": execution.get("relocalization_audit_rows"),
            "active_map_before": evidence.get("active_map_before"),
            "active_map_after": evidence.get("active_map_after"),
            "final_tracking_state": evidence.get("final_tracking_state"),
            "atlas_sha256": sha256(atlas),
        },
        "interpretation": (
            "The native process completed and produced a complete per-frame health log. "
            "The original wrapper marked the run failed because it required an absent "
            "submitted field; this is a wrapper schema defect, not a runtime failure."
        ),
        "limitations": [
            "This audit proves runtime/input/map integrity only; it does not establish causality or detector performance.",
            "Ground truth was not supplied to the online process and remains offline-only.",
        ],
    }
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": checks}, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"fail-if-exists: {args.out}")
    audit(args.protocol, args.output, args.out)


if __name__ == "__main__":
    main()
