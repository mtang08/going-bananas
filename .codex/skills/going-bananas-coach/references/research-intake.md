# Research intake

Routine training decisions use snapshot KB excerpts. This reference applies only when a concrete missing or disputed claim, the user, or a higher-priority verification requirement causes outside research.

1. Name the question and inspect the relevant existing source/evidence records, not the entire corpus. Reuse existing IDs for duplicate DOI/PMID/URLs.
2. Record the question, search/retrieval date, direct source URL/identifier, access actually obtained, finding, limitations, and proposed effect on coaching in `running_coach_kb/research/coaching_web_intake.md`. Never include athlete-specific training or health data in the public KB.
3. A search snippet or inaccessible paper is a candidate, not verified evidence. Label it pending verification; do not turn it into a policy or invent an evidence ID. For a duplicate, record that the KB already covered the finding.
4. To promote verified new evidence, update the source registry and relevant evidence/topic record together, distinguishing research from coaching inference. Preserve existing IDs and source provenance. Add a focused regression case if the change alters coaching behavior.
5. Refresh hashes/byte sizes for changed KB files and give the package a new version; preserve historical intake provenance. Run the KB integrity/retrieval tests. Take a fresh coaching snapshot after KB changes before submitting a proposal, because the evidence digest may have changed. Never rewrite an old proposal's evidence linkage.

Do not bypass a failed verified-KB load with live search. Report the failure. Keep unverified intake notes out of runtime coaching evidence until reviewed and promoted. Technical OpenAI/product documentation belongs in workflow documentation, not the running evidence registry.
