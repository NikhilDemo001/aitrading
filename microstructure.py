"""Order-book (market depth) parsing + spread/liquidity gating (plan:
docs/superpowers/plans/2026-07-08-market-depth-integration.md).

The bot receives Upstox 5-level depth on every quote but discarded it. These pure functions
normalize it and turn it into a liquidity gate (skip wide-spread/illiquid names) and a real
observed spread for the fill model. Defensive: bad/missing depth returns None / allows."""

from __future__ import annotations


def normalize_depth(raw_depth):
    """Upstox depth {'buy':[{price,quantity,orders}...], 'sell':[...]} -> normalized dict, or
    None if depth is missing/empty/crossed/zero. Uses top of book (level 0)."""
    try:
        buy = (raw_depth or {}).get("buy") or []
        sell = (raw_depth or {}).get("sell") or []
        if not buy or not sell:
            return None
        best_bid = float(buy[0].get("price") or 0)
        best_ask = float(sell[0].get("price") or 0)
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            return None
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_qty": int(buy[0].get("quantity") or 0),
            "ask_qty": int(sell[0].get("quantity") or 0),
            "mid": round((best_bid + best_ask) / 2.0, 2),
            "spread": round(best_ask - best_bid, 2),
        }
    except Exception:
        return None


def spread_bps(best_bid, best_ask):
    """Bid-ask spread in basis points of mid. None on bad input."""
    try:
        mid = (best_bid + best_ask) / 2.0
        if mid <= 0:
            return None
        return (best_ask - best_bid) / mid * 10000.0
    except Exception:
        return None


def liquidity_ok(book, order_qty=None, *, max_spread_bps=50.0, min_depth_ratio=0.5):
    """(ok, reason). Reject when the spread is too wide (illiquid) or, if order_qty is given,
    top-of-book depth can't cover min_depth_ratio * order_qty. book=None (no data) -> allow,
    fail-open, so a missing feed never blocks trading."""
    try:
        if not book:
            return True, "no depth (allow)"
        sb = spread_bps(book["best_bid"], book["best_ask"])
        if sb is not None and sb > max_spread_bps:
            return False, f"spread {sb:.0f}bps > {max_spread_bps:.0f}bps"
        if order_qty:
            top = min(book.get("bid_qty", 0), book.get("ask_qty", 0))
            if top < min_depth_ratio * order_qty:
                return False, f"thin book: top {top} < {min_depth_ratio:.0%} of order {order_qty}"
        return True, "ok"
    except Exception:
        return True, "ok (guard error, fail-open)"
