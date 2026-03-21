# Sandbox — Headless Debian Experimentation Repo

## Environment
- **Machine:** "enlightenment" — headless Debian box
- **Access:** Tailscale + Claude Code `--remote-control`
- **User:** mws
- **Purpose:** Sandboxed experimentation — long-running agents, pipeline development, research tools
- **Policy:** Nothing here should touch production repos or client data. This is for building and testing tooling.

## Projects

### 1. docx-pipeline (`projects/docx-pipeline/`)
Automated template refinement: Claude Code iterates on Word reference templates by building test docs, rendering to PNG, and visually comparing against a precedent document. Runs unattended with `--dangerously-skip-permissions`.

See `projects/docx-pipeline/README.md` for setup and usage.

### 2. case-research (`projects/case-research/`)
Agent that queries CourtListener (and potentially other public legal databases) to do preliminary case research — find relevant opinions, summarize holdings, pull key quotes, monitor dockets.

See `projects/case-research/README.md` for design and API notes.

### 3. adversarial-sim (`projects/adversarial-sim/`)
Multi-agent argument refinement: spawns subagents in roles (advocate, adversary, judge) to stress-test legal arguments before drafting. Uses Claude Code's subagent architecture.

See `projects/adversarial-sim/README.md` for design.

### 4. slack-bot (`projects/slack-bot/`)
Optional Slack integration for status notifications from long-running tasks. Deferred until other projects are running.

## Conventions
- Python: use `uv` for dependency management
- Each project gets its own README.md with setup instructions
- Shared utilities go in `shared/`
- Debian packages needed across projects: see `setup.sh`

## Unattended Runs
For headless/unattended execution:
```bash
claude --dangerously-skip-permissions --print "$(cat prompt.md)"
```
