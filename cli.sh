#!/bin/bash
# Quick launcher for Claude Code on the sandbox box.
# Usage: ./cli.sh [optional prompt]
#
# Sets up env, activates venv if needed, and drops into Claude Code
# with full access to all sandbox projects.

set -e
cd "$(dirname "$0")"

# Load env vars (API keys, tokens)
if [ -f projects/slack-bot/.env ]; then
    export $(grep -v '^#' projects/slack-bot/.env | xargs)
fi

# Activate venv if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

if [ -n "$1" ]; then
    # One-shot mode: run a prompt and exit
    claude --print "$@"
else
    # Interactive mode
    claude
fi
