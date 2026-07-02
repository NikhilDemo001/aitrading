"""
market_feed.py — decoupled market-data feed with a thread-safe price cache.

Why this exists
---------------
The trading loops previously did a REST round-trip (`get_market_quotes`) on every
tick, so decision latency was gated by network latency. This module puts a swappable
feed in front of an in-memory cache: a background producer keeps the latest prices
warm, and consumers read them in O(1) without blocking. Consumers ALWAYS fall back to
a direct REST fetch when the cache is stale or the feed is down, so the bot is never
blind, and broker-side stop-loss orders remain the hard safety net regardless.

Implementations
---------------
  RestPollFeed : background thread polling client.get_market_quotes (works today).
  UpstoxWsFeed : Upstox V3 protobuf websocket feed — FOLLOW-UP, validated at market
                 open. Until then create_feed() transparently falls back to RestPollFeed.

Design notes
------------
* All cache access is mutex-guarded; the producer runs in a daemon thread and the
  asyncio loops are the consumers.
* `healthy()` reports whether fresh data is flowing, which is what the consumer uses
  to decide between the cache and a direct REST call.
"""

import json
import time
import uuid
import threading


class PriceCache:
    """Thread-safe store of the latest quote per instrument_key, with timestamps."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}   # instrument_key -> {"quote": dict, "ts": float}

    def update_many(self, quotes_by_key):
        now = time.time()
        with self._lock:
            for key, quote in quotes_by_key.items():
                self._data[key] = {"quote": quote, "ts": now}

    def get(self, key, max_age=None):
        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return None
            if max_age is not None and (time.time() - rec["ts"]) > max_age:
                return None
            return rec["quote"]

    def get_many(self, keys, max_age=None):
        out = {}
        now = time.time()
        with self._lock:
            for key in keys:
                rec = self._data.get(key)
                if rec and (max_age is None or (now - rec["ts"]) <= max_age):
                    out[key] = rec["quote"]
        return out


class MarketFeed:
    """Base interface for a price feed backed by a PriceCache."""

    def __init__(self, client):
        self.client = client
        self.cache = PriceCache()
        self._keys = set()
        self._keys_lock = threading.Lock()
        self._running = False
        self._last_success = 0.0

    def set_keys(self, keys):
        """Replace the working subscription set with exactly `keys`."""
        with self._keys_lock:
            self._keys = set(keys)

    def keys(self):
        with self._keys_lock:
            return list(self._keys)

    def get_many(self, keys, max_age=None):
        return self.cache.get_many(keys, max_age=max_age)

    def healthy(self, max_age=3.0):
        """True if the feed is running and produced fresh data within max_age seconds."""
        return self._running and (time.time() - self._last_success) <= max_age

    # lifecycle — overridden by implementations
    def start(self):
        raise NotImplementedError

    def stop(self):
        self._running = False


class RestPollFeed(MarketFeed):
    """Keeps the cache warm via a dedicated background REST polling thread."""

    def __init__(self, client, interval=1.0):
        super().__init__(client)
        self.interval = max(0.2, float(interval))
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="RestPollFeed", daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            keys = self.keys()
            if keys:
                try:
                    quotes = self.client.get_market_quotes(keys)
                    if quotes:
                        self.cache.update_many(quotes)
                        self._last_success = time.time()
                except Exception as e:
                    print(f"[RestPollFeed] poll error: {e}")
            time.sleep(self.interval)


class UpstoxWsFeed(MarketFeed):
    """Upstox V3 protobuf websocket market-data feed.

    Lifecycle (background daemon thread):
      authorize (REST) -> wss connect -> binary 'sub' for desired keys -> recv loop
      decoding FeedResponse protobuf into the price cache. Reconnects with backoff on
      any error; re-subscribes on (re)connect; honours set_keys() via sub/unsub deltas.

    The decode path is unit-tested offline against the *official* compiled proto
    (round-trip), so only the live transport/authorize is validated at market open.
    If the token is missing/expired or the socket drops, healthy() goes false and the
    consumer transparently falls back to direct REST — the bot is never blind.

    data_mode: one of 'ltpc' (lightest, LTP+close), 'full', 'option_greeks', 'full_d30'.
    """

    AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

    def __init__(self, client, data_mode="ltpc", backoff=(1, 2, 5, 10), recv_timeout=5):
        super().__init__(client)
        self.data_mode = data_mode if data_mode in ("ltpc", "full", "option_greeks", "full_d30") else "ltpc"
        self._backoff = backoff
        self._recv_timeout = recv_timeout
        self._thread = None
        self._ws = None
        self._wire_keys = set()   # keys currently subscribed on the live socket
        self._pb = None

    # ── lifecycle ──
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="UpstoxWsFeed", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def _authorize(self):
        headers = {
            "Authorization": f"Bearer {self.client.access_token}",
            "Accept": "application/json",
        }
        resp = self.client.session.get(self.AUTHORIZE_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        uri = (data.get("data") or {}).get("authorized_redirect_uri") or (data.get("data") or {}).get("authorizedRedirectUri")
        if not uri:
            raise RuntimeError(f"authorize response missing wss uri: {data}")
        return uri

    def _run(self):
        import websocket  # websocket-client
        import MarketDataFeedV3_pb2 as pb
        self._pb = pb
        attempt = 0
        while self._running:
            try:
                if not self.client.access_token:
                    raise RuntimeError("no access token")
                wss = self._authorize()
                self._ws = websocket.create_connection(
                    wss, 
                    timeout=self._recv_timeout,
                    ping_interval=20,
                    ping_timeout=5
                )
                attempt = 0
                self._wire_keys = set()
                self._sync_subscription()   # subscribe to all desired keys
                while self._running:
                    try:
                        msg = self._ws.recv()
                    except websocket.WebSocketTimeoutException:
                        self._sync_subscription()   # apply any set_keys() changes even when quiet
                        continue
                    if msg:
                        if isinstance(msg, (bytes, bytearray)):
                            self._on_message(bytes(msg))
                    self._sync_subscription()
            except Exception as e:
                print(f"[UpstoxWsFeed] connection error: {e}")
            finally:
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None
            if not self._running:
                break
            time.sleep(self._backoff[min(attempt, len(self._backoff) - 1)])
            attempt += 1

    # ── subscription ──
    def _sync_subscription(self):
        desired = set(self.keys())
        add = desired - self._wire_keys
        remove = self._wire_keys - desired
        if add:
            self._send("sub", list(add))
        if remove:
            self._send("unsub", list(remove))
        self._wire_keys = desired

    def _send(self, method, keys):
        if not self._ws or not keys:
            return
        import websocket
        payload = json.dumps({
            "guid": uuid.uuid4().hex,
            "method": method,
            "data": {"mode": self.data_mode, "instrumentKeys": keys},
        }).encode("utf-8")
        self._ws.send(payload, opcode=websocket.ABNF.OPCODE_BINARY)

    # ── decode ──
    @staticmethod
    def _extract_ltpc(feed):
        which = feed.WhichOneof("FeedUnion")
        if which == "ltpc":
            return feed.ltpc
        if which == "fullFeed":
            sub = feed.fullFeed.WhichOneof("FullFeedUnion")
            if sub == "marketFF":
                return feed.fullFeed.marketFF.ltpc
            if sub == "indexFF":
                return feed.fullFeed.indexFF.ltpc
        if which == "firstLevelWithGreeks":
            return feed.firstLevelWithGreeks.ltpc
        return None

    def decode(self, data):
        """Decode a FeedResponse frame into {instrument_key: quote-dict}. Public for testing."""
        pb = self._pb
        if pb is None:
            import MarketDataFeedV3_pb2 as pb
            self._pb = pb
        fr = pb.FeedResponse()
        fr.ParseFromString(data)
        updates = {}
        for key, feed in fr.feeds.items():
            ltpc = self._extract_ltpc(feed)
            if ltpc is None or not ltpc.ltp:
                continue
            ltp = float(ltpc.ltp)
            cp = float(ltpc.cp) if ltpc.cp else ltp
            updates[key] = {
                "ltp": ltp,
                "close": cp,
                "net_change": round(ltp - cp, 2),
                "open": 0.0, "high": 0.0, "low": 0.0, "volume": 0,
            }
        return updates

    def _on_message(self, data):
        try:
            updates = self.decode(data)
        except Exception as e:
            print(f"[UpstoxWsFeed] decode error: {e}")
            return
        if updates:
            self.cache.update_many(updates)
            self._last_success = time.time()


def create_feed(client, mode="rest", interval=1.0):
    """Factory. mode='ws' selects the Upstox V3 protobuf websocket feed; 'rest' (default)
    selects the REST polling feed. The ws feed self-falls-back to REST behaviour at the
    consumer level (via healthy()) whenever it can't connect or data goes stale."""
    if mode == "ws":
        return UpstoxWsFeed(client)
    return RestPollFeed(client, interval=interval)
