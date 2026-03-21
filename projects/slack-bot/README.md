# Slack Bot — Status & Notification Channel

## Overview
Optional Slack integration for monitoring long-running tasks on enlightenment. Deferred until other projects are running and there's a demonstrated need for async notifications beyond `--remote-control`.

## Use Cases
- Notifications when template refinement completes (round count, final score)
- Case research results delivered to a channel
- Adversarial sim transcripts posted for review
- General "task complete" pings so Matt doesn't have to check in manually

## Possible Approaches
1. **Slack MCP Server** — Claude Code has MCP support; wire up a Slack MCP for sending messages
2. **Simple webhook** — Incoming webhook to a `#enlightenment` channel; shell scripts post via curl
3. **Slack Bot (full)** — Bot with slash commands for triggering tasks and receiving results

## Status
Parked. Revisit after at least one project is running unattended and we see if `--remote-control` over Tailscale is sufficient or if async notifications add real value.
