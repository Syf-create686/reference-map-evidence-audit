# Post-V1.6 reference-map challenger result

> **Supersession notice (2026-10-03):** the source reference-map pilot used
> raw OpenLORIS `depth` rather than depth registered to color. The numerical
> pipeline remains reproducible, but these feature/outcome values cannot support
> an RGB-D geometry or comparative paper claim. See
> `POST_V1_6_OPENLORIS_DEPTH_REGISTRATION_AUDIT_20261003.md`.

Date: 2026-10-03

Status: `RETROSPECTIVE_PIPELINE_AUDIT_ONLY; INPUT_GEOMETRY_QUARANTINED`

## Population and frozen analysis

The comparison used the 143 `MAP_SUPPORTED` frames from the already-seen
OpenLORIS `office1-3` reference-map pilot. The other 217 finite system poses
were classified as `VO_FALLBACK` and were excluded before this analysis was
run. These 143 frames form one contiguous run and are not independent
replicates.

The protocol, inputs, feature set, outcomes, complete-case rule and quartile
comparison were committed before the numerical result was generated. No
threshold, weight, model or winner was selected from the result. The exact
Ferranti et al. confidence method remains unavailable because the retained
data lack database-side coverage and an independent labelled training set.
The challenger here is therefore named only as a
`literature-inspired query spatial-distribution proxy`.

## Main descriptive result

All reported values below are descriptive Spearman rank associations on the
same contiguous run. No p-values are reported.

| Feature | Translation APE | SO(3) APE | 1-frame translation RPE | 1-frame SO(3) RPE | Feature versus input index |
| --- | ---: | ---: | ---: | ---: | ---: |
| Association support | 0.777 | -0.498 | -0.757 | -0.624 | -0.669 |
| Geometric retention | 0.274 | -0.048 | -0.350 | -0.289 | -0.070 |
| Directional proxy | 0.469 | -0.471 | -0.531 | -0.360 | -0.415 |
| Spatial entropy proxy | 0.356 | -0.437 | -0.275 | -0.120 | -0.323 |
| Grid occupancy proxy | -0.087 | -0.108 | 0.139 | 0.140 | 0.070 |
| Support + geometry mean | 0.783 | -0.494 | -0.767 | -0.644 | -0.604 |
| Three-axis minimum | 0.743 | -0.488 | -0.764 | -0.631 | -0.569 |
| Three-axis arithmetic mean | 0.756 | -0.523 | -0.770 | -0.631 | -0.599 |
| Three-axis geometric mean | 0.758 | -0.525 | -0.770 | -0.632 | -0.599 |

The local one-frame errors generally decrease when association or fused
evidence increases. The three-axis summaries do not show a large descriptive
advantage over the two-axis mean on this run. Spatial entropy has a comparable
association with SO(3) APE but much weaker associations with the two local RPE
outcomes. Grid occupancy is weak for all four outcomes.

The translation APE relation has the opposite sign from the local RPE
relations: larger association or fused evidence coincides with larger absolute
translation error. This cannot be read as a beneficial or harmful causal
effect. Translation APE is strongly associated with input order
(`rho=-0.805`), while several evidence features decline with input order. SO(3)
APE and local RPE also have moderate time associations (`rho=0.432` to
`0.515`). Time, trajectory segment and feature quality are therefore
confounded in this single run.

## Scientific decision

The numerical pipeline and the non-synonymous spatial challenger are feasible
on genuine reference-map-supported frames. The result does **not** establish
superiority, incremental predictive value, statistical significance or
generalization. It also does not validate a confidence estimator or event
detector.

`S3_NUMERICAL_FEASIBILITY_PASS; S3_SCIENTIFIC_COMPARISON_NOT_YET_PASS`

The present data support three narrower conclusions:

1. the spatial entropy proxy is not equivalent to every native evidence axis;
2. the three-axis summaries are not uniformly better than the simpler
   support-plus-geometry summary;
3. one contiguous development run cannot separate feature information from
   trajectory/time effects.

Before a paper-level comparative claim, the frozen comparison must be applied
to independent source/session groups with map-supported coverage and external
trajectory endpoints. Group-level results, per-group denominators and negative
results must be retained. This requirement is part of S4/S5 and is not waived
by the present feasibility pass.

## Reproducibility

- Frozen protocol: `protocols/REFERENCE_MAP_CHALLENGER_COMPARISON_V1_20261003.json`
- Analysis implementation: `tools/compare_reference_map_challenger.py`
- Machine-readable result:
  `POST_V1_6_REFERENCE_MAP_CHALLENGER_COMPARISON_20261003.json`
- Result SHA-256:
  `6ebf8528b20780103c342b235deef007ff7ec311e619a2cd44cae4b45d1cf5aa`
- A deterministic second execution produced the same SHA-256.
