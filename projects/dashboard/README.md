# Dashboard — Terminal UI for Monitoring

## Overview
A `textual`-based TUI that runs in a tmux pane. Shows running tasks, recent results, library contents, and system status at a glance. Not an interactive command interface — that's what `claude` is for. This is the heads-up display.

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  TASKS                                                      │
│  ● adversarial-sim:steiner  [running]  4m 23s               │
│  ✓ case-research:tvpa       [done]     12 results   2m ago  │
│  ✗ docx-pipeline:letter     [failed]   round 7/30  18m ago  │
├─────────────────────────────────────────────────────────────┤
│  LIBRARY              │  RECENT OUTPUT                      │
│  tvpa (3 topics)      │  adversarial-sim:steiner            │
│    private_right  ✓   │    opposing_counsel: 3 fatal, 1 ser │
│    fee_shifting   ✓   │    judge: 2 fatal                   │
│    charging_lien  ○   │    attacker: 4 compound weaknesses  │
│  arbitration (2)      │    reviser: revised + 8 playbook    │
│    unconscionab.  ✓   │                                     │
│    separability   ●   │  [Enter to view full output]        │
├─────────────────────────────────────────────────────────────┤
│  SYSTEM                                                     │
│  uptime: 14d 3h  │  disk: 42% used  │  bot: online         │
│  claude: idle     │  CL quota: 4,812/5,000                  │
└─────────────────────────────────────────────────────────────┘
```

## Features
- **Task panel:** Live-updating list of running/recent tasks from task_manager
- **Library panel:** Research library categories with staleness indicators
- **Output panel:** Summary of most recent sim/research results (click to expand)
- **System panel:** Uptime, disk, bot status, CL API quota

## Usage
```bash
# Run in a tmux pane
./dashboard.py

# Or with a specific refresh interval
./dashboard.py --refresh 5
```

## Typical tmux setup
```
tmux new-session -s sandbox
# Pane 0: dashboard (top)
python projects/dashboard/dashboard.py
# Pane 1: claude (bottom)
./cli.sh
```

## Requirements
- `textual` (Python TUI framework)
- `uv pip install textual`

## Status
Stub — to be built when textual is installed on the box.
