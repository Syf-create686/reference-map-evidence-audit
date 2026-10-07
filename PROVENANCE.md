# Provenance ledger

This file records, in English and without internal process labels, where every
reported number comes from. It replaces the internal working notes that are not part
of this package.

Throughout, an **input** is one RGB-D frame submitted to the estimator, a **row** is
one line of an exported trajectory file, and **OK / RECENTLY_LOST / LOST** are the
native tracking states (2 / 3 / 4). The **support contract** accepts an input only
when its matching tracking-health record has state OK *and* a valid pose is
available.

## 1. Data groups

| Group | Source | Second-role semantics | Inputs |
|---|---|---|---|
| E1 Office build / revisit | OpenLORIS Office `office1-1` / `office1-3` | separate recording of the same space | 809 / 360 |
| E2 Cafe build / revisit | OpenLORIS Cafe `cafe1-1` / `cafe1-2` | separate recording of the same space | 1708 / 2698 |
| P1 TUM build / revisit / window2 | TUM `freiburg1_desk2` | disjoint time window of one sequence | 30 / 30 / 30 |
| P2 TUM build / revisit | TUM `freiburg1_desk` | disjoint time window of one sequence | 30 / 30 |
| E3 Office RGB-occlusion | E1 revisit input with a central RGB mask | paired input-response boundary | 360 |
| FR2 TUM build / continuation | TUM `freiburg2_desk` | **chronological continuation of one scan, not a spatial revisit** | 988 / 1977 |

The second role always localizes against the atlas built by the first role, in
localization-only mode, and leaves that atlas unchanged. The role name does not by
itself assert that a spatial revisit occurred. For FR2 the second role does not
return to the build camera positions: only 4.0 % of its poses lie within 0.25 m of a
build pose, against 35.6 % for the E2 Cafe revisit, which is a genuine second
recording.

## 2. Support-state counts

| Group | Inputs | MAP_SUPPORTED | VO_FALLBACK | INVALID_OR_LOST | UNKNOWN |
|---|---|---|---|---|---|
| E1 Office build | 809 | 808 | 0 | 0 | 1 |
| E1 Office revisit | 360 | 144 | 216 | 0 | 0 |
| E2 Cafe build | 1708 | 1707 | 0 | 0 | 1 |
| E2 Cafe revisit | 2698 | 892 | 1723 | 83 | 0 |
| P1 TUM build | 30 | 29 | 0 | 0 | 1 |
| P1 TUM revisit | 30 | 22 | 8 | 0 | 0 |
| P2 TUM build | 30 | 29 | 0 | 0 | 1 |
| P2 TUM revisit | 30 | 30 | 0 | 0 | 0 |
| E3 Office RGB-occlusion | 360 | 61 | 212 | 87 | 0 |
| FR2 TUM build | 988 | 987 | 0 | 0 | 1 |
| FR2 TUM continuation | 1977 | 266 | 1422 | 289 | 0 |

The support-state categories are evidence-availability categories, not detector
outcomes. UNKNOWN is not renamed to a tracking-lost count.

## 3. Evidence coordinates

Produced by `tools/summarize_reference_window_stats.py`. Each cell is the median
over complete rows with the **first and third quartiles in brackets**; rows missing
any coordinate stay in the frame denominator and are not imputed.

| Group | s | g | d | Complete / frames |
|---|---|---|---|---|
| E1 Office build | 0.5315 [0.4876, 0.5745] | 0.6720 [0.6080, 0.7468] | 0.1023 [0.0918, 0.1103] | 808 / 809 |
| E1 Office revisit | 0.5885 [0.4955, 0.6018] | 0.6466 [0.6180, 0.6576] | 0.1151 [0.1116, 0.1174] | 144 / 360 |
| E2 Cafe build | 0.5076 [0.4538, 0.5489] | 0.6604 [0.5821, 0.7285] | 0.1103 [0.0995, 0.1185] | 1707 / 1708 |
| E2 Cafe revisit | 0.4549 [0.4036, 0.4878] | 0.5096 [0.4576, 0.5532] | 0.1155 [0.1052, 0.1252] | 892 / 2698 |
| P1 TUM build | 0.5481 [0.5313, 0.5670] | 0.5847 [0.5641, 0.6362] | 0.0860 [0.0788, 0.0913] | 29 / 30 |
| P1 TUM revisit | 0.5237 [0.4746, 0.6343] | 0.4686 [0.4390, 0.5157] | 0.0903 [0.0807, 0.0934] | 22 / 30 |
| P2 TUM build | 0.5419 [0.5244, 0.5637] | 0.6059 [0.5562, 0.6922] | 0.0917 [0.0859, 0.1065] | 29 / 30 |
| P2 TUM revisit | 0.5117 [0.4807, 0.5329] | 0.6798 [0.5409, 0.7034] | 0.0825 [0.0772, 0.1005] | 30 / 30 |
| FR2 TUM build | 0.5713 [0.5379, 0.6032] | 0.5728 [0.5369, 0.6170] | 0.1039 [0.0948, 0.1119] | 987 / 988 |
| FR2 TUM continuation | 0.5874 [0.5598, 0.6230] | 0.6303 [0.5817, 0.6660] | 0.1037 [0.0998, 0.1089] | 266 / 1977 |

