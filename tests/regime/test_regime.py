from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.prices.cache import PriceBar, upsert_daily_prices
from app.regime.rules import (
    Component,
    RegimeScore,
    drawdown_component,
    publish_regime,
    trend,
    trend_slope,
    volatility_component,
)
from app.regime.run import render_backtest, save_snapshot
from app.schemas.decision_record import RegimeState
from app.storage.database import connect


@pytest.mark.parametrize(
    ("drawdown", "points"),
    [(-0.05, 0), (-0.10, -2), (-0.20, -2), (-0.20001, -4)],
)
def test_drawdown_boundaries(drawdown: float, points: int) -> None:
    assert drawdown_component(drawdown).points == points


@pytest.mark.parametrize(("percentile", "points"), [(59.99, 1), (60, -1), (85, -1), (85.01, -3)])
def test_volatility_percentile_boundaries(percentile: float, points: int) -> None:
    assert volatility_component(percentile).points == points


def test_sma_crossover_boundaries_are_not_positive() -> None:
    assert trend(100, 100).points == -2
    assert trend_slope(100, 100).points == -1
    assert trend(100.01, 100).points == 2
    assert trend_slope(100.01, 100).points == 1


def test_hysteresis_first_snapshot_publishes_directly() -> None:
    assert publish_regime(None, [RegimeState.RED]) == RegimeState.RED


def test_hysteresis_ignores_one_day_blip_then_changes_on_second_day() -> None:
    assert publish_regime(RegimeState.GREEN, [RegimeState.RED]) == RegimeState.GREEN
    assert publish_regime(RegimeState.GREEN, [RegimeState.RED, RegimeState.RED]) == RegimeState.RED


def _score(raw: RegimeState, points: int) -> RegimeScore:
    return RegimeScore(raw, points, {"test": Component(1.0, points)})


def test_snapshot_recompute_is_noop_but_changed_output_crashes(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    target = date(2026, 7, 20)
    score = _score(RegimeState.GREEN, 4)

    first = save_snapshot(conn, target, score)
    second = save_snapshot(conn, target, score)

    assert first == second == RegimeState.GREEN
    assert conn.execute("SELECT COUNT(*) FROM regime_snapshots").fetchone()[0] == 1
    with pytest.raises(ValueError, match="different rules output"):
        save_snapshot(conn, target, _score(RegimeState.YELLOW, 0))


def _bars(ticker: str, count: int) -> list[PriceBar]:
    start = date(2024, 1, 1)
    return [
        PriceBar(
            ticker=ticker,
            bar_date=start + timedelta(days=index),
            open=100,
            high=100,
            low=100,
            close=100,
            adj_close=100,
            volume=100,
            source="test",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for index in range(count)
    ]


def test_backtest_renders_changes_without_writing_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path / "synthetic.db")
    bars = _bars("SPY", 506) + _bars("QQQ", 506)
    upsert_daily_prices(conn, bars)
    scores = iter(
        [
            _score(RegimeState.GREEN, 4),
            _score(RegimeState.RED, -4),
            _score(RegimeState.RED, -4),
        ]
    )
    monkeypatch.setattr("app.regime.run.score_regime", lambda spy, qqq: next(scores))
    start = date(2024, 1, 1) + timedelta(days=503)

    text = render_backtest(conn, start, start + timedelta(days=2))

    assert f"- {start}: GREEN" in text
    assert f"- {start + timedelta(days=2)}: RED" in text
    assert "## Score time series" in text
    assert conn.execute("SELECT COUNT(*) FROM regime_snapshots").fetchone()[0] == 0


def test_historical_regime_replay_ignores_future_rows() -> None:
    conn = connect(":memory:")
    first = _score(RegimeState.GREEN, 1)
    original = save_snapshot(conn, date(2026, 7, 20), first)
    save_snapshot(conn, date(2026, 7, 22), _score(RegimeState.RED, -4))
    assert save_snapshot(conn, date(2026, 7, 20), first) == original
    with pytest.raises(ValueError, match="future snapshots"):
        save_snapshot(conn, date(2026, 7, 21), first)
    assert conn.execute("SELECT COUNT(*) FROM regime_snapshots").fetchone()[0] == 2
    conn.close()
