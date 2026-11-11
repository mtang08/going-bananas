# Search Log, Disagreements, and Research Gaps

## Search status

- **Search date:** 2026-11-10
- **Evidence covered through:** 2026-11-10
- **Method:** targeted critical literature review and source verification; **not** a registered or exhaustive systematic review
- **Primary aim:** find the strongest, most directly applicable evidence for auditable coaching decisions, then test popular claims and identify where evidence does not support an operational threshold

## Sources and search approach

The search used PubMed/PMC records, publisher pages, professional consensus/guideline documents, and targeted web discovery to locate recent or seminal work. For key quantitative claims, original studies were preferred and review-level generalizations were checked against study details when accessible. Manufacturer material was used only to describe proprietary Garmin metrics, not as independent evidence of coaching benefit.

### Priority order

1. Systematic reviews/meta-analyses and professional consensus/clinical guidance
2. Randomized or controlled trials
3. Prospective longitudinal cohorts, especially recreational runners and wearable-recorded training
4. Device-validation studies
5. Methods papers and critical analyses
6. Descriptive elite practice or expert viewpoints when stronger outcome evidence was unavailable
7. Coaching convention, explicitly labeled

### Population priority

- Recreational runners and hybrid/concurrent trainees
- Mixed-sex/non-elite populations where available
- Diagnosed PTT/PTTD populations for symptom-specific questions
- Elite endurance evidence only when the population mismatch was explicit

## Major search concepts

Searches combined terms in the following groups. Exact syntax varied by database/site.

### Aerobic progression and injury

- running injury training parameters systematic review
- 10 percent rule novice runners randomized trial
- running single-session distance spike Garmin cohort
- acute chronic workload ratio running critique prospective cohort
- training monotony strain running injury
- return to sport acute respiratory illness athlete consensus

### Intensity distribution and methods

- polarized versus pyramidal training meta-analysis recreational runner
- threshold training recreational runners randomized
- endurance training intensity distribution session goal time in zone
- Zone 2 definition first lactate threshold expert consensus
- Norwegian single threshold double threshold elite acute split session
- running intervals 4 x 4 short intervals 10-20-30 meta-analysis
- strides hill sprints running performance dose
- block periodization endurance meta-analysis

### Long runs and cross-training

- long run weekly volume half marathon marathon performance injury
- long run percentage weekly mileage evidence
- cycling substitution running VO2max randomized
- cross training runners systematic review meta-analysis

### Concurrent strength and mobility

- concurrent endurance resistance training interference meta-analysis
- running economy heavy resistance plyometric combined meta-analysis
- exercise prevention running injury systematic review randomized
- same day versus separate day concurrent training session order

### Posterior tibial tendon

- posterior tibial tendon dysfunction exercise randomized trial systematic review
- posterior tibial tendinopathy running return to sport
- progressive collapsing foot deformity consensus terminology
- PTT orthoses systematic review
- intrinsic foot exercise systematic review
- tendinopathy exercise dose load frequency meta-analysis
- Achilles pain monitoring model continued sport randomized
- isometric versus isotonic tendinopathy systematic review

### Recovery and wearables

- athlete sleep consensus sleep loss endurance performance meta-analysis
- HRV guided endurance training randomized meta-analysis
- subjective feedback guided running training trial
- training readiness systematic review athlete
- Garmin Forerunner 265 VO2max race prediction validation
- Garmin sleep staging HRV wrist heart rate validation
- session RPE validity reliability review
- aerobic decoupling pace heart rate heat confounding

### Fueling and energy availability

- IOC REDs 2023 consensus low energy availability
- carbohydrate endurance training position statement
- protein resistance training meta-analysis concurrent exercise
- low energy availability athlete performance systematic review

## Verification and access

Each source in `../references/source_registry.json` has:

- stable `source_id`;
- full citation and title;
- DOI, PMID, and/or PMCID when available;
- stable URL;
- source type and population/scope;
- access level checked for this package;
- verification date and notes.

Access labels include:

- **full text verified:** full article or official full consensus text inspected;
- **abstract verified:** bibliographic record and abstract inspected, but full text was unavailable or not checked;
- **manufacturer documentation verified:** official product description only;
- **citation/summary verified:** limited access; no quantitative claim should exceed what the accessible record supports.

No search-engine snippet was used as evidence. No copyrighted paper archive is included.

## Material disagreements and how the package handles them

### Polarized versus pyramidal training

- A 2024 meta-analysis found a small VO2peak advantage for polarized training but not clear advantages across several performance outcomes [E-INT-03; S011].
- A 2025 individual-participant network meta-analysis found no overall polarized-versus-pyramidal difference and suggested recreational athletes may respond at least as well to pyramidal training [E-INT-02; S010].
- A small recreational trial found both polarized and between-threshold programs improved, without a significant primary between-group difference [E-INT-01; S009].

**Resolution:** both are viable; no mandatory 80/20 or polarized default. Low-volume session-count ratios are especially unstable.

