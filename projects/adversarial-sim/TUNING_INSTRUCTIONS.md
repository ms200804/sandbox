# Adversarial Sim — Post-First-Run Tuning

Based on the Hubbard lien motion test run. Apply these changes to the prompts, orchestrator, and template.

## 1. Rewrite `prompts/strategist.md` as Pragmatic Review

The current "economic realist" lens overlaps too much with Opposing Counsel and Judge. Refocus as a senior partner red-pen review.

**New role:** "Pragmatic Review" — a pragmatic senior litigator reviewing the brief before it goes out the door.

**New lens:** Not economics or incentives. Instead:
- Is the requested relief actually what the client needs? Are we asking for too much (inviting objections) or too little (leaving value on the table)?
- Is there a simpler path to the same result that we're overcomplicating?
- Does the tone match the audience? (Magistrate vs. Article III judge, motion vs. opposition, etc.)
- Are we picking fights we don't need to pick? (e.g., the White Lilly footnote, the for-cause factual allegations)
- Would I sign this? What would I change before it goes out?

**Keep the output format** (Top 3 Weaknesses, Strongest Attack Vector, plus a new "Filing Recommendations" section).

**Rename the file** from `strategist.md` to `pragmatic.md`. Update `sim.py` PHASE1_AGENTS list accordingly.

## 2. Add "affirmatively clear sound sections" to ALL Phase 1 prompts

Every Phase 1 prompt should include this near the end of its Rules section:

```
- If you evaluate a section or argument and find it SOUND, say so explicitly:
  "Section III is well-constructed and I have no material concerns." Do not
  default to finding weaknesses in every section. Silence on a point means
  you didn't evaluate it, not that it passed. Affirmatively clearing strong
  sections is as valuable as flagging weak ones — it tells the attorney
  where NOT to spend revision time.
```

This prevents convergence bias where all agents recommend cutting the same section simply because it's easier to flag than to clear.

## 3. Update `prompts/reviser.md` — produce draft language, not just instructions

Add to the Reviser's "Your Task" or "Revision Principles" section:

```
## Output Expectations

- For NEW sections you recommend adding (e.g., a magistrate authority section,
  a due process paragraph), write the FULL TEXT ready to paste into the brief.
- For STRUCTURAL changes (reordering sections, moving arguments), produce the
  revised section headings and transition language between sections.
- For LANGUAGE changes (replacing phrases throughout), show before and after
  for each instance, or provide a find-and-replace table.
- The attorney should be able to incorporate your revisions by pasting your
  output, not by reconstructing what you meant from instructions. Your output
  is a revision memo with draft text, not an outline of suggestions.
```

## 4. Wire Attacker research gaps to `research_followup/`

In `sim.py`, after Phase 2 completes, parse the Attacker output for research gaps and write them to the research follow-up folder.

**Implementation:** After `run_phase2()` returns, scan the attacker response for lines indicating research needs:
- "Research needed"
- "No [circuit] authority"
- "Check whether"
- "Verify the * citation"
- "Look for [court] decisions"

Write matching items to `research_followup/[scenario_name].md` in the standard follow-up format:

```markdown
# Research Follow-Up: [scenario name]
Generated: [date]
Status: pending
Source: adversarial sim

## Research Gaps from Attacker Report
- [ ] [extracted gap item]
- [ ] [extracted gap item]
```

This connects the sim output to the research pipeline so gaps don't get lost.

## 5. Update `scenarios/TEMPLATE.md` — emphasize Agent Instructions

Add a note to the Agent Instructions section in the template:

```markdown
## Agent Instructions
[This is the highest-ROI section of the scenario file. Generic scenarios
produce generic output. Specific instructions produce specific analysis.

Good instructions include:
- Procedural posture details the agents need (e.g., "this is before a
  Magistrate Judge on pretrial referral, not full consent")
- Which side Opposing Counsel should argue as, and what their best
  arguments are
- Legal framework that's already been established (e.g., "the Court has
  already applied NY law to the fee agreement — that's settled")
- Anything unusual about the case that agents might miss from the brief
  alone (e.g., "BF is not a party — they were denied intervention")

Bad instructions: "Be thorough." "Focus on the key issues." These add
nothing. The agents already do this.]
```

