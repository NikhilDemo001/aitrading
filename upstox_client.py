import os
import json
import gzip
import urllib.parse
import requests
import time
import threading
from datetime import datetime


class RateLimiter:
    """Thread-safe rate limiter using a sliding window of request timestamps."""
    def __init__(self, max_calls=10, period=1.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    now = time.time()
            self.calls.append(now)


class UpstoxClient:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.session = requests.Session()
        self._rate_limiter = RateLimiter(max_calls=10, period=1.0)

        # Override session.request to apply rate-limiting to all Upstox API requests
        original_request = self.session.request
        def rate_limited_request(*args, **kwargs):
            url = args[1] if len(args) > 1 else kwargs.get("url", "")
            if "api.upstox.com" in url:
                self._rate_limiter.wait()
            return original_request(*args, **kwargs)
        self.session.request = rate_limited_request

        self.load_config()
        self.instrument_map_path = "instrument_map.json"
        self.instrument_map = {}
        self.futures_map_path = "futures_map.json"
        self.futures_map = {}
        self._delivery_symbols = set()
        self.options_map_path = "options_map.json"
        self.options_map = {}
        self.load_instrument_map()

    def _update_env_var(self, key, value):
        env_path = ".env"
        if not os.path.exists(env_path):
            if os.path.exists(".env.template"):
                import shutil
                shutil.copy(".env.template", env_path)
            else:
                with open(env_path, "w") as f:
                    pass

        try:
            with open(env_path, "r") as f:
                lines = f.readlines()
        except Exception:
            lines = []

        key_found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                key_found = True
                break

        if not key_found:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"{key}={value}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)

    def load_config(self):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        with open(self.config_path, "r") as f:
            self.config = json.load(f)

        self.api_key = os.environ.get("UPSTOX_API_KEY") or self.config.get("api_key")
        self.api_secret = os.environ.get("UPSTOX_API_SECRET") or self.config.get("api_secret")
        self.redirect_uri = os.environ.get("UPSTOX_REDIRECT_URI") or self.config.get("redirect_uri")
        self.access_token = os.environ.get("UPSTOX_ACCESS_TOKEN") or self.config.get("access_token")
        self.proxy = os.environ.get("PROXY_URL") or self.config.get("proxy")

        self.paper_trading = self.config.get("paper_trading", True)
        if hasattr(self, "session") and self.proxy:
            self.session.proxies = {
                "http": self.proxy,
                "https": self.proxy
            }

    def save_config(self):
        # We don't save environment variable keys to config.json to keep it clean
        cfg_copy = dict(self.config)
        # Only write settings keys (do not overwrite credentials in config.json if they are empty)
        with open(self.config_path, "w") as f:
            json.dump(cfg_copy, f, indent=2)

    def load_instrument_map(self):
        if os.path.exists(self.instrument_map_path):
            try:
                with open(self.instrument_map_path, "r") as f:
                    self.instrument_map = json.load(f)
                print(f"Loaded {len(self.instrument_map)} instruments from local map.")
            except Exception as e:
                print(f"Error loading local instrument map: {e}")
                self.instrument_map = {}
        if os.path.exists(self.futures_map_path):
            try:
                with open(self.futures_map_path, "r") as f:
                    self.futures_map = json.load(f)
                print(f"Loaded futures contracts for {len(self.futures_map)} underlyings.")
            except Exception as e:
                print(f"Error loading futures map: {e}")
                self.futures_map = {}
        if os.path.exists(self.options_map_path):
            try:
                with open(self.options_map_path, "r") as f:
                    self.options_map = json.load(f)
                print(f"Loaded options contracts for {len(self.options_map)} underlyings.")
            except Exception as e:
                print(f"Error loading options map: {e}")
                self.options_map = {}

    def get_auth_url(self):
        """Generates the authorization URL for user login."""
        encoded_redirect = urllib.parse.quote(self.redirect_uri, safe="")
        return f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={self.api_key}&redirect_uri={encoded_redirect}"

    def exchange_code(self, code):
        """Exchanges authorization code for access token."""
        url = "https://api.upstox.com/v2/login/authorization/token"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "code": code,
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code"
        }
        
        response = self.session.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            self.access_token = res_json.get("access_token")
            # Update in environment and .env file
            os.environ["UPSTOX_ACCESS_TOKEN"] = self.access_token
            try:
                self._update_env_var("UPSTOX_ACCESS_TOKEN", self.access_token)
            except Exception as e:
                print(f"Failed to update .env with access token: {e}")
            self.config["access_token"] = self.access_token
            self.save_config()
            print("Access token successfully acquired and saved!")
            return True
        else:
            print(f"Failed to exchange code: {response.status_code} - {response.text}")
            return False

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def download_instruments(self, force=False):
        """Downloads the NSE/BSE equity instruments list and builds the map."""
        if not force and os.path.exists(self.instrument_map_path) and len(self.instrument_map) > 0 \
                 and os.path.exists(self.futures_map_path) and len(self.futures_map) > 0 \
                 and os.path.exists(self.options_map_path) and len(self.options_map) > 0:
            mod_date = datetime.fromtimestamp(os.path.getmtime(self.instrument_map_path)).date()
            if mod_date == datetime.now().date():
                return   # already fresh today
            
        print("Downloading instruments from Upstox...")
        scan_bse = self.config.get("scan_bse", False)
        exchanges = ["NSE"]
        if scan_bse:
            exchanges.append("BSE")

        new_map = {}
        fut_map = {}
        opt_map = {}

        for exchange in exchanges:
            print(f"Downloading {exchange} instruments...")
            url = f"https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
            try:
                response = self.session.get(url, stream=True, timeout=15)
                if response.status_code == 200:
                    temp_gz_file = f"{exchange.lower()}_instruments.json.gz"
                    with open(temp_gz_file, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024):
                            f.write(chunk)
                    
                    # Decompress and parse
                    with gzip.open(temp_gz_file, "rb") as f:
                        instruments = json.loads(f.read().decode("utf-8"))
                    
                    # Filter NSE/BSE equities + stock futures & options (for F&O mode)
                    for inst in instruments:
                        segment = inst.get("segment")
                        inst_type = inst.get("instrument_type")

                        if segment in ("NSE_EQ", "BSE_EQ") and inst_type == "EQ":
                            symbol = inst.get("trading_symbol")
                            # If symbol exists in both, prefer NSE
                            if symbol in new_map and segment == "BSE_EQ":
                                continue
                            new_map[symbol] = {
                                "instrument_key": inst.get("instrument_key"),
                                "name": inst.get("name"),
                                "tick_size": inst.get("tick_size"),
                                "lot_size": inst.get("lot_size")
                            }
                        elif segment == "NSE_FO" and inst_type == "FUT" and exchange == "NSE":
                            underlying = inst.get("underlying_symbol")
                            if not underlying:
                                continue
                            expiry_ms = inst.get("expiry") or 0
                            fut_map.setdefault(underlying, []).append({
                                "instrument_key": inst.get("instrument_key"),
                                "trading_symbol": inst.get("trading_symbol"),
                                "expiry_date": datetime.fromtimestamp(expiry_ms / 1000).date().isoformat(),
                                "lot_size": int(inst.get("lot_size") or 1),
                            })
                        elif segment == "NSE_FO" and inst_type in ("CE", "PE") and exchange == "NSE":
                            underlying = inst.get("underlying_symbol")
                            if not underlying:
                                continue
                            expiry_ms = inst.get("expiry") or 0
                            opt_map.setdefault(underlying, []).append({
                                "instrument_key": inst.get("instrument_key"),
                                "trading_symbol": inst.get("trading_symbol"),
                                "expiry_date": datetime.fromtimestamp(expiry_ms / 1000).date().isoformat(),
                                "lot_size": int(inst.get("lot_size") or 1),
                                "strike_price": float(inst.get("strike_price") or 0.0),
                                "option_type": inst_type,
                                "weekly": bool(inst.get("weekly", False))
                            })
                    
                    if os.path.exists(temp_gz_file):
                        os.remove(temp_gz_file)
                else:
                    print(f"Failed to download {exchange} instruments: status code {response.status_code}")
            except Exception as e:
                print(f"Error downloading {exchange} instruments: {e}")

        if new_map:
            for contracts in fut_map.values():
                contracts.sort(key=lambda c: c["expiry_date"])
            for contracts in opt_map.values():
                contracts.sort(key=lambda c: (c["expiry_date"], c["strike_price"]))

            self.instrument_map = new_map
            with open(self.instrument_map_path, "w") as f:
                json.dump(self.instrument_map, f, indent=2)
            self.futures_map = fut_map
            with open(self.futures_map_path, "w") as f:
                json.dump(self.futures_map, f, indent=2)
            self.options_map = opt_map
            with open(self.options_map_path, "w") as f:
                json.dump(self.options_map, f, indent=2)
            print(f"Instruments download complete. Saved {len(self.instrument_map)} symbols, futures for {len(self.futures_map)} underlyings, options for {len(self.options_map)} underlyings.")

    def get_instrument_info(self, symbol):
        return self.instrument_map.get(symbol)

    def get_future_for(self, symbol):
        """Returns the nearest-expiry (not expiring today) stock future for an
        underlying equity symbol, or None if no F&O contract exists."""
        contracts = self.futures_map.get(symbol) or []
        today = datetime.now().date().isoformat()
        for c in contracts:   # sorted by expiry ascending
            if c.get("expiry_date", "") > today:   # strictly after today — roll on expiry day
                return c
        return None

    def get_option_for(self, symbol, option_type, spot_price):
        """Returns the nearest-expiry ATM option contract for the underlying symbol,
        option_type (CE or PE), closest to the spot_price."""
        contracts = self.options_map.get(symbol) or []
        today = datetime.now().date().isoformat()
        valid_contracts = [
            c for c in contracts
            if c.get("option_type") == option_type and c.get("expiry_date", "") > today
        ]
        if not valid_contracts:
            return None

        # Find the nearest expiry date
        nearest_expiry = min(c.get("expiry_date") for c in valid_contracts)
        expiry_contracts = [c for c in valid_contracts if c.get("expiry_date") == nearest_expiry]

        if not expiry_contracts:
            return None

        # Pick the contract with strike closest to spot_price
        best_contract = min(expiry_contracts, key=lambda c: abs(c.get("strike_price", 0.0) - spot_price))
        return best_contract

    def fetch_nifty50_symbols(self):
        """Downloads the official Nifty 50 constituent list from NSE.
        Returns a list of trading symbols, or [] on failure."""
        url = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            import csv, io
            response = self.session.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"Failed to fetch Nifty 50 list: status code {response.status_code}")
                return []
            reader = csv.DictReader(io.StringIO(response.text))
            symbols = [row["Symbol"].strip().upper() for row in reader if row.get("Symbol", "").strip()]
            return symbols
        except Exception as e:
            print(f"Error fetching Nifty 50 list: {e}")
            return []

    @staticmethod
    def _v3_interval(interval):
        """Maps v2-style interval names to v3 (unit, interval) URL segments."""
        mapping = {
            "1minute": ("minutes", "1"),
            "3minute": ("minutes", "3"),
            "5minute": ("minutes", "5"),
            "15minute": ("minutes", "15"),
            "30minute": ("minutes", "30"),
            "1hour": ("hours", "1"),
            "day": ("days", "1"),
            "week": ("weeks", "1"),
            "month": ("months", "1"),
        }
        if interval not in mapping:
            raise Exception(f"Unsupported candle interval: {interval}")
        return mapping[interval]

    def get_intraday_candles(self, instrument_key, interval="5minute"):
        """Fetches current day's candles as a list of dicts."""
        if not self.access_token:
            raise Exception("No access token. Please login.")

        unit, iv = self._v3_interval(interval)
        url = f"https://api.upstox.com/v3/historical-candle/intraday/{instrument_key}/{unit}/{iv}"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                candles = data["data"]["candles"]
                # Upstox returns candles in descending order (latest first)
                candles.reverse()
                
                candle_list = []
                for c in candles:
                    candle_list.append({
                        "timestamp": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5])
                    })
                return candle_list
        print(f"Error fetching candles for {instrument_key}: {response.text}")
        return []

    def get_historical_candles(self, instrument_key, interval, from_date, to_date):
        """
        Fetch historical OHLCV candles for a date range.
        interval: '1minute','5minute','15minute','30minute','1hour','day'
        from_date / to_date: 'YYYY-MM-DD'
        Returns list of candle dicts in ascending (oldest first) order.
        """
        if not self.access_token:
            raise Exception("No access token. Please login.")
        unit, iv = self._v3_interval(interval)
        url = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/{unit}/{iv}/{to_date}/{from_date}"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                candles = data["data"]["candles"]
                candles.reverse()  # ascending order
                return [
                    {
                        "timestamp": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5]),
                        "oi": int(c[6]) if len(c) > 6 else 0,
                    }
                    for c in candles
                ]
        print(f"Error fetching historical candles for {instrument_key}: {response.text}")
        return []

    def get_market_quote(self, instrument_key):
        """Fetches the latest market quote (LTP)."""
        if not self.access_token:
            raise Exception("No access token. Please login.")
            
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={instrument_key}"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status") == "success":
                data = res_json.get("data") or {}
                # API keys quotes by "EXCHANGE:TRADING_SYMBOL", not instrument_key —
                # match on the embedded instrument_token instead.
                quote = data.get(instrument_key)
                if not quote:
                    for v in data.values():
                        if v.get("instrument_token") == instrument_key:
                            quote = v
                            break
                if not quote and len(data) == 1:
                    quote = next(iter(data.values()))
                if quote:
                    return {
                        "ltp": float(quote["last_price"]),
                        "open": float(quote.get("ohlc", {}).get("open", 0)),
                        "high": float(quote.get("ohlc", {}).get("high", 0)),
                        "low": float(quote.get("ohlc", {}).get("low", 0)),
                        "close": float(quote.get("ohlc", {}).get("close", 0)),
                        "volume": int(quote.get("volume") or 0),
                        "net_change": float(quote.get("net_change", 0.0))
                    }
        print(f"Error fetching quote for {instrument_key}: {response.text}")
        return None

    def get_market_quotes(self, instrument_keys):
        """Fetches the latest market quotes (LTP) in a single batch request."""
        if not self.access_token or not instrument_keys:
            return {}
            
        keys_str = ",".join(instrument_keys)
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={urllib.parse.quote(keys_str)}"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status") == "success":
                data = res_json.get("data") or {}
                result = {}
                for key in instrument_keys:
                    quote = data.get(key)
                    if not quote:
                        for v in data.values():
                            if v.get("instrument_token") == key:
                                quote = v
                                break
                    if not quote and len(data) == 1:
                        quote = next(iter(data.values()))
                    if quote:
                        result[key] = {
                            "ltp": float(quote["last_price"]),
                            "open": float(quote.get("ohlc", {}).get("open", 0)),
                            "high": float(quote.get("ohlc", {}).get("high", 0)),
                            "low": float(quote.get("ohlc", {}).get("low", 0)),
                            "close": float(quote.get("ohlc", {}).get("close", 0)),
                            "volume": int(quote.get("volume") or 0),
                            "net_change": float(quote.get("net_change", 0.0))
                        }
                return result
        print(f"Error fetching batch quotes: {response.text}")
        return {}

    def place_order(self, symbol, transaction_type, quantity, order_type="MARKET", price=0.0, trigger_price=0.0, tag="auto_bot", instrument_key=None, product=None):
        """Places an order (either mock paper-trade or live).
        instrument_key: optional explicit key (e.g. an NSE_FO futures contract);
        defaults to the symbol's NSE_EQ equity instrument."""
        if not instrument_key:
            inst_info = self.get_instrument_info(symbol)
            if not inst_info:
                raise Exception(f"Unknown instrument key for symbol {symbol}")
            instrument_key = inst_info["instrument_key"]
        
        if self.paper_trading:
            print(f"[PAPER TRADE] Placing {transaction_type} order for {symbol}: {quantity} shares")
            quote = self.get_market_quote(instrument_key)
            fill_price = quote["ltp"] if quote else (price if price > 0 else 100.0)
            
            # For paper stop loss orders, mark status as TRIGGER_PENDING and use mock SL ID prefix
            if "SL" in order_type:
                order_id = f"MOCK-SL-{int(datetime.now().timestamp() * 1000)}"
                status = "TRIGGER_PENDING"
                fill_price = trigger_price if trigger_price > 0 else price
            else:
                order_id = f"MOCK-{int(datetime.now().timestamp() * 1000)}"
                status = "FILLED"
                
            trade_details = {
                "order_id": order_id,
                "symbol": symbol,
                "instrument_key": instrument_key,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "price": fill_price,
                "order_type": order_type,
                "timestamp": datetime.now().isoformat(),
                "status": status
            }
            return trade_details
            
        if product is None:
            product = "D" if symbol in self._delivery_symbols else "I"

        url = "https://api.upstox.com/v2/order/place"
        body = {
            "quantity": quantity,
            "product": product,
            "validity": "DAY",
            "price": price if order_type != "MARKET" else 0,
            "tag": tag,
            "instrument_token": instrument_key,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": trigger_price,
            "is_amo": False
        }
        
        response = self.session.post(url, headers=self.get_headers(), json=body, timeout=10)
        
        # Retry as Delivery order if Intraday is not allowed
        if response.status_code == 400:
            res_text = response.text
            if "UDAPI100500" in res_text or "Intraday order is not allowed" in res_text:
                # In Indian markets, short selling (SELL entry) is strictly prohibited as Delivery (CNC).
                # We can only fall back to Delivery if it is a BUY order (long entry) or an exit order (e.g. autobot_sl, autobot_exit).
                if transaction_type == "SELL" and tag not in ("autobot_sl", "autobot_exit"):
                    raise Exception(f"Short selling is not allowed on delivery-only scrip {symbol} (Intraday MIS blocked by broker).")
                
                print(f"[LIVE TRADE] Intraday order not allowed for {symbol}. Retrying as Delivery order (CNC)...")
                self._delivery_symbols.add(symbol)
                body["product"] = "D"
                response = self.session.post(url, headers=self.get_headers(), json=body, timeout=10)

        if response.status_code == 200 or response.status_code == 201:
            res_json = response.json()
            if res_json.get("status") == "success":
                order_id = res_json["data"]["order_id"]
                print(f"[LIVE TRADE] Order placed successfully! Order ID: {order_id}")
                # For MARKET orders, fetch actual fill price from LTP
                fill_price = price
                if order_type == "MARKET":
                    try:
                        quote = self.get_market_quote(instrument_key)
                        if quote:
                            fill_price = quote["ltp"]
                    except Exception:
                        pass
                return {
                    "order_id": order_id,
                    "symbol": symbol,
                    "instrument_key": instrument_key,
                    "transaction_type": transaction_type,
                    "quantity": quantity,
                    "price": fill_price,
                    "order_type": order_type,
                    "timestamp": datetime.now().isoformat(),
                    "status": "SUBMITTED"
                }
        raise Exception(f"Failed to place order via Upstox: {response.status_code} - {response.text}")

    def _token_expired(self):
        """Returns True if the stored JWT access token has passed its exp claim."""
        if not self.access_token:
            return True
        try:
            import base64, json as _j
            payload = self.access_token.split('.')[1]
            payload += '=' * (4 - len(payload) % 4)
            data = _j.loads(base64.b64decode(payload))
            return data.get('exp', 0) < datetime.now().timestamp()
        except Exception:
            return False

    def try_refresh_token(self):
        """
        L2 Auto-Reauth: Attempts to obtain a new access token using client credentials
        and stored configuration (if client id, secret and code/redirect are present).
        Returns True if successful, False otherwise.
        """
        # Since standard Upstox access tokens do not support refreshing without a new code
        # in standard API setups, we can attempt to check if a saved code/env exists,
        # or if we can mock a refresh in paper trading.
        if self.paper_trading:
            # For paper trading, simply extend token lifetime or generate a new mock token
            log_token = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ"
            # mock standard payload with future expiry (1 day)
            import json as _j, base64
            mock_payload = {
                "sub": "FP0592",
                "iat": int(datetime.now().timestamp()),
                "exp": int((datetime.now() + timedelta(days=1)).timestamp())
            }
            payload_b64 = base64.b64encode(_j.dumps(mock_payload).encode('utf-8')).decode('utf-8').rstrip('=')
            mock_token = f"{log_token}.{payload_b64}.mocksignature"
            self.access_token = mock_token
            os.environ["UPSTOX_ACCESS_TOKEN"] = self.access_token
            self.config["access_token"] = self.access_token
            self.save_config()
            return True
            
        # In live mode, we can try to re-read environment to see if a cron job updated the token
        try:
            self.load_config()
            if self.access_token and not self._token_expired():
                return True
        except Exception:
            pass
        return False

    def cancel_order(self, order_id):
        """Cancels a pending order."""
        if self.paper_trading:
            return {"status": "success", "order_id": order_id}
            
        url = f"https://api.upstox.com/v2/order/cancel?order_id={order_id}"
        response = self.session.delete(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            return response.json()
        print(f"Failed to cancel order {order_id}: {response.text}")
        return None

    def get_funds_and_margin(self):
        """Fetches funds and margin details from Upstox API."""
        if self.paper_trading:
            # For paper trading, simulate a default capital of ₹1,00,000 or config setting
            paper_capital = float(self.config.get("paper_capital", 100000.0))
            return {
                "status": "success",
                "data": {
                    "equity": {
                        "available_margin": paper_capital
                    }
                }
            }
            
        url = "https://api.upstox.com/v2/user/get-funds-and-margin"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            return response.json()
        print(f"Error fetching funds and margin: {response.status_code} - {response.text}")
        return None

    def modify_order(self, order_id, quantity, order_type, price, trigger_price=0.0):
        """Modifies a pending order."""
        if self.paper_trading:
            print(f"[PAPER TRADE] Modifying order {order_id} on broker: Qty {quantity} | Price {price} | Trigger {trigger_price}")
            return {"status": "success", "order_id": order_id}
            
        url = "https://api.upstox.com/v2/order/modify"
        body = {
            "order_id": order_id,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "trigger_price": trigger_price,
            "validity": "DAY"
        }
        response = self.session.put(url, headers=self.get_headers(), json=body, timeout=10)
        if response.status_code == 200 or response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to modify order: {response.status_code} - {response.text}")

    def get_order_status(self, order_id):
        """Retrieves the current status of an order."""
        if self.paper_trading:
            if "MOCK-SL-" in order_id:
                # To simulate SL triggers, we will check if the price crossed the trigger in main.py,
                # so we can return TRIGGER_PENDING here.
                return "TRIGGER_PENDING"
            return "FILLED"
            
        url = f"https://api.upstox.com/v2/order/history?order_id={order_id}"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status") == "success" and res_json.get("data"):
                history = res_json["data"]
                if history:
                    status = history[0].get("status")
                    # Map Upstox's "complete" execution status to "FILLED" for bot compatibility
                    if status == "complete":
                        return "FILLED"
                    return status
        return "UNKNOWN"

