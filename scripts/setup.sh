#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${1:-qwen2.5-coder:3b}"
VOICE="${2:-en_GB-alan-medium}"

echo "=== Code Assassin Setup ==="

# Check uv
echo "Checking uv..."
if ! command -v uv &> /dev/null; then
    echo "ERROR: uv is not installed. Please install uv first: https://github.com/astral-sh/uv"
    exit 1
fi
echo "uv found."

# Check ollama
echo "Checking ollama..."
if ! command -v ollama &> /dev/null; then
    echo "WARNING: ollama is not installed. Please install ollama: https://ollama.com/"
else
    echo "ollama found."
fi

# Sync dependencies
echo "Syncing dependencies..."
uv sync

# Pull model
echo "Pulling model $PROJECT_NAME..."
if command -v ollama &> /dev/null; then
    ollama pull "$PROJECT_NAME"
else
    echo "WARNING: Skipping model pull (ollama not found)"
fi

# Download voice
echo "Downloading voice $VOICE..."
uv run assassin voices download "$VOICE"

# Run doctor
echo "Running health checks..."
uv run assassin doctor

echo "Setup complete!"