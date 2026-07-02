# Upstox Intraday Trading Bot - Ultimate Reference Manual

This document provides a deep, comprehensive, and detailed explanation of the **Upstox Intraday Trading Bot**. It serves as an ultimate reference guide for traders, developers, and system administrators to understand the inner workings, mathematics, execution sequences, code structures, and expansion pathways of the bot.

---

## 1. Core Application Concept & Philosophy
Intraday trading is highly fast-paced. A human trader often struggles with emotional decision-making, speed of execution, and monitoring multiple stocks simultaneously. 

This application replaces human screen monitoring with **automated computer routines**. The system is built on three core pillars:
1.  **Rule-based Scanning**: Eliminates human bias. Technical patterns are calculated strictly mathematically.
2.  **Instant Execution**: Places orders in milliseconds once criteria are met, securing optimal prices.
3.  **Capital Protection**: Hardcoded stop-losses and maximum daily loss limits ensure that a single bad day does not blow up your trading account.

---

## 2. Deep Dive: Code Files & System Architecture

The project is structured modularly. Here is the deep explanation of what each file does:

### A. SSL Certificate Generator (`generate_certs.py`)
Upstox Developer portal mandates that all Redirect URLs use secure HTTPS protocol. Since our web server runs locally (`localhost`), we need a local SSL Certificate.
- **How it works**: Uses the python `cryptography` library to generate an asymmetric RSA 2048-bit private key (`key.pem`) and a self-signed X.509 certificate (`cert.pem`).
- **Technical Detail**: The certificate includes a `SubjectAlternativeName` extension linking to `localhost` and `127.0.0.1` so modern browsers like Chrome recognize it as a valid SSL endpoint for local development.

### B. Upstox API v2 Wrapper Client (`upstox_client.py`)
This file is the bridge between our bot and the Upstox servers. It handles all raw HTTP communication.
- **Login Flow (OAuth 2.0)**:
  1.  Generates a login dialog URL using your `API Key` (Client ID).
  2.  After you login on Upstox, Upstox redirects back with a temporary authorization code: `https://127.0.0.1:5000/callback?code=AUTH_CODE`.
  3.  `exchange_code()` makes a `POST` request to `https://api.upstox.com/v2/login/authorization/token` with the `AUTH_CODE`, `API Key`, and `API Secret`.
  4.  Upstox returns a secure, long-lived `access_token` valid until 3:30 AM IST the next day.
- **Instrument Search & Caching**:
  - Upstox has thousands of tradable assets. Downloading details on every startup is slow.
  - `download_instruments()` downloads the NSE Equity Master file in gzipped JSON format (`nse_equity.json.gz`), filters out equity shares (EQ segment), and saves a mapped dictionary (`instrument_map.json`) mapping tickers (e.g., `RELIANCE` -> `NSE_EQ|INE002A01018`) for instant lookup.
- **Data Pulling**:
  - `get_intraday_candles()`: Calls the GET endpoint `https://api.upstox.com/v2/historical-candle/intraday/{instrument_key}/5minute` to fetch the current day's OHLCV values.
  - `get_market_quote()`: Calls GET `https://api.upstox.com/v2/market-quote/quotes` to fetch the Last Traded Price (LTP).
- **Order Placement**:
  - Configures standard order parameters: Product Type is set to `"I"` (Intraday/MIS), validity is `"DAY"`.
  - Places orders via `POST https://api.upstox.com/v2/order/place`.
  - **Paper Trading Mode**: If enabled in `config.json`, the client bypasses the order placement HTTP request entirely, generates a mock `order_id` (e.g. `MOCK-1718029302`), fetches the live LTP, and returns a simulated filled trade record.

### C. Technical Indicator & Strategy Engine (`strategies.py`)
This file contains the core algorithms and mathematical rules.

#### 1. Exponential Moving Average (EMA) Mathematics
Unlike a Simple Moving Average (SMA) which gives equal weight to all prices in the period, the EMA gives higher weight to recent prices.
- **Formula**:
  $$\text{EMA}_{\text{today}} = \left(\text{Price}_{\text{today}} \times \frac{2}{\text{Period} + 1}\right) + \left(\text{EMA}_{\text{yesterday}} \times \left(1 - \frac{2}{\text{Period} + 1}\right)\right)$$
- **Code implementation**: 
  Calculated sequentially. The first EMA value (at index `period - 1`) is initialized as the SMA of the first `period` elements. All subsequent values use the multiplier.

#### 2. Volume Weighted Average Price (VWAP) Mathematics
VWAP represents the average price a stock has traded at throughout the day, based on both volume and price.
- **Formula**:
  $$\text{VWAP} = \frac{\sum (\text{Typical Price} \times \text{Volume})}{\sum \text{Volume}}$$
  Where Typical Price is:
  $$\text{Typical Price} = \frac{\text{High} + \text{Low} + \text{Close}}{3}$$
- **Code implementation**:
  Maintains cumulative sums of `Typical Price * Volume` and `Volume` from the first candle of the day (9:15 AM) onwards. Dividing them gives the VWAP at any specific minute of the day.

#### 3. Opening Range Breakout (ORB) Algorithm
- **Range Definition**: Captures candles between 9:15 AM and 9:30 AM.
  - Range High = maximum high price of the first 3 candles.
  - Range Low = minimum low price of the first 3 candles.
- **Breakout Condition**:
  - **Buy**: If candle close crosses *above* Range High, AND the close is above the 20 EMA.
  - **Short**: If candle close crosses *below* Range Low, AND the close is below the 20 EMA.
