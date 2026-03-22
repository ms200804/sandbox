# Adversarial Simulation — Two-Phase Argument Stress-Testing

## Overview
Feed in a draft argument or legal position. The system runs it through independent adversarial pressure from multiple perspectives, then synthesizes the results into a prioritized vulnerability report and revised argument.

## Architecture: Two Phases

### Phase 1: Parallel Attack Surface (independent, no cross-talk)

Four agents analyze the argument simultaneously. They never see each other's output, preventing convergence and ensuring independent weakness discovery.

| Agent | Lens | Finds |
|---|---|---|
| **Hostile OC** | "How do I win this motion?" | Actual attacks opposing counsel will make — case distinctions, procedural traps, factual gaps |
| **Skeptical Judge** | "Why should I grant this?" | Missing elements, conclusory assertions, standard-of-review problems, threshold issues |
| **Appellate Panel** | "Is the doctrine clean?" | Doctrinal errors, circuit splits, sloppy framing, preservation issues |
| **Economic Realist** | "What are the real incentives?" | Settlement leverage, cost/benefit, remedy collectability, insurance angles |

Each outputs: top 3 weaknesses, strongest single attack vector, and suggested authorities.

### Phase 2: Sequential Synthesis

| Agent | Job |
|---|---|
| **Destroyer** | Reads ALL Phase 1 output. Ranks weaknesses by severity. Identifies compound weaknesses (same issue flagged by multiple agents from different angles). Produces prioritized vulnerability report. |
| **Refiner** | Takes original argument + Destroyer's report. Revises to preempt top threats. Flags unfixable issues. Produces opposition playbook ("They'll argue X → Our response Y"). |

### Flow
```
Input: argument + case context + forum
  │
  ├─→ [Hostile OC]        ─┐
  ├─→ [Skeptical Judge]    ─┤  Phase 1 (parallel)
  ├─→ [Appellate Panel]    ─┤
  ├─→ [Economic Realist]   ─┘
  │                          │
  │         ┌────────────────┘
  │         ▼
  ├─→ [Destroyer]  → vulnerability report     Phase 2 (sequential)
  │         │
  │         ▼
  └─→ [Refiner]   → revised argument + opposition playbook
```

## Usage

```bash
# Full simulation (Phase 1 + Phase 2)
python sim.py scenarios/example.md

# Phase 1 only (just the four parallel analyses)
python sim.py scenarios/example.md --phase1-only

# Use a specific model
python sim.py scenarios/example.md --model claude-opus-4-6
```

## Output Structure
```
output/example_20260321_143022/
├── summary.md              # Index with reading order
├── phase1_hostile_oc.md    # Independent OC attack analysis
├── phase1_skeptical_judge.md
├── phase1_appellate_panel.md
├── phase1_economic_realist.md
├── phase2_destroyer.md     # Synthesized vulnerability report
└── phase2_refiner.md       # Revised argument + opposition playbook
```

**Reading order:** Start with `phase2_refiner.md` (the revised argument and playbook), then `phase2_destroyer.md` (full vulnerability report), then individual Phase 1 files for deep dives.

## Scenario Format

Scenarios go in `scenarios/`. See `scenarios/example.md` for the template:

```markdown
# Scenario Title

## Forum
[Court — e.g., SDNY, 9th Cir., CDCA]

## Position
[Who you represent and what you're arguing]

## Context
[Facts, procedural posture, key issues]

## Key Authorities (Starting Point)
[Cases and statutes — gives agents a starting point but they'll find more]
```

## Directory Structure
```
adversarial-sim/
├── sim.py              # Orchestrator
├── prompts/
│   ├── hostile_oc.md       # Phase 1
│   ├── skeptical_judge.md  # Phase 1
│   ├── appellate_panel.md  # Phase 1
│   ├── economic_realist.md # Phase 1
│   ├── destroyer.md        # Phase 2
│   └── refiner.md          # Phase 2
├── scenarios/
│   └── example.md
└── output/             # Simulation results (gitignored)
```

## Requirements
- Claude CLI (`claude` command) installed and `ANTHROPIC_API_KEY` set
- Python 3.10+

## Future Enhancements
- [ ] Integration with case-research project (give Hostile OC access to CourtListener for counter-authorities)
- [ ] Law Clerk agent: independent research, flags cases neither side cited
- [ ] Mediator mode: for settlement/demand letter scenarios
- [ ] Jury mode: for trial arguments, tests lay comprehension
- [ ] Configurable adversary calibration (standard / aggressive / elite)
- [ ] Multiple rounds: feed Refiner output back through Phase 1 for a second pass
