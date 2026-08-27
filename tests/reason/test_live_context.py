from datetime import UTC, date, datetime

import pytest

from app.reason.live_context import live_portfolio_context
from app.schemas.live_execution import LivePortfolioSnapshot
from app.storage.database import connect


def _snapshot(profile_id: str, positions: list[dict[str, object]]) -> LivePortfolioSnapshot:
    return LivePortfolioSnapshot(
        portfolio_snapshot_id=f"snap_{profile_id}",
        execution_profile_id=profile_id,
        broker_account_fingerprint="0" * 16,
        captured_at=datetime(2026, 8, 27, 20, tzinfo=UTC),
        account_equity=100,
        buying_power=50,
        positions=positions,
    )


def test_live_context_isolates_profile_quotas_and_positions() -> None:
    conn = connect(":memory:")
    conn.executemany(
        """
        INSERT INTO order_intents
            (order_intent_id, decision_id, created_at, ticker, side, execution_mode,
             execution_profile_id, intent_json)
        VALUES (?, ?, '2026-08-27T20:00:00Z', 'NVDA', 'BUY', 'LIVE', ?, '{}')
        """,
        [
            ("oi_codex_1", "d_codex_1", "codex"),
            ("oi_codex_2", "d_codex_2", "codex"),
            ("oi_claude", "d_claude", "claude"),
        ],
    )
    codex = _snapshot(
        "codex", [{"ticker": "NVDA", "market_value": 20, "primary_theme_id": "chips"}]
    )
    claude = _snapshot(
        "claude", [{"ticker": "MSFT", "market_value": 30, "primary_theme_id": "cloud"}]
    )

    codex_context = live_portfolio_context(conn, codex, date(2026, 8, 27))
    claude_context = live_portfolio_context(conn, claude, date(2026, 8, 27))

    assert codex_context.buy_add_trades_today == 2
    assert claude_context.buy_add_trades_today == 1
    assert codex_context.primary_theme_weights == {"chips": 0.2}
    assert claude_context.primary_theme_weights == {"cloud": 0.3}


def test_live_context_fails_closed_for_unknown_holding() -> None:
    snapshot = _snapshot("codex", [{"ticker": "NVDA", "market_value": 20, "primary_theme_id": ""}])

    with pytest.raises(ValueError, match="missing primary theme"):
        live_portfolio_context(connect(":memory:"), snapshot, date(2026, 8, 27))


def test_live_context_rejects_position_value_above_equity() -> None:
    snapshot = _snapshot(
        "codex", [{"ticker": "NVDA", "market_value": 101, "primary_theme_id": "chips"}]
    )

    with pytest.raises(ValueError, match="exceeds account equity"):
        live_portfolio_context(connect(":memory:"), snapshot, date(2026, 8, 27))
