#!/bin/bash
# Enlightenment (headless Debian) — one-time system setup
set -e

echo "=== System packages ==="
sudo apt update
sudo apt install -y \
  libreoffice-writer \
  poppler-utils \
  imagemagick \
  pandoc \
  python3-pip \
  python3-venv \
  git \
  curl \
  jq

echo "=== Install uv ==="
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "=== Install Claude Code ==="
# Requires Node.js — install if missing
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt install -y nodejs
fi
npm install -g @anthropic-ai/claude-code

echo "=== Install Tailscale ==="
if ! command -v tailscale &> /dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
  echo "Run: sudo tailscale up --operator=mws"
  echo "Then disable key expiry in Tailscale admin console"
fi

echo "=== Done ==="
echo "Next steps:"
echo "  1. tailscale up --operator=mws"
echo "  2. Set ANTHROPIC_API_KEY in ~/.bashrc or ~/.env"
echo "  3. Clone this repo and run project-specific setup"
