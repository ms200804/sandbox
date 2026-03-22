# Slack Bot — Conversational Interface to Enlightenment

## Overview
A Claude-powered Slack bot running on enlightenment. DM it or @mention it in a channel with natural language — loose, typo-laden phone messages are fine. It interprets intent, runs tools (case research, adversarial sim, task status), and responds conversationally.

## Architecture

```
Phone/Slack
    │
    ▼
Slack (Socket Mode — outbound websocket, no public URL needed)
    │
    ▼
bot.py (on enlightenment)
    │
    ├─→ Claude API (with tool use)
    │       │
    │       ├─→ run_adversarial_sim()
    │       ├─→ run_case_research()
    │       ├─→ check_task_status()
    │       ├─→ read_file()
    │       ├─→ list_running_tasks()
    │       └─→ run_shell_command()  (sandboxed)
    │
    └─→ Slack response (threaded)
```

### Why Socket Mode
- No public URL, no ngrok, no Lambda, no Tailscale funnel
- Bot opens an outbound websocket to Slack's servers
- Works from behind NAT, firewalls, Tailscale — just needs outbound HTTPS
- Perfect for a headless box

### Why Claude API (not Claude Code CLI)
- The bot IS the agent — it receives a message, calls Claude with tools, Claude decides what to do
- Tool use API gives structured tool calls and results
- Persistent conversation threads per Slack thread (context window per conversation)
- Can stream responses for long-running queries

## Capabilities

### What you can say to it (examples)
```
"find cases on tvpa private right of action in the 5th circuit"
→ Triggers case research agent, posts results

"run the adversarial sim against the steiner mtd scenario"
→ Kicks off sim, posts progress, delivers results

"whats running right now"
→ Lists active tasks on enlightenment

"hows the template refinement going"
→ Checks latest session_log.md, reports round/score

"show me the destroyer output from the last sim run"
→ Reads and posts the file

"shepardize these cases: 546 US 440, 68 F3d 554"
→ Runs citation check via CourtListener

"remind me what the sakhai matter status is"
→ Reads matter_summary.md (if client repos are synced)
```

### Tools available to Claude

| Tool | Description |
|---|---|
| `run_adversarial_sim` | Launch a sim with a scenario file or inline argument description |
| `run_case_research` | Search CourtListener, lookup citations, shepardize |
| `check_task_status` | Check status of a running background task |
| `list_tasks` | List all running/completed tasks |
| `read_file` | Read a file from the sandbox repo |
| `run_shell` | Run a sandboxed shell command (ls, git status, cat, etc.) |
| `notify` | Send a message to a Slack channel (for async task completion) |

## Setup

### 1. Create Slack App
1. Go to api.slack.com/apps → Create New App → From Scratch
2. Name: "Enlightenment" (or whatever)
3. Enable **Socket Mode** (Settings → Socket Mode → Enable)
4. Generate an **App-Level Token** with `connections:write` scope
5. Under **OAuth & Permissions**, add bot scopes:
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
   - `files:write` (for posting long results as files)
6. Under **Event Subscriptions**, subscribe to:
   - `app_mention`
   - `message.im`
7. Install to workspace, copy **Bot User OAuth Token**

### 2. Environment on Enlightenment
```bash
# In .env or exported in ~/.bashrc
SLACK_BOT_TOKEN=xoxb-...        # Bot User OAuth Token
SLACK_APP_TOKEN=xapp-...        # App-Level Token (Socket Mode)
ANTHROPIC_API_KEY=sk-ant-...    # Claude API
COURTLISTENER_TOKEN=...         # CourtListener API (optional, for case research)
```

### 3. Install & Run
```bash
cd projects/slack-bot
uv venv && source .venv/bin/activate
uv pip install slack-bolt anthropic httpx python-dotenv
python bot.py
```

For persistent running:
```bash
# systemd service (see enlightenment.service)
sudo cp enlightenment.service /etc/systemd/system/
sudo systemctl enable --now enlightenment
```

## Design Decisions

### Conversation threading
- Each Slack thread = one Claude conversation with maintained context
- DMs use the DM channel as implicit thread
- @mentions in channels always use threads to avoid noise
- Context window is per-thread; new thread = fresh context

### Long-running tasks
- Adversarial sim, template refinement, etc. take minutes
- Bot acknowledges immediately ("Running the sim, I'll post results when done")
- Task runs in background thread
- Results posted to the same Slack thread when complete
- If results are long, posted as a Slack file attachment (snippet)

### Error handling
- If Claude API fails, bot posts the error to the thread
- If a tool fails, Claude sees the error and can explain/retry
- Bot process itself is monitored by systemd (auto-restart)

## File Structure
```
slack-bot/
├── README.md
├── bot.py                  # Main bot: Slack listener + Claude integration
├── tools.py                # Tool definitions and implementations
├── task_manager.py         # Background task tracking
├── enlightenment.service   # systemd unit file
└── .env.example            # Template for environment variables
```
