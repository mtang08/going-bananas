# Targeted Search Log and Remaining Gaps: Periodization Extension

**Search completed:** 2026-11-11  
**Baseline research through:** 2026-11-10  
**Purpose:** Incremental search for planning authority, block lifecycle, operational session recipes, intensity calibration, tapering, and interruptions. This file does not reopen the baseline KB's completed reviews of aerobic progression, ACWR, wearable readiness, symptoms, concurrent lifting, fueling, or environment.

## 1. Baseline integration before searching

The public `running_coach_kb` on `main` was inspected first. Stable IDs `S001-S056`, existing evidence IDs, policies `P001-P018`, daily/weekly workflows, eight topic guides, and 15 evaluation cases were preserved. Public `manifest.json` hashes and raw files inspected on 2026-11-11 anchor the baseline because the accessible interface did not expose a trustworthy commit SHA. No SHA was inferred.

The audit found four material gaps:

1. no block-review operation or lifecycle contract;
2. no explicit planning-layer authority;
3. no structured recipe records; and
4. no compact calibration/race-transition workflow.

## 2. Databases, sites, and source types

Searches used PubMed/NCBI, PMC full text, publisher full text where accessible, Crossref/DOI metadata, Frontiers, PLOS, Springer/Sports Medicine, Sports Medicine - Open, Oxford Academic, and journal abstract pages. Citation chaining was used from major reviews and the baseline source registry. Search results were screened for direct relevance, population, design, access level, duplicate DOI/title/PMID, and whether the result changed an operational coaching decision.

Priority order was:

1. systematic reviews/meta-analyses and professional or methods consensus;
2. intervention and repeated-testing studies;
3. longitudinal/descriptive evidence;
4. methods papers and critical reviews; and
5. elite-coach or results-proven-practice descriptions, explicitly labeled as convention/practice.

## 3. Main query themes

Representative query concepts included:

- running periodization systematic review distance runners traditional block flexible;
- periodization theory evidence empirical validation athlete responsive planning;
- elite distance runner training periodization systematic review race-specific phase;
- endurance coach planning monitoring block review qualitative;
- field critical speed running reliability protocol systematic review;
- noninvasive threshold methods agreement reliability running talk test heart rate;
- critical speed D-prime running measurement application review;
- individual response repeated testing exercise training responder misclassification;
- high-intensity interval programming work recovery neuromuscular mechanical load;
- endurance taper meta-analysis volume intensity frequency duration;
- recreational marathon taper observational training data; and
- endurance detraining systematic review short-term cessation retained training.

## 4. Included incremental evidence

Sixteen new source records were added as `S057-S072`:

- periodization critique and responsive planning: S057-S058;
- elite distance sequencing and coach practice: S059-S061;
- tapering: S062-S063;
- field calibration/threshold/critical speed: S064-S066;
- repeated testing and response classification: S067-S068;
- interval-programming variables: S069-S071; and
- detraining/interruption: S072.

The evidence addendum records 12 new findings: `E-PER-02` through `E-PER-05`, `E-CAL-01` through `E-CAL-04`, `E-WKT-01`, `E-RACE-01` through `E-RACE-02`, and `E-TRANS-01`.

## 5. Access and verification notes

- Full text was inspected where marked in `source_registry.json`.
- S069 used the PubMed abstract plus available publisher text; S071 was abstract-only. Neither supports a precise recipe dose in this patch.
- Quantitative taper results were checked against the full PLOS/PMC article. Subgroup values are reported only as study findings and are not encoded as universal rules.
- Elite practice papers were used to describe common sequencing, not prove causality or transfer volume/density.
- A 2026 network meta-analysis/clarification concerning intensity distribution was considered but not made load-bearing because the existing KB already preserves mixed findings and the current workstream separates distribution labels from sequencing models. The patch does not claim a new universal polarized/pyramidal winner.
- Sources already represented by DOI, PMID, title, or URL in S001-S056 were not duplicated.

## 6. Evidence deliberately not converted into rules

The patch does **not** activate:

- a fixed 4-, 6-, or 8-week block duration;
- a mandatory cutback every N weeks;
- a universal long-run percentage cap;
- a race-result-to-zone conversion table;
- a required testing cadence;
- an exact critical-speed protocol for every athlete;
- a universal VO2 or threshold starter workout;
- a fixed taper length or percentage reduction;
- a day-by-day detraining or return formula; or
- a single-test definition of response/nonresponse.

Where numeric protocols appear in recipe records, each is classified as a studied protocol or coaching-conventional example with population and qualification. The record leaves personalization fields explicitly athlete-calibrated or `null`.

## 7. Remaining scientific gaps

1. **Explicit blocks in low-volume recreational runners.** No direct comparison was found between an explicit block entity and a simpler ongoing objective plus rolling plan for runners training 3–4 times per week.
2. **Block duration and completion.** No validated fixed duration or completion threshold generalizes across block objective, training age, frequency, and current tolerance.
3. **Consolidation/step-back cadence.** Planned lighter periods are common coaching practice, but a universal cadence or reduction is unsupported.
4. **Recipe starting doses.** Direct evidence is sparse for initial stride, hill, threshold, or VO2 doses in low-volume runners with concurrent lifting or impact-load constraints.
5. **Intensity-method interchangeability.** Threshold and critical-speed methods differ in constructs, protocols, and agreement. Correlation does not justify silent conversion.
6. **Critical-speed standardization.** Test count, trial duration, mathematical model, environment, and D-prime variability remain material implementation choices.
7. **Individual response.** Repeated testing reduces misclassification, but there is no universal number of observations sufficient for every metric or decision.
8. **Taper precision.** General strategy is supported; exact taper duration/reduction remains heterogeneous, and recreational marathon evidence is observational.
9. **Return after interruption.** Detraining direction is clearer than an individual return schedule. Symptoms, illness, retained activity, prior training, and current easy baseline must drive restoration.
10. **Low-token retrieval efficacy.** Token budgets and retrieval-miss detection are engineering evaluation questions, not sports-science findings. They require measured runtime tests.

## 8. Product and user decisions still required

- Whether the application exposes an explicit block to the user or stores it as lightweight metadata.
- Whether the second calendar week is visibly provisional and how approval works when provisional sessions become committed.
- Which intensity-anchor methods the product supports initially.
- Whether race priority uses A/B/C labels or plain-language meanings.
- What amount of current state must be available before the agent may propose a block transition.
- Whether preserving two strength sessions is a hard calendar constraint, a preferred constraint, or user-adjustable per phase.

## 9. Update triggers

Review this extension when:

- a strong direct study tests periodization/block structures in recreational runners;
- major threshold/critical-speed field methods are standardized or materially revised;
- new meta-analysis changes taper conclusions;
- the product captures enough repeated benchmark/execution data to test calibration behavior;
- evaluation reveals retrieval misses or excessive full-file loading; or
- the user changes running-versus-strength priority or calendar semantics.
