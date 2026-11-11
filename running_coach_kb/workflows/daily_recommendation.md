# Workflow: Daily Recommendation

## Objective

Turn the current plan, recent app-computed metrics, a 10–20-second subjective check-in, and prior recommendation outcomes into one auditable **proceed / modify / rest / seek-clinical-input** decision. Preserve the currently agreed run and strength frequency unless current instructions change them.

## Required loading

1. `COACHING_GUIDE.md`
2. Current athlete/app summary and today’s plan
3. This workflow
4. Relevant topic guide(s)
5. Matching records from `policies/coaching_policy_candidates.json`
6. Evidence/source files only when the recommendation remains disputed or needs a deeper explanation

Do not load every topic by default.

## Inputs

### Minimum live inputs

- Planned session: mode, purpose, duration/distance, intensity intent, terrain if relevant
- Last completed run/lift and timestamp
- Current posterior-tibial-region symptom trend and daily function, or `null`
- Delayed response to the last run, or `unknown`
- Illness/systemic symptoms and red flags, or `null`
- Perceived fatigue/recovery today
- Interfering lower-body soreness
- Any current clinician instruction

### Useful imported/derived context

- Completed versus planned sessions over the rolling 14-day cycle
- Recent longest comparable run and novelty flag
- Quality/long-run/lower-body-strength proximity
- Sleep duration trend, overnight HRV trend/status, resting-HR trend, and Training Readiness components—not just the composite
- Route/weather/sensor-quality flags
- Prior recommendation and whether it worked

Every observation must carry `observed_at`, source, and quality/status. Missing is `null`, not zero or normal.

## Quality checks

1. **Timestamp check:** Is the symptom check after the most recent relevant exposure? Is Garmin data from last night or older?
2. **Plausibility check:** Flag impossible duration, pace, heart rate, or sleep values; do not “fix” them silently.
3. **Comparability check:** Before interpreting pace/HR, confirm route, hills, heat/humidity, surface, device/sensor, effort, fueling, and fatigue are sufficiently similar.
4. **Classification check:** Store whether intensity came from session goal, RPE, talk test, HR zone, pace, or time in zone.
5. **Delayed-response check:** A symptom-free finish does not establish tolerance when symptoms have historically worsened after the session.

## Decision sequence

### Step 1: Is routine coaching inappropriate?

Use P018 and P004/P005 as relevant. Progressive loss of function, concerning swelling/weakness/deformity, acute trauma, cardiopulmonary/systemic illness signs, or a clinician restriction should stop routine optimization. The output is clinical input plus clearly tolerated alternatives, not a diagnosis.

### Step 2: Are symptoms/function deteriorating?

Use P005 and P006. Worsening PTT-region symptoms or delayed response outrank favorable sleep, HRV, or Training Readiness. Modify the mechanical exposure; do not copy an Achilles numeric pain cutoff.

### Step 3: Is recovery deterioration isolated or accumulated?

- One poor night with normal symptoms and normal recent trend → P002: usually retain easy training; use a warm-up decision for demanding work.
- Several agreeing poor-recovery days → P003: modify the next demanding exposure and investigate illness, load, life stress, and fueling.
- Missing wearable field with normal subjective/function data → P001: do not cancel automatically.

### Step 4: Does today create a scheduling/load conflict?

Use P007–P014. Count the long run, quality session, lower-body lifting, hills, strides, and plyometrics by actual mechanical/physiological cost. Do not compress missed work or increase volume and intensity together without explicitly accepting higher uncertainty.

### Step 5: Choose the smallest effective action

**Proceed** when symptoms/function are stable, no meaningful illness signal exists, recovery is acceptable, and the planned exposure resembles tolerated work.

**Modify** when the plan’s purpose can be preserved by reducing duration, removing intensity/hills, changing terrain, moving the session, altering strength dose, or substituting low-impact aerobic work.

**Rest** when systemic recovery or symptoms make even the fallback inappropriate, or rest is the clearest way to protect the next priority session.

**Seek clinical input** when P018 applies.

Do not add a replacement session that changes the agreed frequency.

## Alternatives by intent

- Easy aerobic intent → shorter/easier run; flat route; low-impact aerobic mode; rest
- Quality intent → controlled reduced reps; easy run; move quality without adding a session
- Long-run intent → repeat last tolerated duration; shorten; split aerobic stimulus with cross-training
- Strength intent → preserve full-body training but adjust provocative lower-body exercise, volume, or proximity to failure; do not default to deleting lifting

## Clarification rule

Ask at most one immediate question when it blocks a safe or meaningful choice—for example, whether “pain” is worsening during walking versus a stale note. Otherwise provide a conservative recommendation, state the missing field, and lower confidence.

## Daily output contract

```yaml
decision: proceed | modify | rest | seek_clinical_input
proposed_session:
  mode: string
  purpose: string
  duration_or_structure: string | null
  intensity_instruction: string
  terrain_or_equipment: string | null
change_from_plan: string
short_rationale: string
references:
  policy_ids: [Pxxx]
  evidence_ids: [E-xxx-xx]
confidence:
  evidence: high | moderate | low | insufficient
  athlete_applicability: high | moderate | low
  decision: high | moderate | low
missing_or_stale_inputs: [string]
follow_up_observation:
  what: string
  when: string
audit:
  data_through: ISO-8601 timestamp
  prior_recommendation_outcome_used: string | null
  proposed_changes: [string]
```

## Worked reasoning patterns

- **Poor sleep, otherwise normal:** proceed easy; remove optional fast finish; note P002; observe RPE/warm-up.
- **Great readiness, worse tendon:** modify or rest based on function; P005; collect delayed response.
- **Fast reported long run, no RPE/terrain:** do not relabel easy pace; P010; treat as a large completed exposure.
- **Strength soreness before intervals:** warm-up assessment; convert to easy if gait/quality altered; P012; review lift dose/placement.
- **No HRV import:** do not infer poor recovery; P001; use symptoms, sleep duration, fatigue, and plan context.