`s = map associations / extracted features`; `g = geometric inliers / map
associations`; `d` is the directional geometry proxy, the ratio of the smallest to
the largest singular value of the rotational block of the 6x6 information matrix,
defined in `protocols/DIRECTIONAL_GEOMETRY_PROXY_DEFINITION_V1.json`.

## 4. Export predicate versus support contract

| Run | Inputs | OK | RECENTLY_LOST | LOST | Exported rows | Contract population |
|---|---|---|---|---|---|---|
| E1 Office revisit | 360 | 360 | 0 | 0 | 360 | 360 |
| E2 Cafe revisit | 2698 | 2615 | 23 | 60 | 2638 | 2615 |
| P1 TUM revisit | 30 | 30 | 0 | 0 | 30 | 30 |
| P2 TUM revisit | 30 | 30 | 0 | 0 | 30 | 30 |
| E3 occlusion | 360 | 273 | 0 | 87 | 273 | 273 |
| FR2 TUM continuation | 1977 | 1688 | 289 | 0 | 1977 | 1688 |

The two chains that diverge do so by exactly the RECENTLY_LOST class:

* **E2 Cafe revisit.** 2698 inputs = 2615 OK + 23 RECENTLY_LOST + 60 LOST, and the
  export holds 2638 rows against a contract population of 2615, a difference of 23.
  That difference is a **population** statement, not a per-row count. The join is not
  injective: the 2638 rows carry only 2626 distinct timestamps, because six
  timestamps appear more than once (two twice, two three times, two four times; five
  OK and one RECENTLY_LOST), contributing 12 excess rows, and 72 inputs have no row
  at all (60 LOST and 12 RECENTLY_LOST). The row-level composition is therefore 2626
  OK rows and 12 RECENTLY_LOST rows. The exported row count equals the non-LOST input
  count, 2638, only because 12 duplicated rows offset 12 missing RECENTLY_LOST rows.
* **FR2 TUM continuation.** 1977 inputs = 1688 OK + 289 RECENTLY_LOST, no LOST. Here
  the join is one-to-one: 1977 rows, 1977 distinct timestamps, no missing inputs, so
  all 289 excess rows correspond individually to RECENTLY_LOST inputs.

## 5. Geometric separation by native state

Distance from each second-role pose to the nearest build pose; both trajectories are
expressed in the build map frame because the second role loaded the build atlas in
localization-only mode and left it unchanged.

| Chain | Native state | n | median (m) | p90 (m) | max (m) |
|---|---|---|---|---|---|
| E2 Cafe revisit | OK | 2626 | 0.868 | 4.585 | 4.82 |
| E2 Cafe revisit | RECENTLY_LOST | 12 | 0.148 | 0.684 | 2.64 |
| FR2 TUM continuation | OK | 1688 | 1.937 | 2.602 | 2.81 |
| FR2 TUM continuation | RECENTLY_LOST | 289 | 136.197 | 296.114 | 335.92 |

For FR2 the 1688 OK-state poses stay within 2.81 m of the build trajectory, whereas
its 289 RECENTLY_LOST poses lie a median of 136 m away and up to 336 m away. Because
that second role is a forward continuation rather than a return to the mapped space,
this is a **map-support separation, not a ground-truth localization error**; no
ground-truth comparison is made for these rows. The same stratification does not
reproduce that separation in the Cafe revisit, where the 12 RECENTLY_LOST poses stay
within 2.64 m. The magnitude is therefore chain-dependent and is not claimed as
general.

## 6. The Office input materializations

Two materializations of the OpenLORIS Office association files are archived and both
are included here, because they are the only difference between two otherwise
identical runs:

| Item | `post_v1_6_office_aligned_reference_map_inputs` | `post_v1_6_reference_map_pilot_inputs` |
|---|---|---|
| depth stream | aligned depth, depth registered to colour | unregistered depth |
| `office1-1` associations | 85,754 bytes | 79,282 bytes |
| `office1-3` associations | 38,160 bytes | 35,280 bytes |
| depth pixels | registered (about 168 kB per frame) | unregistered (about 209 kB per frame) |

The RGB and depth timestamps are identical between the two; only the depth directory
prefix and the depth pixel content differ. The manuscript uses the registered
materialization throughout. The unregistered materialization yields a different
frame-level support count on the revisit (127 of 360 instead of 144 of 360) and is
not used for any reported number.

## 7. Third-party artefacts not redistributed

| Artefact | Identifier |
|---|---|
| `freiburg2_desk` archive | SHA-256 `1a0756d72510a26e26e2a02bf0b6c69c2796619fca531e176fc2e5110173807c`, 1,893,351,095 bytes |
| `freiburg2_desk` extraction | 5,933 files, 2,001,657,567 bytes |
| ORB-SLAM3 RGB-D reference-map entry point | frozen build; the estimator is not redistributed |
| ORB vocabulary | `ORBvoc.txt` from ORB-SLAM3 |

The `freiburg2_desk` archive was transport-repaired before use: the original partial
download was retained as a prefix, the missing tail of 29,703,863 bytes was
re-fetched and hash-verified per segment, and the reassembled archive was validated
by gzip-to-EOF and CRC before extraction.

## 8. Statement of scope

Every quantity in this ledger is a count, a median, a quartile, or a distance. None
of them is a detector accuracy, a calibrated threshold, a confidence interval, a
causal attribution, or a localization performance claim. The support-state
categories are evidence-availability categories. Negative results are reported as
such: the three-axis evidence summary shows no stable advantage over the simpler or
spatial alternatives, and that boundary is part of the result.