## 6. Embed tone guide rules in `prompts/reviser.md`

Add a "Writing Style" section to the Reviser prompt with these rules from Matt's tone guide (`tone_references/tone_guide.md` in the claude repo):

```
## Writing Style

Match this voice when producing draft language:
- CRAC structure (Conclusion, Rule, Application, Conclusion)
- Anglo-Saxon word preference over Latinate ("show" not "demonstrate")
- Em-dashes with no spaces — max one pair per paragraph
- Selective quoting: paraphrase the holding, then quote only the key phrase
- No gratuitous definitions (don't define terms you only use once)
- Oxford comma always
- Year-as-parenthetical gets commas: "In *Chambers*, 501 U.S. 32 (1991), the Court..."
- Aggressive but precise — never bombastic or overwrought
- Cite every sentence in a Statement of Facts
- Plural: "data are," "media are"
```

If the tone guide is updated in the claude repo, update this section to match. The tone guide changes rarely.

## 7. Citation verification of sim output

After Phase 2 completes, run the citation extractor on ALL output files (phase1_*.md, phase2_*.md). For every citation the agents produced, attempt to verify against CourtListener.

Write results to `research_followup/[scenario_name].md`:

```markdown
## Citation Verification (from sim output)
- [x] 501 U.S. 32 — Chambers v. NASCO — verified ✓
- [x] 868 F.2d 684 — Villanueva v. CNA — verified ✓
- [ ] 743 F.3d 218 — NOT FOUND IN CL. Cited by: opposing_counsel.
      May be hallucinated. Verify on Lexis before relying on it.
- [?] 302 A.D.2d 183 — Schneider — found in CL but CL state coverage
      is spotty. Confirm on Lexis.
```

**Important:** CL is not perfect. A case NOT being in CL doesn't necessarily mean it's hallucinated — CL has gaps, especially for:
- State court opinions (NY, TX, CA coverage varies)
- Unpublished district court opinions
- Very recent opinions not yet indexed

So the verification output should use three statuses:
- **verified** — found in CL with matching citation and case name
- **not found** — not in CL. Could be hallucinated OR a CL gap. Flag for Lexis.
- **partial** — found but metadata doesn't fully match (e.g., different citation format, different case name spelling). Flag for manual confirmation.

All "not found" and "partial" entries go into the research follow-up for manual Lexis verification on the next round.

## 8. Auto-research from sim gaps

When the Attacker identifies research gaps (e.g., "no Fifth Circuit authority on X"), automatically run a CL search before writing the follow-up note. Three outcomes:

- **CL finds relevant cases** → save to library, note in follow-up as "resolved by CL — review for quality"
- **CL finds nothing** → write follow-up note for Lexis
- **CL finds tangentially related cases** → save to library, note as "partial — may need Lexis for direct authority"

This means the follow-up folder only contains genuine gaps that CL can't fill. Reduces manual Lexis work to what actually needs it.

## 9. Confidence scoring in the research library

Add a `confidence` field to library entries in `library.py`. Score based on:

- **high**: binding authority found in target circuit, adverse authority checked, multiple confirming cases, citations verified
- **medium**: persuasive authority only, OR binding authority found but not shepardized/verified, OR results only from CL (state court gaps possible)
- **low**: few results, narrow CL coverage for this jurisdiction/topic, not verified against Lexis

The Slack bot and sim agents should surface confidence when using library data: "I have cases on this but confidence is medium — CL-only, haven't checked for adverse authority."

The confidence score should upgrade when:
- Matt confirms cases via Lexis ("that's good law" → bump to high)
- Shepardize results come back clean
- Additional research fills gaps

And downgrade when:
- Cases are old and haven't been re-checked
- Staleness timer triggers (existing 90-day mechanism)

## 10. Matter-specific research tagging

Add an optional `matters` field to library entries:

```json
{
  "category": "tvpa",
  "topic": "charging_liens",
  "matters": ["hubbard_goedinghaus_tvpa"],
  ...
}
```

When running a sim for a specific matter, the orchestrator pulls all research tagged to that matter and injects it as context for the agents. Over time each matter builds a curated research base.

