import logging
from typing import Any, Dict

logger = logging.getLogger("robo_shopper.onchain_execution")
logging.basicConfig(level=logging.INFO)

def _execute_onchain_swap(token_in: str, token_out: str, amount: float, chain: str = "xlayer_test") -> Dict[str, Any]:
    # Normalize token symbols
    token_in = token_in.strip().upper()
    token_out = token_out.strip().upper()
    
    # Format the exact CLI command for X Layer testnet
    cli_command = f"onchainos swap execute --from {token_in} --to {token_out} --amount {amount} --chain {chain}"
    
    return {
        "ok": True,
        "tool": "execute_onchain_swap",
        "status": "PENDING_HUMAN_APPROVAL",
        "dry_run": True,
        "cli_command": cli_command,
        "message": "🛑 BIG GREEN BUTTON REQUIRED: This is a DRY RUN. The command has been generated but NOT executed. Human approval and manual execution required."
    }

def register_onchain_execution_tools(mcp: Any) -> None:
    @mcp.tool()
    def execute_onchain_swap(token_in: str, token_out: str, amount: float, chain: str = "xlayer_test") -> Dict[str, Any]:
        """Generate the onchainos CLI command for a swap. DOES NOT EXECUTE AUTOMATICALLY."""
        return _execute_onchain_swap(token_in, token_out, amount, chain)

if __name__ == "__main__":
    import json
    print(json.dumps(_execute_onchain_swap("USDC", "WETH", 100), indent=2))
