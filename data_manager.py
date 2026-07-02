"""
Downloads and caches historical OHLCV data from Upstox.
Cache lives in historical_cache/ to avoid redundant API calls.
"""
import os
import json
import time
from datetime import datetime, timedelta

CACHE_DIR = "historical_cache"


class DataManager:
    def __init__(self, client):
        self.client = client
        os.makedirs(CACHE_DIR, exist_ok=True)

    # ── Cache helpers ──────────────────────────────────────────────────────────

    def _cache_path(self, symbol, interval, from_date, to_date):
        return os.path.join(CACHE_DIR, f"{symbol}_{interval}_{from_date}_{to_date}.json")

    def _load_cache(self, path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_cache(self, path, data):
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Cache write error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def fetch(self, symbol, interval, from_date, to_date, force_refresh=False):
        """
        Return candles for symbol/interval/date-range.
        Uses disk cache when available. force_refresh bypasses cache.
        """
        cache_path = self._cache_path(symbol, interval, from_date, to_date)

        if not force_refresh and os.path.exists(cache_path):
            data = self._load_cache(cache_path)
            if data is not None:
                return data

        inst = self.client.get_instrument_info(symbol)
        if not inst:
            print(f"[DataManager] Unknown symbol: {symbol}")
            return []

        print(f"[DataManager] Fetching {symbol} {interval} {from_date}→{to_date}…")
        candles = self.client.get_historical_candles(
            inst["instrument_key"], interval, from_date, to_date
        )

        if candles:
            self._save_cache(cache_path, candles)
        else:
            print(f"[DataManager] No data returned for {symbol} {interval}")

        time.sleep(0.3)  # gentle rate limiting
        return candles

    def fetch_multi(self, symbols, interval, from_date, to_date,
                    progress_cb=None, force_refresh=False):
        """
        Fetch candles for a list of symbols.
        Returns {symbol: [candles]}.
        """
        result = {}
        for i, sym in enumerate(symbols):
            if progress_cb:
                progress_cb(i + 1, len(symbols), sym)
            result[sym] = self.fetch(sym, interval, from_date, to_date, force_refresh)
        return result

    def organize_by_day(self, candles):
        """
        Split a flat candle list into {date_str: [candles]} dict.
        Date is the YYYY-MM-DD prefix of each candle's timestamp.
        """
        by_day = {}
        for c in candles:
            date_str = str(c.get("timestamp", ""))[:10]
            if date_str:
                by_day.setdefault(date_str, []).append(c)
        # Sort each day's candles ascending (should already be, but guard)
        for d in by_day:
            by_day[d].sort(key=lambda c: c["timestamp"])
        return by_day

    @staticmethod
    def trading_dates(from_date, to_date):
        """Return list of weekday date strings (YYYY-MM-DD) in the range."""
        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt = datetime.strptime(to_date, "%Y-%m-%d")
        dates = []
        curr = from_dt
        while curr <= to_dt:
            if curr.weekday() < 5:
                dates.append(curr.strftime("%Y-%m-%d"))
            curr += timedelta(days=1)
        return dates
