"""Realistic paper fills + NSE intraday-equity transaction costs (plan:
docs/superpowers/plans/2026-07-08-realistic-fills-and-costs.md).

Paper orders otherwise fill at the exact LTP with zero charges, which flatters every result.
`apply_fill_slippage` models the price you actually get (buy lifts the offer, sell hits the bid);
`intraday_equity_charges` models the real round-trip fees/taxes that eat small intraday profits.
Pure functions — defensive, config-driven from the callers."""

from __future__ import annotations


def apply_fill_slippage(ltp, transaction_type, *, spread_bps=3.0, slippage_bps=2.0,
                        real_spread_bps=None):
    """Realistic paper fill price. A BUY lifts the offer (pays more), a SELL hits the bid
    (receives less), by (half the spread + slippage) in basis points of price. When
    `real_spread_bps` is provided (from the live order book), it replaces the fixed config
    spread so fills reflect the actual observed spread. Returns ltp unchanged for a
    non-positive/absent price."""
    try:
        if ltp is None or ltp <= 0:
            return ltp
        sb = real_spread_bps if (real_spread_bps is not None and real_spread_bps > 0) else spread_bps
        adj = (sb / 2.0 + slippage_bps) / 10000.0
        if str(transaction_type).upper() == "BUY":
            return round(ltp * (1 + adj), 2)
        return round(ltp * (1 - adj), 2)
    except Exception:
        return ltp


def intraday_equity_charges(buy_value, sell_value, *, brokerage_per_order=20.0,
                            stt_pct=0.00025, exchange_txn_pct=0.0000297,
                            gst_pct=0.18, sebi_per_crore=10.0, stamp_pct=0.00003):
    """Round-trip NSE intraday-equity charges. Returns a breakdown dict incl. 'total'.

    - Brokerage per leg = min(brokerage_per_order, 2.5% of leg value); round trip = buy + sell.
    - STT: sell side only (0.025% intraday).
    - Exchange transaction charge: on turnover (buy+sell).
    - GST: 18% on (brokerage + exchange charge).
    - SEBI: per crore of turnover.
    - Stamp duty: buy side only (0.003%).
    """
    try:
        buy_value = max(0.0, float(buy_value or 0.0))
        sell_value = max(0.0, float(sell_value or 0.0))
        turnover = buy_value + sell_value
        brokerage = (min(brokerage_per_order, 0.025 * buy_value)
                     + min(brokerage_per_order, 0.025 * sell_value))
        stt = stt_pct * sell_value
        exchange = exchange_txn_pct * turnover
        gst = gst_pct * (brokerage + exchange)
        sebi = sebi_per_crore / 1e7 * turnover
        stamp = stamp_pct * buy_value
        total = brokerage + stt + exchange + gst + sebi + stamp
        return {
            "brokerage": round(brokerage, 2), "stt": round(stt, 2),
            "exchange": round(exchange, 4), "gst": round(gst, 2),
            "sebi": round(sebi, 4), "stamp": round(stamp, 2), "total": round(total, 2),
        }
    except Exception:
        return {"brokerage": 0.0, "stt": 0.0, "exchange": 0.0, "gst": 0.0,
                "sebi": 0.0, "stamp": 0.0, "total": 0.0}
