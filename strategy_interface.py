"""
Thin `Strategy` interface (Section 4) wrapping the 8 existing strategy functions so the
selector and UI (per-tick "what does every strategy want to do" signal matrix) can iterate a
uniform list of objects. No strategy math is touched here — every adapter just calls straight
into the existing, working `check_*` function in strategies.py / strategy_*.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Features:
    """Bundle of everything a strategy's check_* function might need. Built once per tick by
    the orchestrator/scanner and passed to every strategy identically."""
    candles: list                       # primary (e.g. 5-minute) OHLCV series, ascending
    candles_15m: Optional[list] = None  # higher-timeframe series (also used as htf_candles)
    htf_trend: str = "neutral"
    config: Optional[dict] = None
    regime: Optional[str] = None        # precomputed market regime, if the caller has one


def _normalize_signal(sig: Optional[dict]) -> Optional[dict]:
    """Additive normalization: injects a `direction` ("long"/"short") plus `entry`/`stop`/
    `target` aliases for the spec's Signal field names, without removing or renaming any of the
    existing entry_price/stop_loss/target_1 keys main.py already reads."""
    if not sig:
        return None
    strat_name = sig.get("strategy", "")
    sig.setdefault("direction", "long" if "Buy" in strat_name or "buy" in strat_name.lower() else "short")
    sig.setdefault("entry", sig.get("entry_price"))
    sig.setdefault("stop", sig.get("stop_loss"))
    sig.setdefault("target", sig.get("target_1"))
    sig.setdefault("confidence", sig.get("confidence_score", sig.get("confidence")))
    return sig


class Strategy(ABC):
    name: str = "Strategy"

    @abstractmethod
    def generate(self, features: Features) -> Optional[dict]:
        """Returns a signal dict (direction/entry/stop/target/confidence, plus the strategy's
        own native fields) or None if no signal fires."""
        raise NotImplementedError

    @abstractmethod
    def suitable_regimes(self) -> list:
        raise NotImplementedError


class ORBStrategy(Strategy):
    name = "ORB"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategies import check_orb_strategy
        return _normalize_signal(check_orb_strategy(features.candles, 5, 15, features.htf_trend))


class VWAPPullbackStrategy(Strategy):
    name = "VWAP-Pullback"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down", "ranging"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategies import check_vwap_pullback_strategy
        return _normalize_signal(check_vwap_pullback_strategy(features.candles, features.htf_trend))


class MomentumStrategy(Strategy):
    name = "Momentum"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategies import check_momentum_breakout_strategy
        return _normalize_signal(check_momentum_breakout_strategy(features.candles, features.htf_trend))


class MeanReversionStrategy(Strategy):
    name = "MeanReversion"

    def suitable_regimes(self) -> list:
        return ["choppy", "ranging"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategies import check_mean_reversion_strategy
        return _normalize_signal(check_mean_reversion_strategy(features.candles))


class TrendFollowStrategy(Strategy):
    name = "TrendFollow"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategies import check_trend_following_strategy
        return _normalize_signal(check_trend_following_strategy(features.candles, features.htf_trend))


class VWAPTrendPullbackStrategy(Strategy):
    name = "VWAPTrendPullback"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategy_vwap_trend_pullback import check_vwap_trend_pullback
        return _normalize_signal(check_vwap_trend_pullback(
            features.candles, htf_candles=features.candles_15m,
            config=features.config, htf_trend=features.htf_trend,
        ))


class SupportResistanceStrategy(Strategy):
    name = "SupportResistance"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down", "ranging", "choppy"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategy_support_resistance import check_support_resistance_strategy
        return _normalize_signal(check_support_resistance_strategy(
            features.candles, candles_15m=features.candles_15m,
            config=features.config, htf_trend=features.htf_trend,
        ))


class CandlestickConfluenceStrategy(Strategy):
    name = "CandlestickConfluence"

    def suitable_regimes(self) -> list:
        return ["trending_up", "trending_down", "ranging", "choppy"]

    def generate(self, features: Features) -> Optional[dict]:
        from strategy_candlestick_confluence import check_candlestick_confluence_strategy
        return _normalize_signal(check_candlestick_confluence_strategy(
            features.candles, candles_15m=features.candles_15m,
            config=features.config, htf_trend=features.htf_trend,
        ))


ALL_STRATEGIES: list[Strategy] = [
    ORBStrategy(),
    VWAPPullbackStrategy(),
    MomentumStrategy(),
    MeanReversionStrategy(),
    TrendFollowStrategy(),
    VWAPTrendPullbackStrategy(),
    SupportResistanceStrategy(),
    CandlestickConfluenceStrategy(),
]


def generate_signal_matrix(features: Features) -> dict:
    """Runs every strategy for the current tick and returns {strategy_name: signal_or_None} —
    the full "what does every strategy want to do right now" view the Cockpit UI needs (Section
    8 Tab 1), not just the selector's single winning pick."""
    matrix = {}
    for strategy in ALL_STRATEGIES:
        try:
            matrix[strategy.name] = strategy.generate(features)
        except Exception as e:
            matrix[strategy.name] = {"error": str(e)}
    return matrix
