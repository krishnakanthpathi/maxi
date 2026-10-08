#!/usr/bin/env bash
# 🎙️ Start Maxi Decoupled Voice Service
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( dirname "$DIR" )"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

# Ensure GROQ_API_KEY is available
if [ -z "$GROQ_API_KEY" ] && [ -n "$GROK_API_KEY" ]; then
    export GROQ_API_KEY="$GROK_API_KEY"
fi

# Check if Maxi daemon is running
if ! curl -s http://127.0.0.1:4848/api/health > /dev/null 2>&1; then
    echo "⚠️ Maxi daemon is not running on 127.0.0.1:4848."
    echo "Starting Maxi daemon in background..."
    "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 4848 > /dev/null 2>&1 &
    sleep 2
fi

echo "🚀 Starting Maxi Voice Service..."
exec "$PYTHON" "$DIR/listener.py" "$@"
