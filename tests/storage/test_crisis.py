from datetime import timedelta
from pathlib import Path

from app.storage.crisis import crisis_reasons, exposure_check, market_relative_move
from app.storage.database import connect
from tests.storage.test_holding_reviews import MONDAY_MORNING, close_bar, snapshot_at


def regime(conn: object, published: str, raw: str) -> None:
    conn.execute(  # type: ignore[attr-defined]
        "INSERT OR REPLACE INTO regime_snapshots VALUES "
        "('2026-09-18', ?, ?, 0, '{}', '2026-09-18T21:00:00+00:00')",
        (published, raw),
    )


def test_calm_markets_raise_no_crisis(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    regime(conn, "GREEN", "GREEN")
    for day, close in (("2026-09-17", 500.0), ("2026-09-18", 498.0)):
        close_bar(conn, "QQQ", day, close)
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)}, qqq=497.0)

    assert crisis_reasons(conn, snapshot, MONDAY_MORNING) == []
    conn.close()


def test_every_sign_of_stress_is_named(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    regime(conn, "GREEN", "YELLOW")
    for day, close in (("2026-09-17", 500.0), ("2026-09-18", 480.0)):
        close_bar(conn, "QQQ", day, close)
    snapshot_at(conn, tmp_path, MONDAY_MORNING - timedelta(days=3), {"NVDA": (0.1, 200, 200)})
    snapshot = snapshot_at(
        conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 150)}, equity=95.0, qqq=462.0
    )

    assert crisis_reasons(conn, snapshot, MONDAY_MORNING) == [
        "qqq_fell_3_percent_at_the_last_close",
        "qqq_down_3_percent_today",
        "account_down_3_percent_today",
        "raw_regime_off_green",
    ]
    conn.close()


def test_exposure_is_judged_against_the_stricter_of_the_published_and_raw_bands(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    regime(conn, "GREEN", "YELLOW")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.4, 200, 200)})

    exposure = exposure_check(conn, snapshot, MONDAY_MORNING)

    assert (exposure["invested_percent"], exposure["over_exposed"]) == (80.0, True)
    assert exposure["raw_band_percent"] == [40, 70]
    conn.close()


def test_a_holding_moving_with_its_beta_has_little_excess_move(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    from datetime import date

    day = date(2026, 6, 1)
    for index in range(61):
        stamp = (day + timedelta(days=index)).isoformat()
        market = 400.0 * (1.01 if index % 2 else 0.99) ** (index % 3)
        close_bar(conn, "QQQ", stamp, market)
        close_bar(conn, "NVDA", stamp, market / 2)
    close_bar(conn, "QQQ", "2026-09-18", 400.0)
    close_bar(conn, "NVDA", "2026-09-18", 200.0)
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 190)}, qqq=380.0)

    relative = market_relative_move(conn, snapshot, "NVDA", MONDAY_MORNING)

    assert relative["move_since_last_close_percent"] == -5.0
    assert relative["qqq_move_since_last_close_percent"] == -5.0
    assert relative["beta_to_qqq"] == 1.0
    assert relative["excess_move_percent"] == 0.0
    conn.close()
