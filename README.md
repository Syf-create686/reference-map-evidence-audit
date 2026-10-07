# Reproduction package — Interpretable Evidence Auditing for Reference-map RGB-D Localization

This repository is the minimal reproduction package for the manuscript
*Interpretable Evidence Auditing for Reference-map RGB-D Localization*
(Robotics and Autonomous Systems).

It contains the analysis code, the frozen protocol definitions, the evidence
records, and the input association files needed to check every number reported in
the manuscript. It deliberately does **not** contain image data, saved atlases, or
raw tracker logs; those are derived or third-party artefacts and are identified by
checksum in [`PROVENANCE.md`](PROVENANCE.md) instead.

## What is here

| Path | Contents |
|---|---|
| `tools/` | the nine analysis scripts, including the five cited in Section 9 of the manuscript |
| `protocols/` | the frozen protocol definitions the study relies on (support contract, directional proxy, challenger comparison, camera configurations, E3 intervention) |
| `experiments/EXP-20260929-public-dataset-audit/` | the evidence records the reported numbers trace to |
| `experiments/.../post_v1_6_*_inputs/` | RGB/depth association files for the OpenLORIS sequences, including both archived Office materializations |
| `MANIFEST.json` | path, byte size and SHA-256 for every file in this package |

## Entry points

The scripts corresponding to the manuscript tables are:

| Manuscript item | Script |
|---|---|
| Support-state coverage | `tools/classify_reference_map_pose_support.py` |
| Evidence coordinates, median [Q1, Q3] | `tools/summarize_reference_window_stats.py` |
| Challenger comparison | `tools/compare_tum_reference_map_challenger.py`, `tools/compare_unified_reference_map_challenger.py` |
| Export predicate vs support contract | `tools/reconstruct_reference_map_input_status.py` then `tools/classify_reference_map_pose_support.py` |
| E3 intervention runtime | `tools/audit_openloris_intervention_runtime.py` |

### Classification chain

```bash
# 1. reconstruct the per-input status record from the frozen native artefacts
python tools/reconstruct_reference_map_input_status.py \
    --associations <associations.txt> \
    --tracking-health <tracking_health.csv> \
    --trajectory <CameraTrajectory.txt> \
    --out input_status.csv \
    --metadata input_status_metadata.json

# 2. classify each input against the frozen support definition
python tools/classify_reference_map_pose_support.py \
    --associations <associations.txt> \
    --input-status input_status.csv \
    --tracking-health <tracking_health.csv> \
    --definition protocols/REFERENCE_MAP_POSE_SUPPORT_DEFINITION_V1_20261003.json \
    --mode build|revisit \
    --out support_audit.json
```

### Coordinate summaries

```bash
python tools/summarize_reference_window_stats.py \
    --run "E1 Office build=<native_stdout.log>" \
    --run "E1 Office revisit=<native_stdout.log>" \
    --out coordinate_summary.json
```

The bracketed pair in the coordinate table is the **first and third quartile**,
not a confidence interval.

## Environment

* Python 3 with `numpy`
* The native estimator is the ORB-SLAM3 RGB-D entry point in reference-map mode,
  used with a frozen vocabulary and per-sequence settings; the estimator is not
  redistributed here.
* The directional-proxy and native-evidence markers (`M2_DIAG_*`) are emitted by
  that instrumented entry point and parsed from its standard output.

See [`requirements.txt`](requirements.txt).

## Data sources

No new sensor data were captured. All sequences are public datasets used under
their original terms and are **not** redistributed here:

* **OpenLORIS-Scene** — Office (`office1-1`, `office1-3`) and Cafe (`cafe1-1`, `cafe1-2`).
  Ground truth is offline LiDAR SLAM and is used only for offline evaluation.
* **TUM RGB-D benchmark** — `freiburg1_desk`, `freiburg1_desk2`, `freiburg2_desk`.
  Ground truth is used only for offline evaluation.

The `freiburg2_desk` archive used here has SHA-256
`1a0756d72510a26e26e2a02bf0b6c69c2796619fca531e176fc2e5110173807c` and was verified
by gzip-to-EOF and CRC before extraction; see `PROVENANCE.md` for details.

## Scope and limits

This package supports reproduction of the reported **populations and counts**. It
does not ship the raw logs or atlases, so re-deriving the per-frame evidence values
requires re-running the estimator on the public sequences with the frozen
configuration. Every number in the manuscript can nevertheless be checked against
the evidence records and association files included here.

The study is a descriptive offline analysis. It does not provide a validated event
detector, a calibrated confidence model, an active-recovery policy, or real-robot
validation, and none of those are claimed.

## Licence

Code: MIT (see [`LICENSE`](LICENSE)). Documents and evidence records: CC BY 4.0.
Third-party datasets remain under their own licences.
