# Wearables and Metric Interpretation

## Takeaways first

1. **Use Garmin metrics as measurements with error, not coaching truth.** Device, firmware, fit, motion, environment, and proprietary algorithms matter.
2. **The Forerunner 265 can support trend tracking, but VO2max and race predictions are not exact.** One small validation found systematic VO2max overestimation and optimistic half-marathon predictions [E-WEAR-01].
3. **Sleep duration/timing are more defensible than stage minutes.** Stage agreement is substantially weaker [E-WEAR-02].
4. **Overnight HRV is useful mainly within the same device and athlete.** Absolute values are not interchangeable across platforms [E-WEAR-03].
5. **Wrist HR can be adequate in steady running but may lag or artifact during intervals.** Correlation is not agreement [E-WEAR-04].
6. **Training Readiness describes Garmin’s composite, not a validated proceed/rest threshold.** Show components and conflicts [E-WEAR-05].
7. **Pace/HR, decoupling, and session RPE are most useful under comparable conditions.** Heat, hills, surface, fatigue, fueling, and sensor error can distort trends [E-DATA-01–02].
8. **No dashboard metric precisely predicts injury, race performance, or readiness.** The goal is transparent decision support and longitudinal context.

## Metric taxonomy

### Direct or near-direct observations

- Timestamp, GPS track, elapsed time
- Wrist pulse waveform-derived HR
- Accelerometer-derived movement
- User-entered RPE/symptoms

Even these contain error or subjective interpretation.

### Derived metrics

- Pace, elevation gain, cadence
- Sleep duration/stages
- HRV summaries
- Training load, recovery time, VO2max estimate, race prediction
- Readiness/composite scores

Derived values depend on algorithms, settings, and upstream signal quality.

### App-computed summaries

- Rolling 14-day volume and frequency
- Recent longest comparable run
- Demanding-exposure spacing
- Standardized pace–HR/RPE trends
- Symptom-free consistency

These should be auditable from imported values and explicit logic.

## Wrist heart rate

**Research.** A treadmill validation of an older Garmin Forerunner model reported running correlations of roughly .845–.906 against reference HR, with latency and condition-dependent error [E-WEAR-04; S047]. A correlation can be high despite meaningful individual disagreement.

**Common confounders.** Loose fit, cold skin, arm motion, cadence lock, sweat, tattoos/skin characteristics, rapid intensity changes, intervals, and optical-signal dropout.

**Use.** Steady-run trends can be informative after plausibility checks. For interval precision, a chest strap may be preferable if the athlete wants one, but it is not mandatory for useful coaching.

**Quality flags.** Flatlining at cadence, impossible jumps, delayed response relative to effort, missing segments, or mismatch with RPE.

## HRV

**Research.** In a 536-night study of 13 adults, a Garmin Fenix 6 showed reasonably strong concordance for nocturnal HRV versus ECG (CCC .87; MAPE 10.5%) but with wide individual error [E-WEAR-03; S046]. This is a different model and small sample.

**Use.** Same device, similar wearing conditions, and multi-day trend. Store metric definition (for example, overnight RMSSD or Garmin status) and baseline window. Do not compare one athlete’s absolute number with another’s or mix devices.

**Do not infer.** A low night does not equal inadequate recovery, and a high night does not clear a symptomatic tendon.

## Sleep

**Research.** In a laboratory study of 53 adults using a Forerunner 245, sleep/wake agreement was 89% but kappa .35; sleep-stage agreement was 50% with kappa .25 [E-WEAR-02; S045]. Device and firmware differ from the Forerunner 265.

**Use.** Prefer sleep window, duration trend, and user-perceived quality. Treat stage minutes and score changes as low-confidence context.

**Do not infer.** A sleep score is not a diagnosis, and one low score does not mandate rest.

## VO2max estimates and race predictions

**Research.** A study of 20 half-marathon trainees using the Forerunner 265 found VO2max estimates about 2.6–2.9 mL/kg/min above laboratory values and race predictions about 7.6 minutes faster, although mean absolute percentage errors were under 10% [E-WEAR-01; S044].

**Use.** Track direction under similar training/device conditions. Verify with actual races or standardized field tests when appropriate.