The Slack bot should tag research to a matter when context makes it obvious (e.g., research done in a thread about Hubbard gets tagged to hubbard_goedinghaus_tvpa).

## 11. Calibrate procedural risk to real-world practice

The first run over-weighted theoretical procedural objections that rarely happen in practice (e.g., "motion to strike the footnote"). The agents should distinguish between:

- **Real threats**: arguments opposing counsel would actually make because they're worth the attorney time and have a meaningful chance of affecting the outcome
- **Paper threats**: technically available procedural moves that no practicing lawyer would waste time and credibility on (motions to strike footnotes, motions for sanctions over citation format, etc.)

Add to `prompts/opposing_counsel.md`:

```
- Distinguish between arguments you would ACTUALLY MAKE (worth the time,
  credibility cost, and page space) and arguments that are technically
  available but no real lawyer would bother with. A motion to strike a
  footnote burns goodwill with the judge and almost never succeeds.
  Focus your attacks on things that move the needle, not procedural
  theater. If a procedural objection is only a paper threat, say so:
  "BF could theoretically move to strike, but this is not a realistic
  risk — no judge would grant it and the motion itself signals weakness."
```

Add similar language to `prompts/judge.md`:

```
- When evaluating risks, calibrate to real-world practice. Don't flag
  theoretical procedural objections that would never actually be raised
  or granted. A footnote citing a collateral proceeding is not going to
  generate a successful motion to strike. Focus on what would actually
  concern you at oral argument or in chambers, not academic risks.
```

## 12. Opposing Counsel calibration — evaluate your own attacks

From the first run review: OC generates attacks but doesn't weigh how well they hold up against obvious counters. Add to `prompts/opposing_counsel.md`:

```
- For each attack, assess its SURVIVABILITY — how well does it hold up
  when the other side responds with the obvious counter? An attack that
  sounds devastating in isolation but collapses under a one-sentence
  rebuttal is not a strong attack. Rate your own attacks honestly.
- Factor in the adversary calibration. If the opponent is a bankrupt
  pro se party, don't generate sophisticated counter-proposals they'd
  never articulate. Flag when an attack is "smart but unlikely given
  this opponent."
- CRITICAL: Flag when preemptively rebutting one of your attacks would
  HURT the movant. If you identify a clever argument the other side
  would never think of on their own, say so: "This is a strong attack
  but unlikely to be raised by this opponent. Do NOT address it
  preemptively — you'd be giving them a roadmap." This is as important
  as identifying the attack itself.
```

## 13. Practice-knowledge gaps in agent analysis

The agents lack practice knowledge that experienced litigators have. Examples from the first run:

- Intervention for charging liens is almost never granted outside the 5th Circuit contingency-interest exception. The agent treated "BF is not a party" as devastating when in practice, liens are preserved on the docket without party status — that's how it works in most jurisdictions.
- "Departing counsel gets an interest but doesn't get to tank the case" is a basic principle of NY lien law that the agent didn't weigh properly.
- The agent gave equal weight to all OC attacks without distinguishing between arguments that sound good in a brief vs. arguments a judge would actually credit.

This is harder to fix through prompting alone — it's the gap between knowing doctrine and knowing practice. Two mitigations:

1. Add to ALL Phase 1 prompts: "Distinguish between arguments that sound good on paper and arguments a judge would actually credit in the real world. A creative doctrinal argument that no court has ever adopted is less threatening than a simple factual argument the judge can verify from the docket."

2. The Pragmatic Review agent (replacing Strategist) should specifically check: "Are any of the other agents' findings based on theoretical risks rather than practical ones?"

## Order of Operations

1. Rename `strategist.md` → `pragmatic.md`, rewrite the prompt
2. Add the "affirmatively clear" language to all 6 Phase 1 prompts (including the new pragmatic)
3. Update `reviser.md` with draft-language output expectations + tone guide rules
4. Update `sim.py` — change PHASE1_AGENTS list, add post-Phase-2 citation verification and research gap extraction
5. Update `library.py` — add confidence scoring and matter tagging fields
6. Update `scenarios/TEMPLATE.md` with the Agent Instructions guidance
7. Commit all changes
8. Test with the same Hubbard scenario to compare output against the first run
