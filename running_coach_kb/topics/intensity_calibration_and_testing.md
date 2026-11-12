# Topic Guide: Intensity Calibration and Testing

**Retrieve for:** `recalibrate_intensity`, `select_quality_session` when anchors are uncertain, `review_training_block` when an objective depends on a performance anchor, or interpretation of a benchmark/race. Do not retrieve for every easy run.

## Core position

Training intensity is an estimate with method-specific error, not a permanent truth. Use the least precise anchor that is precise enough for the decision. A recent race, a field critical-speed estimate, a laboratory threshold, a repeatable workout, heart rate, pace, RPE, and the talk test describe overlapping but nonidentical constructs. Correlation between methods does not make them interchangeable for an individual [E-CAL-01–03].

The coach should prefer **converging evidence from repeated, comparable observations** over one fast run, one 5K, one device VO2max estimate, or one threshold number. When conditions or fatigue make pace unreliable, prescribe by effort and session purpose.

## Decision questions

1. What decision requires an intensity anchor: easy control, threshold-oriented work, VO2-oriented work, race-specific work, or progress assessment?
2. How current, comparable, and trustworthy is each available observation?
3. Do multiple anchors agree closely enough to justify a narrow pace/HR range?
4. What execution signal should override the initial target during the session?
5. What new observation would justify recalibration?

## Anchor hierarchy

This is a practical hierarchy, not a claim that the first item is always physiologically superior.

| Anchor | Best use | Confidence improves when | Main limits |
|---|---|---|---|
| Recent race or controlled benchmark | Event-specific prediction and broad training calibration | The effort was genuinely hard, conditions and course are known, and the result is recent/repeatable | Race distance emphasizes different determinants; pacing, weather, terrain, illness, and motivation can distort it |
| Standardized multi-point critical-speed field test | Severe-domain boundary estimate and performance modelling | Two or more maximal efforts span suitable durations, use the same surface/device, and model fit is inspected | Protocol/model choice changes CS and D′; maximal tests add fatigue; D′ is especially variable [E-CAL-01, E-CAL-03] |
| Laboratory threshold/VO2 test | High-consequence calibration when available | Criterion, protocol, units, date, and measurement error are known | Threshold definitions differ; laboratory pace may not transfer directly outdoors |
| Repeatable workout execution | Ongoing calibration of usable training dose | Same recipe, route/conditions, recovery, and execution markers recur | A workout is not a validated threshold test; completion can reflect motivation or excessive recovery |
| RPE, talk test, and breathing | Real-time control, especially easy running or variable conditions | The athlete has learned the scale and reports promptly | Subjective and influenced by stress, heat, fueling, and expectations; still valuable rather than “invalid” |
| Heart rate | Supporting control for steady work and longitudinal comparison | Sensor is credible, individual thresholds/maxima are established, and lag/drift are considered | Lag in intervals, environmental drift, medication/illness, wrist-sensor error, and generic percentages |
| Pace/speed | Execution target on comparable terrain and conditions | Course, surface, wind, elevation, weather, and recovery are comparable | A precise pace can create the wrong physiological/mechanical session when context changes |
| Device-estimated VO2max/readiness/threshold | Secondary trend or hypothesis | Algorithm, device, data quality, and trend stability are understood | Proprietary, model- and firmware-dependent; not a standalone prescription or diagnosis |

## Calibration workflow

### 1. Define the target construct

Do not ask for “the athlete’s threshold pace” without specifying the operational use. A pace for controlled threshold intervals, a maximal-lactate-steady-state estimate, critical speed, ventilatory threshold, and a one-hour race approximation are related but not identical.

### 2. Quality-screen the observations

For every candidate anchor, record:

- date and recency;
- protocol and whether effort was maximal, controlled, or ordinary training;
- course/surface/elevation and environmental conditions;
- device/sensor and quality flags;
- recent training, illness, soreness, sleep, and fueling context;
- whether the comparison is within the same method; and
- known typical error or repeatability, if available.

If these are missing, retain the observation but lower confidence.

### 3. Triangulate

Use at least two distinct observations when a narrow target matters. Examples:

- race/benchmark plus recent controlled intervals;
- field critical speed plus RPE/HR response in a repeatable workout;
- laboratory threshold plus outdoor execution;
- repeatable easy-route pace/HR/RPE under comparable conditions.

Agreement means the resulting session can be controlled, not that the methods estimate the same biological point.

### 4. Assign calibration confidence

- **High:** recent, methodologically credible evidence; repeated/comparable; multiple anchors agree; no important confounder.
- **Moderate:** one strong observation plus supportive execution data, or several ordinary observations that agree.
- **Low:** single result, old result, inconsistent methods, poor comparability, or substantial confounding.
- **Insufficient:** the target cannot be estimated without pretending missing data are normal.

Only high/moderate confidence should generate a narrow pace or HR target. Low confidence should generate a broader effort target and an explicit learning objective.

### 5. Prescribe an execution hierarchy

Every quality prescription should name:

1. **Primary control:** usually RPE/breathing/session purpose, or pace when confidence and conditions support it.
2. **Secondary check:** HR, lap consistency, talk test, or form.
3. **Ceiling/stop rule:** rising symptoms, gait/form change, inability to keep the intended effort, or marked rep deterioration.
4. **Uncertainty:** why the target may need adjustment.

A target pace is an opening hypothesis. Do not force it when the observed session no longer matches its intended domain.

## When to use effort instead of exact pace

Prefer effort-first prescription when:

- heat, humidity, wind, hills, trail surface, treadmill calibration, or altitude materially alters pace;
- the anchor is old, derived from a different event, or supported by one effort only;
- the athlete is returning from illness/interruption or carrying unusual fatigue/soreness;
- sensor quality is poor;
- symptoms or impact tolerance, rather than cardiorespiratory capacity, are the limiting factor;
- the session is intentionally exploratory; or
- an exact target would encourage racing the workout.

## Establishing a baseline without a race

Use the least disruptive option that answers the question:

- repeat a standardized submaximal easy run and compare RPE/HR only under sufficiently similar conditions;
- use a controlled recipe with consistent work/recovery and examine repeat quality and delayed response;
- use a nonmaximal talk-test or threshold-field method if validated for the available protocol and precision need;
- use multi-effort critical-speed testing only when maximal testing is appropriate, the protocol can be standardized, and the result will change decisions.

Do not schedule a maximal test simply because the app lacks a number.

## Recalibration triggers

Recalibrate when at least one is material:

- a credible race or standardized benchmark differs meaningfully from the current estimate;
- several comparable workouts are consistently too easy, too hard, or executed outside the intended domain;
- the athlete returns from a meaningful interruption or illness;
- environmental context changes systematically (for example, treadmill to outdoor heat);
- a device/sensor or threshold method changes;
- the active block changes the required anchor; or
- current targets repeatedly cause racing, failure, or excessive recovery cost.

Do **not** recalibrate from one unusually good/bad day or by a fixed weekly cadence.

## Interpreting apparent nonresponse

Before concluding that a block did not work, check whether the test can resolve the expected change. Observed change includes biological adaptation, day-to-day variability, and measurement error. Repeated-testing research shows substantial disagreement among responder-classification methods [E-CAL-04]. Therefore:

- classify objective status separately from tolerance;
- use `not_assessable` when exposure or measurement was inadequate;
- look for converging submaximal, performance, and execution evidence;
- do not label a person a “nonresponder” from one test or one block; and
- change the plan because the current evidence supports a better choice, not because of a fixed identity label.

## Interaction with recipes

Recipes specify acceptable anchor options and execution signals. Calibration supplies the current values and confidence. The recipe must remain usable when pace/HR values are `null`; the coach can select an effort-based version or a less demanding family.

## What not to infer

- A 5K result supplies exact mile, threshold, and marathon paces.
- A Garmin VO2max change proves fitness changed by the same amount.
- A high correlation between a field method and laboratory threshold proves individual interchangeability.
- A completed hard workout validates its prescribed intensity.
- A single failed benchmark proves detraining or nonresponse.
- Generic percentages of age-predicted max HR define the athlete’s zones.

## Evidence and policy links

- E-CAL-01 to E-CAL-04; S064-S068
- Existing E-INT-04, E-WEAR-04–05, E-DATA-01–02
- P010, P015, P020, P021
