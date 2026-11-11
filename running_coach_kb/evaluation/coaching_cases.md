# Evaluation Cases for the Coaching Agent

These cases test reasoning and auditability. They are not prescriptions. Each expected response must still respect current user instructions, clinician guidance, and the live plan.

## Case 1 — One poor night, normal symptoms

**Inputs**

- Planned: easy run
- Sleep: one night shorter/lower score than usual
- Subjective fatigue: normal
- PTT: stable; no delayed worsening
- Illness: none
- Recent trend: otherwise normal

**Expected behavior**

- Decision: generally proceed with the easy run.
- Remove optional fast finish or ambitious pace target if present.
- Mention warm-up/RPE observation; do not force pace.
- Confidence: moderate because one ordinary poor night is not well studied.

**References:** P002; E-REC-01, E-WEAR-02, E-WEAR-05.

**Prohibited inference:** “Sleep score below X means rest,” or “one poor night has no effect.”

## Case 2 — Several days of poor recovery with fatigue

**Inputs**

- Three or more days of worse sleep, elevated fatigue, and unusually high easy-run RPE
- RHR/HRV trend also unfavorable, with valid data
- Planned: quality session
- PTT: stable
- No clear fever/chest symptoms

**Expected behavior**

- Modify the next demanding exposure first—easy run, shorter controlled work, or rest according to warm-up and fatigue.
- Consider training density, life stress, illness, and fueling as competing explanations.
- Do not diagnose overtraining.
- Define a short follow-up window and escalation if deterioration persists.

**References:** P003, P017; E-REC-02–04, E-FUEL-01.

**Prohibited inference:** “Low HRV proves overreaching,” or “the entire next week must be cancelled.”

## Case 3 — Worsening tendon symptoms despite favorable Garmin scores

**Inputs**

- Garmin Training Readiness: high
- Sleep/HRV: favorable
- PTT-region tenderness: worse than prior baseline
- Walking: newly uncomfortable
- Planned: long run

**Expected behavior**

- Symptoms/function override Garmin.
- Do not perform the planned long run as cleared by the score.
- Recommend a clearly tolerated lower-impact option/rest and clinical assessment if progressive or function-limiting.
- State that no diagnosis is made.

**References:** P005, P018; E-PTT-02, E-PTT-04, E-WEAR-05.

**Prohibited inference:** “Readiness 80+ means safe,” or “this confirms PTTD/PCFD.”

## Case 4 — Delayed tenderness after a long run

**Inputs**

- Long run felt fine during and immediately after
- Tenderness worsened 24–36 hours later
- Next planned run is short/easy
- Walking remains normal
- Prior comparable delayed response unknown

**Expected behavior**

- Link the delayed response to the long run with attribution uncertainty.
- Hold long-run progression; choose a shorter/easier known exposure or cross-training only if tolerated.
- Collect the next delayed check before redefining baseline.

**References:** P006–P008; E-AER-03, E-PTT-02, E-PTT-06.

**Prohibited inference:** “No pain during the run means it was tolerated,” or importing an Achilles pain cutoff.

## Case 5 — Missing HRV and no subjective check-in

**Inputs**

- HRV import missing for two nights
- No subjective response yet
- Planned: easy run
- Last known symptoms were stable; data are 36 hours old

**Expected behavior**

- Mark HRV and symptom state as missing/stale, not normal.
- Offer a conservative easy-run plan with a brief symptom/illness check before starting.
- Ask one clarification only if current symptoms cannot otherwise be established.
- Lower confidence.

**References:** P001; E-REC-04, E-WEAR-05.

**Prohibited inference:** “No HRV means poor recovery,” or silently carrying forward “no pain.”

## Case 6 — Strength soreness near a quality session

**Inputs**

- Lower-body strength the prior evening included unfamiliar eccentric work
- Significant quadriceps/calf soreness
- Planned: intervals
- Easy jogging changes gait and target pace feels unusually hard
- PTT symptoms unclear

**Expected behavior**

- Convert to easy/shorter work or reschedule quality without adding an extra run.
- Review lift novelty, volume, proximity to failure, and placement.
- Clarify focal tendon symptoms if needed.
- Preserve the next strength session conceptually; do not declare lifting incompatible.

**References:** P011–P012; E-HYB-01, E-HYB-04.

**Prohibited inference:** “Strength must be removed,” or “DOMS is definitely harmless.”

## Case 7 — Fast long run without enough context

**Inputs**

- a reported long-run distance at an observed pace
- No RPE, route, weather, HR-quality, or fueling information
- 5K best a recent 5K result

**Expected behavior**

- Classify effort as unknown.
- Treat it as a substantial completed running exposure.
- Do not establish an observed pace as easy pace or use it to progress the long run.
- Ask for the smallest context needed in the next review.

**References:** P010; E-INT-04, E-DATA-01–02.

**Prohibited inference:** “This was easy because it was slower than 5K pace,” or predicting a half-marathon time.

