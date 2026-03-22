# Adversarial Simulation — Two-Phase Argument Stress-Testing

## Overview
Feed in a draft argument or legal position — from a casual phone description to a full draft brief. The system runs it through independent adversarial pressure from six perspectives, synthesizes the results into a prioritized vulnerability report, and produces a revised argument with an opposition playbook.

## Architecture: Two Phases

### Phase 1: Parallel Attack Surface (6 agents, independent, no cross-talk)

Six agents analyze the argument simultaneously. They never see each other's output, preventing convergence and ensuring independent weakness discovery.

| Agent | Lens | Finds |
|---|---|---|
| **Hostile OC** | "How do I win this motion?" | Actual attacks opposing counsel will make — case distinctions, procedural traps, factual gaps. Calibration: standard / aggressive / elite. |
| **Skeptical Judge** | "Why should I grant this?" | Missing elements, conclusory assertions, standard-of-review problems, threshold issues (standing, jurisdiction, ripeness) |
| **Appellate Panel** | "Is the doctrine clean?" | Doctrinal errors, circuit splits, sloppy framing, preservation issues, standard of review |
| **Economic Realist** | "What are the real incentives?" | Settlement leverage, cost/benefit, remedy collectability, insurance angles, policy arguments |
| **Procedural Tactician** | "What happens next?" | Timing, sequencing, waiver risks, preservation for appeal, opponent's procedural options, discovery needs |
| **Record Auditor** | "Can you prove this?" | Evidentiary gaps, unsupported factual assertions, authentication issues, pleading sufficiency (Iqbal/Twombly), MSJ readiness |

Each outputs: top 3 weaknesses, strongest single attack vector, and role-specific analysis.

### Phase 2: Sequential Synthesis

| Agent | Job |
|---|---|
| **Destroyer** | Reads ALL Phase 1 output. Ranks weaknesses by severity (fatal/serious/minor). Identifies compound weaknesses (same issue flagged by multiple agents). Produces prioritized vulnerability report with triage recommendations. |
| **Refiner** | Takes original argument + Destroyer's report. Revises to preempt top threats. Flags unfixable issues. Produces opposition playbook ("They'll argue X → Our response Y" with strength ratings). |

### Flow
```
Input: argument + case context + forum
  │
  ├─→ [Hostile OC]            ─┐
  ├─→ [Skeptical Judge]        ─┤
  ├─→ [Appellate Panel]        ─┤  Phase 1 (parallel, 6 agents)
  ├─→ [Economic Realist]       ─┤
  ├─→ [Procedural Tactician]   ─┤
  ├─→ [Record Auditor]         ─┘
  │                              │
  │         ┌────────────────────┘
  │         ▼
  ├─→ [Destroyer]  → vulnerability report     Phase 2 (sequential)
  │         │
  │         ▼
  └─→ [Refiner]   → revised argument + opposition playbook
           │
           └─→ (optional: feed back into Phase 1 for another pass)
```

## Usage

```bash
# Full simulation — 6 parallel agents + synthesis (Opus by default)
python sim.py scenarios/example.md

# Phase 1 only (just the six parallel analyses)
python sim.py scenarios/example.md --phase1-only

# Multi-pass: revised argument goes back through Phase 1
python sim.py scenarios/example.md --passes 2

# Override model (shouldn't need to — Opus is default)
python sim.py scenarios/example.md --model claude-sonnet-4-6
```

## Scenario Format

Two modes of input:

### Quick Mode (phone/Slack — inline description)
```markdown
# MTD Opposition: Unconscionability of Arbitration Clause

## Forum
SDNY

## Adversary Calibration
aggressive

## Context
Minority shareholder in a Delaware LLC. Arbitration clause says "all
disputes arising under or relating to this Agreement" go to JAMS.
We're arguing the fiduciary duty claims arise under common law not the
agreement, and JAMS fees are unconscionable.

## Key Authorities
- Buckeye Check Cashing v. Cardegna, 546 U.S. 440 (2006)
```

### Full Mode (reference a draft brief)
```markdown
# Steiner v. Sweetlax — MTD Opposition

## Forum
CDCA (Southern Division)

## Adversary Calibration
standard

## Context
Minor's lacrosse injury case. Defendant moved to dismiss for failure
to state a claim. Our opposition argues negligent supervision.

## Brief
brief: drafts/steiner_mtd_opp_draft.md

## Key Authorities
- ...
```

The `brief:` field points to an external file (relative to the scenario). The orchestrator inlines it automatically — no need to paste a 15-page brief into the scenario.

See `scenarios/TEMPLATE.md` for the full template.

## Output Structure
```
output/example_20260321_143022/
├── summary.md                      # Index with reading order
├── phase1_hostile_oc.md            # Independent analyses
├── phase1_skeptical_judge.md
├── phase1_appellate_panel.md
├── phase1_economic_realist.md
├── phase1_procedural_tactician.md
├── phase1_record_auditor.md
├── phase2_destroyer.md             # Synthesized vulnerability report
└── phase2_refiner.md               # Revised argument + opposition playbook
```

For multi-pass runs, subsequent passes use `_pass2`, `_pass3` suffixes.

**Reading order:** `phase2_refiner.md` → `phase2_destroyer.md` → individual Phase 1 files.

## Model & Cost
- Default: Opus across the board. No corner-cutting on model quality.
- Per run: 8 API calls (6 parallel + 2 sequential). Multi-pass multiplies.
- The sim is fire-and-forget — toss it an issue, do something else, read the results later.

## Requirements
- Claude CLI (`claude` command) installed and `ANTHROPIC_API_KEY` set
- Python 3.10+

## Future Enhancements
- [ ] Tool access for Phase 1 agents (search CourtListener for counter-authorities)
- [ ] Integration with case-research project for real case citations
- [ ] Law Clerk agent: independent research, flags cases neither side cited
- [ ] Mediator mode: for settlement/demand letter scenarios
- [ ] Jury mode: for trial arguments, tests lay comprehension
