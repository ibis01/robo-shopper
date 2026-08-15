"""Robo-Shopper V4 - Portfolio-level guardrails (Sprint 1)."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "trades.db")

PORTFOLIO_BALANCE = 10000.0
MAX_EXPOSURE_PCT = 20.0
DRAWDOWN_LIMIT_PCT = 5.0
ATR_STOP_MULT = 1.5
MAJORS = {"BTC", "ETH", "SOL"}


def _conn():
    return sqlite3.connect(DB)


def _base(symbol):
    return symbol.replace("USDT", "").replace("USD", "").split("-")[0].upper()


def _open_positions(con):
    return con.execute(
        "SELECT symbol, COALESCE(proposed_amount,0) * COALESCE(actual_entry_price, proposed_price,0) "
        "FROM trades WHERE status NOT IN ('closed','proposed','rejected')"
    ).fetchall()


def _daily_pnl(con):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return con.execute(
        "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='closed' AND closed_at >= ?",
        (cutoff,)).fetchone()[0]


def register(mcp: FastMCP):

    @mcp.tool()
    def get_guard_status() -> dict:
        """Portfolio guardrails: circuit breaker state, exposure cap, open clusters."""
        con = _conn()
        daily = _daily_pnl(con)
        limit = PORTFOLIO_BALANCE * DRAWDOWN_LIMIT_PCT / 100.0
        opens = _open_positions(con)
        notional = round(sum(n for _, n in opens), 2)
        return {
            "daily_realized_pnl": round(daily, 2),
            "drawdown_limit_usd": -limit,
            "circuit_breaker": "TRIPPED" if daily <= -limit else "ARMED",
            "open_notional": notional,
            "max_open_notional": PORTFOLIO_BALANCE * MAX_EXPOSURE_PCT / 100.0,
            "exposure_pct": round(notional / PORTFOLIO_BALANCE * 100.0, 2),
            "open_symbols": sorted({_base(s) for s, _ in opens}),
        }

    @mcp.tool()
    def screen_proposal(symbol: str, proposed_notional: float) -> dict:
        """Gate a new proposal against breaker, exposure cap and correlation cluster."""
        con = _conn()
        violations, warnings = [], []
        daily = _daily_pnl(con)
        limit = PORTFOLIO_BALANCE * DRAWDOWN_LIMIT_PCT / 100.0
        if daily <= -limit:
            violations.append(f"circuit breaker tripped (daily pnl {daily:.2f} <= {-limit:.2f})")
        opens = _open_positions(con)
        notional = sum(n for _, n in opens)
        if notional + proposed_notional > PORTFOLIO_BALANCE * MAX_EXPOSURE_PCT / 100.0:
            violations.append("exposure cap exceeded (>20% of portfolio would be open)")
        base = _base(symbol)
        clash = {_base(s) for s, _ in opens} & MAJORS
        if base in MAJORS and clash:
            warnings.append(f"correlated exposure: {sorted(clash)} already open (majors cluster)")
        return {"approved": not violations, "violations": violations, "warnings": warnings}

    @mcp.tool()
    def atr_position_size(entry_price: float, atr: float,
                          portfolio_balance: float = PORTFOLIO_BALANCE,
                          risk_pct: float = 2.0) -> dict:
        """Volatility-adjusted sizing: stop = 1.5x ATR, size = risk budget / stop distance."""
        stop_distance = round(atr * ATR_STOP_MULT, 2)
        risk_budget = portfolio_balance * risk_pct / 100.0
        size = round(risk_budget / stop_distance, 6) if stop_distance > 0 else 0.0
        return {
            "stop_distance": stop_distance,
            "risk_budget_usd": risk_budget,
            "position_size": size,
            "notional": round(size * entry_price, 2),
            "suggested_stop_buy": round(entry_price - stop_distance, 2),
            "note": "wider volatility -> smaller size, inside the same 2% risk budget",
        }
