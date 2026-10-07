# Level 2 reference-map revisit protocol v1

## Status

`L2_0_BLOCKED_BY_NONINTERACTIVE_REFERENCE_MAP_LOCALIZATION_ENTRYPOINT`.

This is a protocol freeze, not authorization to run Level 2. It defines the
experiment that may begin only after the dedicated reference-map replay
entrypoint passes its static validation gate.

The research purpose is long-term visual-map reuse: determine whether a robot
can return to the same warehouse under a later visual appearance and localize
against a frozen reference map. It is not a chassis, speed-limit, sensor-fusion
or map-growth experiment.

## Fixed conditions

- Carrier: frozen V3-VC visual-motion carrier.
- Scene: frozen `small_warehouse.world`, SHA-256
  `4a7d96866367df85668b09a71c60ce3a2807e7d3fe05df77a0edc62a1fa8e263`.
- Route: existing 6 m outbound + frozen 180 degree turn + 6 m return route.
- Command speed: 0.6 m/s. Speed is fixed so that Level 2 changes visual visit
  epoch rather than speed.
- Estimator inputs: RGB image, depth image and camera intrinsics only.
- Prohibited online inputs: controller odometry, wheel odometry, lidar, IMU,
  Gazebo GT and external pose supervision.
- Gazebo GT: offline motion and visual-trajectory evaluation only.
- Existing M0 assets: immutable and never repurposed as a reference-map result.

## Visit epochs

### T0: reference-map construction

One new, standard-light warehouse capture follows the fixed route. Its purpose
is solely to create a map artifact. The resulting `T0_reference.osa` is raw
data: it remains on the VM experiment disk. The shared project directory keeps
only its manifest, SHA-256, source/build identity, route identity and camera
settings hash.

### T1: changed-appearance revisit

One new capture uses exactly the same geometry, route, motion protocol, camera
and 0.6 m/s speed. The declared visual epoch is a **static low-illumination
state at 0.60 of the frozen warehouse main-light baseline**. This is a single
cross-session appearance factor, selected from the previously audited
daylight-proxy trajectory; it is not the old within-run dynamic-light M0
condition.

T1 must load the immutable T0 Atlas and run in a proven localization-only
path. It must not silently build a new active map, append T1 observations to
T0, or use the current visual condition to substitute a fresh map.

## Required entrypoint evidence before runtime

The new replay adapter must, without launching Gazebo:

1. accept explicit `--load-atlas`, `--save-atlas` and
   `--localization-only` arguments;
2. reject a missing Atlas and reject a localization-only run without a loaded
   Atlas;
3. write the absolute Atlas path, SHA-256, vocabulary SHA-256, source commit,
   compiled binary/library SHA-256 and settings SHA-256 into a manifest;
4. emit direct evidence that T0 is selected as the active tracking reference
   and local mapping is disabled before processing the first T1 frame;
5. preserve the current RGB-D calibration, `direct_xz + yaw90` offline
   evaluation and no-online-GT boundary.

Failure of any item stops the stage. It does not consume the single T1
diagnostic and does not authorize ORB parameter tuning.

## One diagnostic only after the entrypoint gate

Run exactly one T0 construction and exactly one T1 revisit. Record:

- reference-map creation/load identity;
- first stable localization timestamp and travelled distance;
- trajectory completeness;
- tracking-loss and recovery count/timestamps;
- translation and yaw RMSE/median/max under the frozen evaluator;
- distance- or time-windowed error evolution; and
- RPE, with interval fixed before the diagnostic.

The diagnostic is not a formal repeat. Only a successful diagnostic, reviewed
without automatic parameter changes, may authorize a separate three-repeat
Level 2 campaign.

## Interpretation boundary

Passing T1 would support the limited statement that frozen ORB-SLAM3 RGB-D can
reuse a T0 warehouse reference map under the declared controlled appearance
change. It would not establish real multi-day factory operation, real camera
exposure behavior, seasonal change, Sim-to-Real transfer, cross-building
generalization or an improved visual-localization algorithm.
