# Sandbox — Headless Debian Experimentation Repo

## Environment
- **Machine:** headless Debian box (hostname: enlightenment)
- **Access:** Tailscale + Claude Code `--remote-control`
- **User:** mws
- **Purpose:** Sandboxed experimentation — long-running agents, pipeline development, research tools
- **Policy:** Nothing here should touch production repos or client data. This is for building and testing tooling.

## Projects

### 1. docx-pipeline (`projects/docx-pipeline/`)
Automated template refinement: Claude Code iterates on Word reference templates by building test docs, rendering to PNG, and visually comparing against a precedent document. Runs unattended with `--dangerously-skip-permissions`.

See `projects/docx-pipeline/README.md` for setup and usage.

### 2. case-research (`projects/case-research/`)
Agent that queries CourtListener (and potentially other public legal databases) to do preliminary case research — find relevant opinions, summarize holdings, pull key quotes, monitor dockets. Structured JSON output, integrates with adversarial sim.

See `projects/case-research/README.md` for design and API notes.

### 3. adversarial-sim (`projects/adversarial-sim/`)
Two-phase argument stress-testing. Phase 1: six parallel agents (opposing counsel, judge, appellate, strategist, procedural, evidence) analyze independently. Phase 2: attacker synthesizes vulnerabilities, reviser revises the argument and builds an opposition playbook. Accepts anything from a bare legal question to a full draft brief.

See `projects/adversarial-sim/README.md` for design.

### 4. slack-bot (`projects/slack-bot/`)
Claude-powered Slack bot via Socket Mode. Conversational interface for running sims, case research, and task management from a phone. Three channels: #status, #research, #adversarial. Morning digest. Thread-based conversation context.

See `projects/slack-bot/README.md` for setup.

## Research Follow-Up (`research_followup/`)
Agents write notes here when they hit gaps CourtListener can't fill — cites needing proper Shepardizing, state court opinions CL doesn't have, cases it couldn't find or verify. These are practical gap-filling notes, not legal analysis — the Slack bot only has CourtListener, so its research is limited to what CL covers. The follow-up notes are just "here's what I couldn't find or confirm, go check Lexis." When Matt says "check any new research follow-up" or "check research notes," read this folder, summarize what's pending, and give him a clean list to run through Lexis AI. When he comes back with results, update the research library and mark the follow-up notes as done.

## Incoming Briefs (`incoming/`)
Drop briefs here for citation extraction. Process with `python projects/case-research/process_incoming.py`. Extracted citations go to the research library; processed files move to `incoming/processed/`.

## Conventions
- Python: use `uv` for dependency management
- Each project gets its own README.md with setup instructions
- Shared utilities go in `shared/`
- Debian packages needed across projects: see `setup.sh`
- Default model: Opus (no corner-cutting on inference quality)

## Unattended Runs
For headless/unattended execution:
```bash
claude --dangerously-skip-permissions --print "$(cat prompt.md)"
```
