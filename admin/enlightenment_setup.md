# Enlightenment — Full Setup Guide

## Overview

Two Claude Code instances on enlightenment, each in its own tmux session:

| Session | Repo | Purpose | Access |
|---|---|---|---|
| `claude-remote` | `~/claude/` | Remote control from phone. Full client work, billing, email, calendar. | mail_cli, calendar_cli, onedrive_cli, all client files |
| `sandbox` | `~/sandbox/` | Long-running projects (sims, research, template refinement). Can run unattended. | CourtListener, sim scripts, sandbox files only |

The sandbox instance does NOT get mail/calendar/OneDrive access. Only the
remote-control instance (which Matt is actively driving) has those tools.

## 1. Clone Repos

```bash
cd ~
git clone git@github.com:ms200804/claude.git
git clone git@github.com:ms200804/sandbox.git
# notes repo if needed:
git clone git@github.com:ms200804/notes.git
```

### SSH key setup (if not done)
```bash
ssh-keygen -t ed25519 -C "enlightenment"
cat ~/.ssh/id_ed25519.pub
# Add to GitHub: Settings → SSH Keys
```

### Git config
```bash
git config --global user.name "Matthew W. Schmidt"
git config --global user.email "matt@schmidtlc.com"
```

## 2. Environment Files

### ~/claude/.env
```bash
# Microsoft Graph (mail, calendar, OneDrive)
GRAPH_CLIENT_ID=...
GRAPH_TENANT_ID=...

# These are used by mail_cli.py, calendar_cli.py, onedrive_cli.py
# Token cache will be created on first auth: .token_cache.bin
```

### ~/sandbox/projects/slack-bot/.env
```bash
# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Claude API (for Slack bot's own API calls)
ANTHROPIC_API_KEY=sk-ant-...

# CourtListener
COURTLISTENER_TOKEN=...

# Channel config
SLACK_CHANNEL_STATUS=#status
SLACK_CHANNEL_RESEARCH=#research
SLACK_CHANNEL_ADVERSARIAL=#adversarial
DIGEST_HOUR=7
DIGEST_MINUTE=0
```

## 3. Python Environment

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Claude repo venv (mail_cli, calendar_cli, onedrive_cli)
cd ~/claude
uv venv
source .venv/bin/activate
uv pip install msal httpx python-dotenv

# Sandbox venv (slack bot, case research)
cd ~/sandbox
uv venv
source .venv/bin/activate
uv pip install slack-bolt anthropic httpx python-dotenv
```

## 4. System Packages

```bash
sudo apt install -y \
  libreoffice-writer \
  poppler-utils \
  imagemagick \
  pandoc \
  tmux \
  python3-pip
```

## 5. Tmux Sessions

### Start both sessions
```bash
# Remote-control session (claude repo — full access)
tmux new-session -d -s claude-remote -c ~/claude
tmux send-keys -t claude-remote 'claude' Enter

# Sandbox session (sandbox repo — projects only)
tmux new-session -d -s sandbox -c ~/sandbox
# Optionally start dashboard in a split:
tmux split-window -t sandbox -v -c ~/sandbox
tmux send-keys -t sandbox.0 'python projects/dashboard/dashboard.py' Enter
tmux send-keys -t sandbox.1 'claude' Enter
```

### Attach to sessions
```bash
# From SSH (laptop or phone via Tailscale)
tmux attach -t claude-remote   # for client work
tmux attach -t sandbox          # for projects
```

### Session management
```bash
tmux ls                         # list sessions
tmux switch -t sandbox          # switch between
tmux detach                     # Ctrl-B, D — leave running
```

## 6. Remote Control (Phone)

On enlightenment, start Claude with remote control:
```bash
tmux attach -t claude-remote
# Inside the session:
claude --remote-control
```

This prints a URL. Open it on your phone browser via Tailscale.
You now have full Claude Code access to the claude repo from your phone.

For the sandbox, same pattern but attach to the sandbox session instead.

## 7. Slack Bot (Persistent)

### Manual start (testing)
```bash
cd ~/sandbox/projects/slack-bot
source ../../.venv/bin/activate
python bot.py
```

### Systemd service (production)
```bash
sudo cp ~/sandbox/projects/slack-bot/claude-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-bot
sudo systemctl status claude-bot
# Logs:
journalctl -u claude-bot -f
```

## 8. First Auth (Microsoft Graph)

The mail/calendar/OneDrive CLIs use device code flow. First run requires
a browser login (do this from your laptop, not headless):

```bash
cd ~/claude
source .venv/bin/activate
python mail_cli.py recent -n 1
# Follow the device code prompt — open the URL on your laptop/phone
# Token cache saved to .token_cache.bin, subsequent runs are automatic
```

## 9. Access Boundaries

**Remote-control instance (~/claude/):**
- Full read/write to claude repo
- Full read/write to notes repo (if cloned)
- mail_cli.py, calendar_cli.py, onedrive_cli.py
- Git push (with Matt actively driving via remote control)

**Sandbox instance (~/sandbox/):**
- Full read/write to sandbox repo
- CourtListener API
- NO access to mail, calendar, OneDrive
- NO access to claude/notes repos
- Git push to sandbox repo only
- Can run unattended (`--dangerously-skip-permissions`)

This boundary is enforced by working directory and CLAUDE.md instructions,
not filesystem permissions. The sandbox CLAUDE.md explicitly says not to
touch client data or external services beyond CourtListener.

## 10. Keeping Repos in Sync

Both your Mac and enlightenment push/pull from the same GitHub repos.
Standard git workflow:

- Before starting work on enlightenment: `git pull` in the relevant repo
- Before starting work on Mac: `git pull`
- Commit and push when done with a session on either machine

If you get merge conflicts (e.g., both machines edited the same file),
resolve on whichever machine you're on. This is normal git — nothing
special about the two-machine setup.

## 11. Monitoring

```bash
# Check what's running
ps aux | grep claude
tmux ls

# Memory/CPU
free -h
uptime

# Slack bot logs
journalctl -u claude-bot -f

# Disk space
df -h
```

## Resource Budget (7.5GB RAM)

| Process | ~RAM | Notes |
|---|---|---|
| Claude Code (remote) | ~200-400MB | Active when attached |
| Claude Code (sandbox) | ~200-400MB | Active when running |
| Slack bot | ~100MB | Always running |
| System + tmux | ~300MB | Base overhead |
| **Total typical** | **~1.2GB** | Plenty of headroom |