### Training load and injury

- A large wearable cohort associated single-session distance spikes with overuse injury [E-AER-03; S003].
- A broad prospective systematic review found inconsistent associations across training parameters [E-AER-02; S002].
- ACWR critiques show conceptual/statistical problems, and a 2026 cohort produced a fragile small association [E-AER-04; S004–S005].

**Resolution:** flag novel individual runs, but do not establish a universal cutoff or causal safe zone.

### Strength and injury prevention

- Strength/plyometric methods can improve running economy [E-HYB-02; S025].
- Pooled exercise programs do not show a clear universal running-injury reduction, though one supervised trial was favorable [E-HYB-03; S026–S027].

**Resolution:** preserve strength for hybrid goals and possible economy/performance benefits; do not promise injury prevention.

### PTT exercise and broader tendon loading

- PTT-specific trials are small, staged, and co-intervened [E-PTT-01–02].
- Broader tendon-dose evidence favors adequately loaded, less-than-daily resistance patterns but excludes PTT [E-PTT-03].
- Isometrics show no consistent superiority in other tendons [E-PTT-07].

**Resolution:** support progressive loading as a clinician discussion, retain tolerated isometrics/short-foot if useful, and leave numeric dose/return thresholds unset.

### HRV/readiness guidance

- Some HRV-guided studies show fewer hard sessions or favorable outcomes, while pooled performance superiority is small/inconsistent [E-REC-03].
- One tiny subjective-guided trial was favorable [E-REC-02].
- Readiness constructs lack a stable validated algorithm [E-REC-04].

**Resolution:** use multi-day trends and subjective information together; no single-night or proprietary-score veto.

## Athlete questions that materially affect recommendations

Keep this list short and action-oriented:

1. What does the actual recent 6–12-week running export show for frequency, volume, long-run size, intensity, terrain, and illness interruption?
2. What is the repeatable delayed symptom/function response at 0–2 hours, next morning, and later key runs?
3. Has a clinician assessed the posterior-tibial-region symptoms, and are there diagnosis-specific restrictions or loading criteria?
4. What lower-body strength exercises/doses reliably cause soreness or calf/foot loading, and what are the current strength/hypertrophy priorities?
5. Is any target race confirmed, and on what date?
6. Which Garmin fields and quality metadata are actually available in the export/API path?

## What imported data can resolve

- Whether the stated rebuilding baseline is accurate
- Adherence to the currently agreed running cadence
- Distribution of duration/distance across runs
- Recent longest comparable run and session novelty
- Quality/long-run placement around strength sessions
- Pace/HR patterns under tagged route/weather conditions
- Missingness and plausibility of wrist HR, sleep, HRV, and readiness components
- Whether recommendations were followed and how session RPE/symptoms responded

Imported activity data cannot diagnose PTT, determine energy availability, or prove causation.

## Questions for a clinician or sports dietitian

- What is the diagnosis/stage, if any, for the posterior-tibial-region symptoms?
- Are there clinical findings that change impact, orthosis, loading, or return-to-running decisions?
- What functional/loading criteria should govern progression for this individual?
- Do progressive symptoms, swelling, weakness, or foot-shape concerns require imaging or specialist referral?
- If persistent fatigue/health signs or nutrition concerns emerge, is formal REDs/energy-availability assessment indicated?

## Literature gaps that remain unresolved

1. PTT-specific return-to-running criteria and pain-monitoring thresholds.
2. Optimal PTT resistance mode, load, frequency, and progression for active runners.
3. How running volume, faster running, hills, calf strength, and footwear interact for PTT symptoms.
4. A validated injury-risk model for individual recreational runners using wearable data.
5. Direct trials of progression strategies in already-active low-volume runners returning after illness.
6. Optimal intensity distribution at the agreed rolling-cycle run count with two meaningful strength sessions.
7. Direct evidence for minimum effective stride/hill doses in tendon-limited runners.
8. Long-run percentage caps or distribution rules as injury-prevention tools.
9. Best concurrent-training schedule for preserving running, hypertrophy, maximal strength, and explosive performance in trained hybrid athletes.
10. Independent intervention evidence that Garmin Training Readiness improves decisions or outcomes.
11. Stable cross-device validity for current firmware versions of wrist HR, HRV, sleep, VO2max, and race prediction.
12. Whether consumer-derived decoupling thresholds improve coaching outcomes.
13. Practical nutrition screening that detects problematic low energy availability without excessive burden or false diagnosis.
14. Long-term comparisons of block versus mixed periodization in recreational hybrid runners.

## Update triggers for this knowledge base

Review and update the package when:

- a new PTT clinical guideline or return-to-running trial appears;
- high-quality trials validate wearable-guided coaching decisions;
- Garmin materially changes metric definitions/algorithms;
- new large prospective running-load studies replicate or contradict single-session findings;
- the athlete receives a diagnosis or clinician criteria;
- the actual Garmin export changes the assumed training context;
- the user confirms a race date or changes strength/running priorities.
