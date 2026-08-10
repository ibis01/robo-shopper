#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "→ Creating virtualenv and installing deps..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo "→ Running governed decision dossier for ETH buy (0.5 @ 1894, stop 1860)..."
.venv/bin/python - <<'PY'
import asyncio, json
from finance_copilot_skills_mcp import _generate_governance_dossier

async def main():
    dossier = await _generate_governance_dossier("ETH", "buy", 0.5, 1894.0, 1860.0)
    print(json.dumps(dossier, indent=2))

asyncio.run(main())
PY

echo
echo "✅ Dossier generated. In a real session the LLM presents this to the"
echo "   trader, who then runs the 'cli_command' from execution_plan manually."
