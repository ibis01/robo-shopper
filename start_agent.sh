#!/bin/bash
# Robo-Shopper Agent Launcher

# Check if GROK_API_KEY is already set in the environment
if [ -z "$GROK_API_KEY" ]; then
    echo "⚠️ GROK_API_KEY is not set. Please set it in your .env file or run:"
    echo "export GROK_API_KEY='xai-your-actual-key-here'"
    exit 1
fi

echo " Starting Robo-Shopper Agent (Provider: Grok)..."
echo " Dashboard is running at: http://localhost:8003"
echo "---------------------------------------------------"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python qwen_agent.py