**Do not infer.** A displayed VO2max is not a precise physiological measurement or a guarantee of race time. Changes can reflect algorithm inputs, heat, weight entry, or data quality.

## Training Readiness and related proprietary metrics

Garmin documentation says Training Readiness integrates sleep score, recovery time, HRV status, acute load, sleep history, and stress [S048]. Independent validation of the composite as a coaching intervention or injury-prevention tool is lacking [E-WEAR-05; S043]. Algorithms may change.

**Dashboard design.** Show:

- composite and timestamp;
- component values/status;
- missing components;
- conflicts with symptoms and subjective fatigue;
- whether the algorithm/firmware changed if detectable.

Do not reverse-engineer a medical or causal meaning.

## Pace and heart-rate trends

A useful comparison requires similar:

- route/elevation and surface;
- temperature, humidity, wind;
- session intent and RPE;
- fatigue/sleep/illness;
- fueling/hydration;
- device/sensor and quality;
- duration and point within the run.

Heat can raise HR and slow pace at the same internal strain [E-DATA-02; S051]. Hills and wind change external work. A faster pace at the same average HR on a cooler flat day is not necessarily a fitness gain.

**Preferred output.** “Under comparable conditions, pace at similar RPE/HR improved across three observations” rather than “fitness increased 4%.”

## Aerobic decoupling

Decoupling compares the pace/power-to-HR relationship across portions of a session. Research links durability patterns to performance in observational marathon data, but definitions vary and no universal cutoff predicts readiness, injury, or race result [E-DATA-02; S050].

**Use.** Descriptive trend on steady, sufficiently long, comparable runs with stable HR signal.

**Confounders.** Heat accumulation, dehydration, hills, stops, cardiac drift, pace changes, sensor error, caffeine, illness, and fueling.

**Do not use.** On intervals, stop-start urban routes, bad HR traces, or as a daily green/red gate.

## Session RPE

**Research.** A review of 36 studies found session RPE broadly practical and sufficiently valid/reliable for load monitoring, but it varies with context [E-DATA-01; S049].

**Use.** One post-session value can contextualize pace/HR and capture psychological/whole-session burden. Ask after a consistent delay if possible and allow “as expected / harder / easier.”

**Limits.** It is not an injury predictor, and retrospective values can be biased. A strength-session RPE is not directly equivalent to a run RPE.

## Workload displays

### Recommended descriptive views

- Run count, duration, distance for rolling 7/14/28 days
- Individual-run size and recent longest comparable run
- Quality, long-run, and lower-body-strength spacing
- Session RPE and symptom response
- Missingness and data-quality flags

### Avoid as automatic decisions

- ACWR safe zone
- Monotony/strain red line
- 10% weekly rule
- Long-run percent cap
- Training Readiness threshold
- Fixed decoupling threshold

A descriptive dashboard can still show these if their limitations are explicit and they never override symptoms or current instructions.

## Meaningful progress indicators

### High-value

- Adherence to the planned agreed rolling-cycle rhythm
- Symptom-free or symptom-stable consistency
- More aerobic duration at similar perceived effort under comparable conditions
- Stable/improving delayed response to known runs
- Quality-session control without excessive recovery cost
- Strength performance maintained/developed alongside running

### Moderate-value with controls

- Pace at similar HR/RPE on standardized route
- HR at similar pace under matched weather
- VO2max trend on same device
- Decoupling trend in comparable long easy runs

### Low-value in isolation

- One readiness score
- One HRV value
- One sleep stage breakdown
- One race prediction
- One “productive/unproductive” label

## Minimum data-quality metadata

For each metric store:

- `value`
- `unit`
- `observed_at`
- `source_device_or_manual`
- `algorithm_or_definition` when known
- `quality_status`: valid / suspect / missing / stale
- `reason`: optional flag

Derived comparisons should store the exact source sessions and inclusion criteria.

## Relevant inputs

- Forerunner 265 firmware/app version if available
- Sensor type and fit notes
- Zone configuration and threshold source
- Weather/route/elevation/surface
- RPE and symptoms
- Metric timestamps and missingness
- Standardized-run tags

## Evidence and policy links

- Evidence: E-WEAR-01–05, E-DATA-01–02, E-REC-03–04
- Policies: P001–P003, P005, P010, P015
- Sources: S039–S051
