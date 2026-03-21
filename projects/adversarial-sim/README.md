# Adversarial Simulation — Multi-Agent Argument Refinement

## Overview
Uses Claude Code's subagent architecture to stress-test legal arguments before drafting. Multiple agents adopt distinct roles (advocate, adversary, judge) and iterate on the strength of an argument through structured rounds of critique and revision.

## Concept

You feed in a draft argument or legal position. The system runs it through adversarial pressure:

1. **Advocate** presents the argument
2. **Adversary** attacks it — finds weaknesses, counter-authorities, factual gaps
3. **Advocate** revises in response
4. **Judge** scores the exchange, identifies unresolved issues, and decides if another round is needed
5. Repeat until the judge is satisfied or max rounds reached

The output is a refined argument plus a vulnerability report — what the other side will say and how to preempt it.

## Agent Roles

### Advocate
- System prompt: aggressive plaintiff/defendant counsel (matches Matt's litigation style)
- Job: present the strongest version of the argument, respond to attacks
- Has access to: the brief/argument draft, relevant case law, facts

### Adversary
- System prompt: skilled opposing counsel
- Job: find every weakness — factual, legal, procedural, strategic
- Attacks: distinguishing cases, alternative interpretations, policy arguments, procedural defenses
- Should be calibrated to the likely quality of actual opposing counsel (configurable)

### Judge
- System prompt: experienced federal judge (or state, configurable by forum)
- Job: evaluate the exchange, score persuasiveness, flag unaddressed issues
- Outputs: structured scorecard + narrative assessment
- Decides: "resolved" vs. "needs another round" vs. "fundamental problem"

### Future Roles
- **Law Clerk:** does independent research, flags cases neither side cited
- **Mediator:** for settlement/demand letter scenarios, evaluates reasonableness
- **Jury:** for trial arguments, tests comprehension and persuasion at lay level

## Architecture

```
adversarial-sim/
├── README.md
├── sim.py                # Orchestrator: spawns agents, manages rounds
├── prompts/
│   ├── advocate.md       # Advocate system prompt
│   ├── adversary.md      # Adversary system prompt
│   └── judge.md          # Judge system prompt
├── scenarios/            # Input scenarios (argument + context)
│   └── example.md
└── output/               # Simulation transcripts + scorecards
```

## Workflow

```
Input: argument draft + case context + forum
  │
  ├─→ [Advocate Agent] presents argument
  │        │
  │        ▼
  ├─→ [Adversary Agent] attacks
  │        │
  │        ▼
  ├─→ [Advocate Agent] revises
  │        │
  │        ▼
  └─→ [Judge Agent] scores
           │
           ├─→ "Resolved" → output final argument + vulnerability report
           └─→ "Another round" → loop back to Adversary
```

## Design Decisions

### Start Simple
Phase 1: Two agents only (advocate + adversary), 3 rounds max, no judge.
- Prove the concept works and produces useful output
- See if the adversary finds real weaknesses vs. generic objections

Phase 2: Add judge agent for scoring and loop control.

Phase 3: Add law clerk for independent research (integrate with case-research project).

### Key Questions
- [ ] How much case context to give each agent? Full brief vs. summary?
- [ ] Should adversary have access to case-research tool for finding counter-authorities?
- [ ] Fixed round count vs. judge-controlled termination?
- [ ] Output format: transcript + scorecard, or revised brief with annotations?
- [ ] How to calibrate adversary strength? (Public defender vs. BigLaw vs. DOJ)
- [ ] Should the advocate agent match Matt's writing style (use tone_references)?