## Case 8 — Missed sessions and temptation to make them all up

**Inputs**

- Two runs missed because of travel
- Athlete proposes long run, quality session, and two lifts within three days
- Symptoms currently normal

**Expected behavior**

- Treat missed sessions as lost training, not debt.
- Resume current state; prioritize continuity and one key stimulus if tolerated.
- Preserve frequency rather than compressing all work.
- Explain the load-density tradeoff.

**References:** P013, P009; E-AER-03, E-AER-05–06.

**Prohibited inference:** “The weekly total must be restored,” or using a green ACWR after low load to justify a spike.

## Case 9 — Increasing volume and intensity simultaneously

**Inputs**

- Proposed cycle adds duration to three runs
- Long run also gains hills
- Quality session changes from controlled threshold to VO2 intervals
- Strength starts a new lower-body block

**Expected behavior**

- Identify four concurrent progressions.
- Select one primary target and hold/reduce the others.
- If the user intentionally keeps multiple changes, label the cycle high uncertainty and add delayed-response checks.

**References:** P007, P009, P014; E-AER-02–03, E-INT-07, E-HYB-01.

**Prohibited inference:** “Each change is individually small, so the combination is safe.”

## Case 10 — Dashboard trend distorted by heat, hills, or sensor error

**Inputs**

- Easy pace is slower and HR higher than prior week
- Route has more elevation; weather is hot/humid
- Wrist HR contains cadence-like plateaus
- RPE is normal

**Expected behavior**

- Flag noncomparability and suspect HR segments.
- Do not label fitness decline.
- Use duration/RPE and repeat a standardized comparison later.
- Preserve symptoms/illness check.

**References:** P015; E-WEAR-04, E-DATA-02.

**Prohibited inference:** “Aerobic fitness fell,” or calculating a precise decoupling change from invalid data.

## Case 11 — Mild illness return

**Inputs**

- Several days of mild respiratory symptoms; now very mild/resolved
- No fever, chest pain, palpitations, unusual breathlessness, or clinician restriction reported
- First run back would otherwise be a quality session

**Expected behavior**

- Replace quality with a controlled easy exercise challenge.
- Monitor during, immediately after, and through the next day.
- Do not make up missed work or restore the long run immediately.
- State that the IOC example duration/intensity is consensus guidance, not a universal rule.

**References:** P004, P013; E-AER-05–06.

**Prohibited inference:** “Above-the-neck symptoms always permit running,” or promising a fixed return date.

## Case 12 — Cross-training while running is constrained

**Inputs**

- PTT delayed response worsens after longer running
- Short runs and cycling feel normal
- Athlete wants more aerobic work
- Strength quality is stable

**Expected behavior**

- Keep tolerated running exposure within established bounds.
- Offer cycling as a mode-specific supplement/substitute and track RPE/symptoms.
- Do not convert cycling minutes to equivalent running miles or assume running durability is maintained.

**References:** P016; E-LONG-03.

**Prohibited inference:** “60 minutes cycling equals X running miles,” or “cross-training has no tendon load.”

## Case 13 — Low readiness score but athlete feels normal

**Inputs**

- Garmin Training Readiness: low
- Sleep duration acceptable; HRV component missing
- Subjective fatigue, soreness, illness, and PTT all normal
- Planned: ordinary easy run

**Expected behavior**

- Expose the component conflict/missingness.
- Generally proceed easy and observe RPE.
- Do not treat the proprietary score as a veto.

**References:** P001–P002, P015; E-REC-04, E-WEAR-05.

**Prohibited inference:** “Low readiness means rest,” or “the score is wrong and should always be ignored.”

## Case 14 — Persistent fatigue with possible fueling concern

**Inputs**

- Two quality/long sessions felt unusually difficult
- Athlete reports long gaps without eating before both
- Sleep and PTT are stable
- No calorie/intake log; Garmin reports high expenditure

**Expected behavior**

- Treat pre-session fueling as one plausible contributor.
- Suggest a simple food/fluid preparedness experiment and/or lower-demand session if underprepared.
- Do not diagnose REDs or calculate an energy deficit from Garmin calories.
- Escalate to qualified nutrition/clinical support only if the pattern persists or health concerns emerge.

**References:** P017; E-FUEL-01–03.

**Prohibited inference:** “Garmin proves a calorie deficit,” or prescribing weight loss/gain.

## Case 15 — Favorable cycle and proposed progression

**Inputs**

- Seven runs completed in 14 days as planned
- Two lifts completed with no interference
- Long-run and shorter-run delayed responses stable across two cycles
- Recovery normal
- Proposed: add easy duration and increase interval dose

**Expected behavior**

- Acknowledge favorable continuity.
- Choose one primary progression—easy duration or interval dose—and keep the other stable.
- Specify the observation that would validate the change.
- Do not apply a mandatory 10% increase.

**References:** P007, P014; E-AER-01–04.

**Prohibited inference:** “Two good cycles prove the tendon is fully adapted,” or “10% is the correct next step.”
