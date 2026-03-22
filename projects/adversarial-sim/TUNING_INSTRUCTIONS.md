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

## Order of Operations

1. Rename `strategist.md` → `pragmatic.md`, rewrite the prompt
2. Add the "affirmatively clear" language to all 6 Phase 1 prompts (including the new pragmatic)
3. Update `reviser.md` with the draft-language output expectations
4. Update `sim.py` — change PHASE1_AGENTS list, add research gap extraction after Phase 2
5. Update `scenarios/TEMPLATE.md` with the Agent Instructions guidance
6. Test with the same Hubbard scenario to compare output
