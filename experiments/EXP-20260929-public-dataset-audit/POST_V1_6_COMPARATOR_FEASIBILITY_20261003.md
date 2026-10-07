# Post-V1.6 comparator feasibility audit

> **Input-lineage notice (2026-10-03):** the completed office numerical
> comparison is now pipeline-audit-only because its source RGB-D run used raw
> depth with color-camera intrinsics. Challenger field availability remains
> correctly audited; comparative values require aligned-depth data.

Date: 2026-10-03

Status: `S3_NUMERICAL_FEASIBILITY_PASS; S3_SCIENTIFIC_COMPARISON_NOT_YET_PASS`

## Primary-source method check

Ferranti et al., *Can You Trust Your Pose? Confidence Estimation in Visual
Localization* (2020, <https://arxiv.org/abs/2010.00347>) was checked at the
method and training sections on 2026-10-03. Its full confidence model uses:

1. the final pose inlier count;
2. query-image inlier coverage;
3. database-image inlier coverage;
4. a logistic regression trained using an external pose-correctness label,
   with query-related candidates kept within one train/test side.

The coverage score marks pixels covered by at least one inlier in a rectangular
neighborhood sized to 1/15 of the image dimensions. This is not identical to a
convex hull, grid occupancy, or entropy.

## Availability in retained outputs

| Required/possible comparator field | Current state | Decision |
|---|---|---|
| Map association and geometric-inlier counts | Available for 29/30 inputs per run | Valid count-only comparators |
| Query spatial distribution | 4x3 occupancy and normalized entropy available for 29/30 inputs | Use only as `literature-inspired query spatial-distribution proxy` |
| Per-inlier query coordinates | Not retained in current logs | Exact Ferranti query coverage cannot be reconstructed |
| Corresponding database-image inlier coordinates | Not defined/retained for multi-keyframe ORB map tracking | Exact Ferranti database coverage is unavailable |
| Independent train/evaluation labels and adequate groups | Not available in the scratch-map cohort | Logistic confidence model cannot be trained/evaluated fairly |
| Published implementation/license | No source implementation identified in the inspected primary record | Do not claim code reproduction |

The full Ferranti method is therefore **not feasible from the retained
artifacts** and will not be approximated under its name.

## Minimum fair challenger set for the next data

The true reference-map run must log the current three axes and the existing
4x3 query spatial marker on exactly the same input frames. The minimum
comparison is:

- raw geometric-inlier count and association support;
- the pre-existing query spatial entropy/occupancy proxy;
- association plus geometric retention;
- the full three-axis representation;
- the already frozen simple scalar fusions.

This gives a non-synonymous spatial challenger without adding a learned model
to a sample that cannot support training. If the reference-map pilot can
retain the exact current-frame inlier coordinates without changing tracking,
an exact **query-side** neighborhood coverage score may be added under a
separate name and frozen implementation. It still must not be called the full
Ferranti confidence method because database coverage and its trained model are
absent.

## Scientific decision

The existing spatial marker is technically usable: every audited run has 29
same-frame values. Its within-run relationship with SO(3) error changes sign
across the retained cases, just as the proposed axes do. This rules out using
the current scratch-map results to select a favorable comparator or claim
superiority.

`PASS_AVAILABLE_CHALLENGER_FIELDS; FAIL_CURRENT_FULL_LITERATURE_BASELINE`

A frozen numerical comparison has now been completed on the 143
`MAP_SUPPORTED` frames from the already-seen `office1-3` reference-map pilot.
The detailed result is recorded in
`POST_V1_6_REFERENCE_MAP_CHALLENGER_RESULT_20261003.md` and the associated JSON.

The joint summaries were stronger than the spatial entropy proxy for local
one-frame RPE, while the entropy proxy was comparable to individual native
axes for SO(3) APE. The three-axis summaries did not show a large descriptive
advantage over the support-plus-geometry mean. Translation APE had the
opposite association sign from local RPE, and both evidence and outcomes were
associated with input order. This makes trajectory/time confounding a material
alternative explanation.

The comparison closes numerical feasibility only. One contiguous development
run cannot support superiority, incremental information or generalization.
Those claims remain blocked pending independent source/session groups under
the same frozen comparison.
