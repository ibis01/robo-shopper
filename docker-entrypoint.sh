#!/bin/bash
set -e

# If a command is passed (e.g., "monitor", "mcp", "agent"), run it
case "$1" in
    monitor)
        echo "Starting 24/7 Voice Monitor..."
        exec python monitor_service.py
        ;;
    mcp)
        echo "Starting MCP Tool Registry Server..."
        exec python main_server.py
        ;;
    agent)
        echo "Starting Qwen Copilot Brain..."
        exec python qwen_agent.py
        ;;
    dashboard)
        echo "Starting FastAPI Dashboard..."
        exec uvicorn dashboard:app --host 0.0.0.0 --port 8003
        ;;
    *)
        echo "No command specified. Running all services..."
        python monitor_service.py &
        python main_server.py &
        exec python qwen_agent.py
        ;;
esac