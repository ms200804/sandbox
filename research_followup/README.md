# Research Follow-Up

Agents flag research gaps they can't fill from CourtListener — cases that need Lexis/Westlaw, state court opinions CL doesn't have, unpublished district court decisions, or issues where CL's citation analysis isn't definitive enough.

## How It Works

1. **Agents generate notes here.** When the adversarial sim, case research, or citation extractor hits a gap — a case it can't verify, a doctrinal question CL can't answer, a cite that needs Shepardizing properly — it writes a follow-up note here.

2. **You ask Claude to check for new notes.** On Mac: "check any new research follow-up." Claude reads this folder, summarizes what needs to be looked up, and gives you a clean list to run through Lexis AI.

3. **You run it through Lexis AI** and paste back results or confirm the cite is good/bad.

4. **Results feed back into the library.** Claude updates the research library with the confirmed information.

## File Format

Each follow-up note is a markdown file named by source:

```
research_followup/
├── hubbard_vacate_lien.md          ← from that brief's sim/extraction
├── tvpa_fee_shifting.md            ← from a research query
└── steiner_negligent_supervision.md
```

Each file contains:

```markdown
# Research Follow-Up: [source]
Generated: [date]
Status: pending | done

## Needs Lexis/Westlaw Verification
- [ ] *In re Cooperman*, 83 N.Y.2d 465 (1994) — confirm still good law, check for recent NY cases limiting or extending
- [ ] *Butler v. Sequa*, 250 F.3d 171 (2d Cir. 2001) — need full text, CL only has metadata

## Gaps CL Couldn't Fill
- [ ] Are there WDTx or 5th Cir. cases specifically addressing vacatur of charging liens in TVPA cases? CL returned nothing. May be unpublished.
- [ ] State court: any TX state cases on subordination of attorney liens to litigation funding? CL state coverage is thin.

## Needs Proper Shepardizing
- [ ] 868 F.2d 684 (Villanueva) — CL shows forward citations but can't confirm treatment status. Run through KeyCite/Shepard's.
```

## Workflow Summary

```
Agents find gaps → write notes here → git push
You: "check research follow-up" → Claude reads, summarizes
You run Lexis AI → paste back or confirm
Claude updates library → marks notes as done
```
