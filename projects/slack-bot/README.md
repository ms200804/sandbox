# Slack Bot — Claude Interface

## Overview
A Claude-powered Slack bot running on a headless Debian box. DM it or @mention it in a channel with natural language — loose, typo-laden phone messages are fine. It interprets intent, runs tools (case research, adversarial sim, task status), and responds conversationally.

## Architecture

```
Phone/Slack
    │
    ▼
Slack (Socket Mode — outbound websocket, no public URL needed)
    │
    ▼
bot.py (on server)
    │
    ├─→ Claude API (with tool use)
    │       │
    │       ├─→ run_adversarial_sim()
    │       ├─→ search_cases()
    │       ├─→ find_similar_cases()
    │       ├─→ lookup_citation()
    │       ├─→ shepardize()
    │       ├─→ check_task_status()
    │       ├─→ read_file()
    │       └─→ run_shell_command()  (sandboxed)
    │
    └─→ Slack response (threaded)
```

### Why Socket Mode
- No public URL, no ngrok, no Lambda, no Tailscale funnel
- Bot opens an outbound websocket to Slack's servers
- Works from behind NAT, firewalls, Tailscale — just needs outbound HTTPS

### Why Claude API (not Claude Code CLI)
- The bot IS the agent — it receives a message, calls Claude with tools, Claude decides what to do
- Tool use API gives structured tool calls and results
- Persistent conversation threads per Slack thread (context window per conversation)

## Capabilities

### What you can say to it (examples)
```
"find cases on tvpa private right of action in the 5th circuit"
→ Triggers case research, posts results

"that second case looks good, more like that"
→ Finds similar cases via citation network

"run the adversarial sim against the steiner mtd scenario"
→ Asks clarifying questions, then kicks off sim

"can I argue unconscionability of JAMS fees in SDNY"
→ Asks forum/context, or "just run it" to go immediately

"whats running right now"
→ Lists active tasks

"show me the attacker output from the last sim run"
→ Reads and posts the file

"shepardize these cases: 546 US 440, 68 F3d 554"
→ Runs citation check via CourtListener
```

### Channels

| Channel | Purpose |
|---|---|
| `#status` | Bot status, task completions, morning digest |
| `#research` | Case research conversations (threads per topic) |
| `#adversarial` | Sim results (threads per sim run) |

DMs for quick one-offs.

### Tools available to Claude

| Tool | Description |
|---|---|
| `run_adversarial_sim` | Launch a sim — accepts anything from a bare issue to a full brief; asks clarifying questions by default |
| `search_cases` | Search CourtListener by topic, court, date |
| `find_similar_cases` | "More like this" — find cases citing the same authorities |
| `lookup_citation` | Look up a specific case by citation |
| `shepardize` | Check citations for negative treatment |
| `check_task` | Check status of a running background task |
| `list_tasks` | List all running/completed tasks |
| `read_file` | Read a file from the sandbox repo |
| `run_shell` | Run a sandboxed shell command (allowlisted commands only) |

## Setup

### 1. Create Slack App
1. Go to api.slack.com/apps → Create New App → From Scratch
2. Name: "Claude" (or whatever)
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

### 2. Environment
```bash
# In .env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
ANTHROPIC_API_KEY=sk-ant-...
COURTLISTENER_TOKEN=...          # optional
SLACK_CHANNEL_STATUS=#status
SLACK_CHANNEL_RESEARCH=#research
SLACK_CHANNEL_ADVERSARIAL=#adversarial
DIGEST_HOUR=7
DIGEST_MINUTE=0
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
sudo cp claude-bot.service /etc/systemd/system/
sudo systemctl enable --now claude-bot
```

## Design Decisions

### Conversation threading
- Each Slack thread = one Claude conversation with maintained context
- DMs use the DM channel as implicit thread
- @mentions in channels always use threads to avoid noise

### Long-running tasks
- Bot acknowledges immediately ("Running the sim, I'll post results when done")
- Task runs in background thread
- Results posted to the appropriate channel when complete
- If results are long, posted as a Slack file attachment

### Morning digest
- Posts daily at configured time (default 7am) to #status
- Summarizes overnight: tasks completed, failed, still running

## File Structure
```
slack-bot/
├── README.md
├── bot.py                  # Slack listener + Claude integration
├── tools.py                # Tool definitions and implementations
├── task_manager.py         # Background task tracking
├── claude-bot.service      # systemd unit file
└── .env.example
```
