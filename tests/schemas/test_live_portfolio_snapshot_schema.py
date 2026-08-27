from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.live_execution import LivePortfolioSnapshot


def _snapshot_data() -> dict[str, object]:
    return {
        "portfolio_snapshot_id": "snap_codex",
        "execution_profile_id": "codex",
        "broker_account_fingerprint": "0123456789abcdef",
        "captured_at": datetime(2026, 8, 27, 20, tzinfo=UTC),
        "account_equity": 100.0,
        "buying_power": 80.0,
        "positions": [{"ticker": "NVDA", "market_value": 20.0, "primary_theme_id": "ai"}],
    }


def test_live_portfolio_snapshot_is_valid() -> None:
    assert LivePortfolioSnapshot.model_validate(_snapshot_data()).positions[0].ticker == "NVDA"


def test_live_portfolio_snapshot_rejects_duplicate_tickers() -> None:
    data = _snapshot_data()
    data["positions"] = [data["positions"][0], data["positions"][0]]  # type: ignore[index]

    with pytest.raises(ValidationError, match="unique"):
        LivePortfolioSnapshot.model_validate(data)
