# Post-V1.6 cafe ground-truth preflight

Date: 2026-10-03

Status: `CAFE_GT_SUBSET_PASS; RGBD_ARCHIVE_AUDIT_PENDING`

## Verified source

The official OpenLORIS ground-truth archive was downloaded outside Git with
the frozen parallel range downloader.

- size: `11,076,559` bytes;
- SHA-256:
  `07564d7ed3d6739585002afa12bcf481cc0e9e358fc64efd5e658e2c994bdc3b`;
- frozen source identity match: yes.

The archive contains all 22 expected sequence files and all five expected
scene files. The archive-wide audit status is `REVIEW_REQUIRED` because the
five `home` trajectories contain known duplicate timestamps. This warning is
retained even though the home scene is outside the frozen cafe experiment.

## Frozen cafe subset

| Sequence | GT rows | Span | Strictly increasing | Duplicate timestamps | Quaternion norm range |
| --- | ---: | ---: | --- | ---: | ---: |
| `cafe1-1` | 2,281 | 56.979 s | yes | 0 | 1.000000–1.000000 |
| `cafe1-2` | 3,605 | 89.972 s | yes | 0 | 1.000000–1.000000 |

Both frozen cafe roles therefore pass the GT file-level subset checks. The GT
source remains the dataset's offline LiDAR-SLAM trajectory, rather than office
OptiTrack. That provenance must remain visible in every trajectory result and
limits claims about very small absolute errors.

GT is excluded from map construction, tracking, evidence calculation and
pose-support classification. It is admitted only for offline timestamp pairing
and trajectory endpoints after the estimator output is frozen.

## Remaining gate

This preflight does not admit an ORB run. The 7.47 GB cafe RGB-D package must
still match its frozen SHA-256 and pass archive, calibration, aligned-depth,
indexed-file and RGB-depth pairing audits. Until then the S4 state remains
`DATA_DOWNLOAD_AND_AUDIT_IN_PROGRESS`.

Machine-readable audit:
`POST_V1_6_CAFE_GROUNDTRUTH_AUDIT_20261003.json`.