- **Risk Management**:
  - Stop Loss (SL) = Mid-point of the range, or the current 20 EMA value (whichever is closer to entry, protecting against wide stop-losses).
  - Target 1 = Entry + (1.5 * Risk).
  - Target 2 = Entry + (2.0 * Risk).

#### 4. VWAP + EMA Pullback Algorithm
- **Uptrend check**: The candle close must be above the current VWAP.
- **Pullback check**: The low of the pullback candle must touch or dip below the 9 EMA, but must remain strictly *above* the VWAP (low > VWAP).
- **Trigger**: The next candle must close higher than its open (green candle) and close *above* the 9 EMA. This confirms support holds and momentum is returning.
- **Stop Loss (SL)**: Set slightly below the low of the pullback candle or below the VWAP line.

### D. FastAPI Backend Server (`main.py`)
Manages system life-cycle and local persistence.
- **Database/Persistence**: Uses simple, lightweight JSON files (`active_positions.json` and `trade_history.json`) to persist state across server restarts.
- **Background Scanner Thread**:
  Runs a continuous loop every 10 seconds:
  1. Checks safety limit: Is daily PNL lower than `-max_daily_loss`? If yes, square off all and stop bot.
  2. Checks clock: Is time past square-off time? (e.g. 3:10 PM). If yes, close all open trades.
  3. Checks scan window: Is time between 9:30 AM and 2:30 PM?
  4. Manages current positions: Fetches quote LTP. Checks if LTP has hit target or stop-loss. If yes, exits.
  5. Scans Watchlist: If active positions < max open positions limit, scans candles of watchlist stocks. If a strategy triggers a buy/sell signal, places order and saves the position details.

### E. Frontend UI Dashboard (`static/`)
A responsive single-page application built on top of Tailwind-like custom glassmorphic styling:
- **`app.js`**: Polls the server API (`/api/status`, `/api/positions`, `/api/trades`, `/api/logs`) every 3 seconds to keep stats, logs, and tables in sync.
- **`Lightweight Charts`**: Renders an interactive TradingView candlestick chart. Overlays the calculated EMA 20 (blue line) and VWAP (orange line) indicators.
- **Watchlist Navigation**: When you click a stock in the watchlist, the dashboard fetches its 5-minute intraday candles and renders its chart dynamically.

---

## 3. Complete Step-by-Step Life Cycle of a Trade

Here is the exact lifecycle of how the bot processes a trade, from discovery to closure:

```
[ Market Hour: 9:30 AM ]
           │
           ▼
[ Scanner reads watchlist stock: e.g., INFY ] ──> Calls Upstox API for 5-min candles
           │
           ▼
[ strategies.py processes candle data ]
   ├── Calculates EMA 20 & VWAP
   └── Checks ORB Breakout (INFY closes above 15-min range high of ₹1,420)
           │
           ▼
[ Signal Generated: Buy INFY at ₹1,422, SL at ₹1,412, Target at ₹1,437 ]
           │
           ▼
[ main.py runs checks ]
   ├── Open positions count (current is 0, limit is 3) -> OK
   └── Daily loss limit (current PNL is ₹0, limit is -₹1000) -> OK
           │
           ▼
[ upstox_client.py places order ]
   ├── Calculates Quantity: risking ₹200 / (Risk per share of ₹10) = 20 shares
   └── Places Market BUY order for 20 shares
           │
           ▼
[ Position Saved to active_positions.json ] ──> Updates frontend dashboard table
           │
           ▼
[ Loop monitors INFY price every 10 seconds ]
   ├── Option A: Price rises to target ₹1,437 ──> Trigger Target Exit
   ├── Option B: Price drops to Stop Loss ₹1,412 ──> Trigger Stop Loss Exit
   └── Option C: Clock hits 3:10 PM IST ──> Trigger Time-based Square Off
           │
           ▼
[ Exit Execution ]
   ├── Places Market SELL order for 20 shares
   ├── Computes final PnL (e.g. 20 shares * +₹15 = +₹300 profit)
   └── Saves to trade_history.json & updates dashboard tables
```

---

## 4. How to Transition from Paper to Live Trading

By default, the bot runs in **Paper Trading Mode** (simulation) to protect your money. When you are confident in the system's logic and want to trade with real capital:

1.  **Reactivate Segments**: Ensure your Upstox account segments are active (check profile on `upstox.com`).
2.  **Verify Connection**: Log into the bot via the dashboard and ensure "Connection Status" displays **"Connected"**.
3.  **Disable Paper Trading**:
    - Go to the **Safety Settings** panel on the bottom-right of the dashboard.
    - Toggle the **"Paper Trading Mode"** switch to **OFF**.
    - Click **"Save Settings"**.
4.  **Confirm UI Status**: The "Trading Mode" card at the top will turn red and display: **"LIVE Trading (Real Capital)"**.
5.  **Watch the Bot**: The bot will now place actual buy/sell orders in your Upstox account. Start with small quantities by editing the max risk settings in `main.py` (default: `max_risk_per_trade = 200.0`).

---

## 5. Maintenance, Debugging, & Future Enhancements

### Debugging Logs
- If anything fails, check the Python console/terminal. The server prints detailed logs for every request.
- Trade logs and position files (`active_positions.json`, `trade_history.json`) can be viewed directly in a text editor to verify states.

### Updating Watchlist
The watchlist is stored in `config.json`. You can modify it using standard stock symbols:
```json
"watchlist": [
  "RELIANCE",
  "TCS",
  "INFY",
  "HDFCBANK",
  "ICICIBANK"
]
```
*(Always ensure tickers are in uppercase and are liquid NSE index stocks).*
