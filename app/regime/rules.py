"""REVIEW-REQUIRED: maintainer approval is required before decision consumption."""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from app.prices.cache import PriceBar
from app.schemas.decision_record import RegimeState


@dataclass(frozen=True)
class Component:
    value: float
    points: int


@dataclass(frozen=True)
class RegimeScore:
    raw_regime: RegimeState
    score: int
    components: dict[str, Component]


def trend(close: float, sma_200: float) -> Component:
    return Component(close / sma_200 - 1, 2 if close > sma_200 else -2)


def trend_slope(sma_50: float, sma_200: float) -> Component:
    return Component(sma_50 / sma_200 - 1, 1 if sma_50 > sma_200 else -1)


def drawdown_component(drawdown: float) -> Component:
    magnitude = abs(drawdown)
    if magnitude < 0.05:
        points = 2
    elif magnitude < 0.10:
        points = 0
    elif magnitude <= 0.20:
        points = -2
    else:
        points = -4
    return Component(drawdown, points)


def volatility_component(percentile: float) -> Component:
    if percentile < 60:
        points = 1
    elif percentile <= 85:
        points = -1
    else:
        points = -3
    return Component(percentile, points)


def _sma(values: Sequence[float], sessions: int) -> float:
    return sum(values[-sessions:]) / sessions


def _realized_volatility(closes: Sequence[float]) -> float:
    returns = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    return statistics.pstdev(returns) * math.sqrt(252)


def _volatility_percentile(closes: Sequence[float]) -> float:
    window = closes[-504:]
    values = [_realized_volatility(window[end - 20 : end + 1]) for end in range(20, len(window))]
    current = values[-1]
    return sum(value < current for value in values) / len(values) * 100


def score_regime(spy: Sequence[PriceBar], qqq: Sequence[PriceBar]) -> RegimeScore:
    if len(spy) < 504 or len(qqq) < 504:
        raise ValueError("regime scoring requires at least 504 sessions for SPY and QQQ")
    spy_closes = [bar.close for bar in spy]
    qqq_closes = [bar.close for bar in qqq]
    components = {
        "spy_trend": trend(spy_closes[-1], _sma(spy_closes, 200)),
        "qqq_trend": trend(qqq_closes[-1], _sma(qqq_closes, 200)),
        "spy_trend_slope": trend_slope(_sma(spy_closes, 50), _sma(spy_closes, 200)),
        "qqq_trend_slope": trend_slope(_sma(qqq_closes, 50), _sma(qqq_closes, 200)),
    }
    spy_drawdown = spy_closes[-1] / max(spy_closes[-252:]) - 1
    qqq_drawdown = qqq_closes[-1] / max(qqq_closes[-252:]) - 1
    components["drawdown"] = drawdown_component(min(spy_drawdown, qqq_drawdown))
    components["spy_volatility"] = volatility_component(_volatility_percentile(spy_closes))
    score = sum(component.points for component in components.values())
    raw = (
        RegimeState.GREEN if score >= 4 else RegimeState.RED if score <= -4 else RegimeState.YELLOW
    )
    return RegimeScore(raw_regime=raw, score=score, components=components)


def publish_regime(previous: RegimeState | None, raw_history: Sequence[RegimeState]) -> RegimeState:
    current = raw_history[-1]
    if previous is None:
        return current
    if current != previous and len(raw_history) >= 2 and raw_history[-2] == current:
        return current
    return previous
