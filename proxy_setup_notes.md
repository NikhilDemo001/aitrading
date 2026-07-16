# Upstox Proxy Setup & Resume Plan (June 12, 2026)

This file contains the notes and current state of the bot's proxy configuration. If you start a new conversation next week, share this file with the AI assistant to immediately resume from this exact spot.

---

## 1. Current Status (As of Today)

- **Code & Config Updates:**
  - The bot in `upstox_intraday_helper - Copy - Copy` has been fully configured to route all traffic through the proxy.
  - [config.json](file:///C:/Users/nikhi/.gemini/antigravity/scratch/upstox_intraday_helper%20-%20Copy%20-%20Copy/config.json) has been updated with the proxy connection string and `"access_token"` has been cleared (ready for a fresh login).
  - [upstox_client.py](file:///C:/Users/nikhi/.gemini/antigravity/scratch/upstox_intraday_helper%20-%20Copy%20-%20Copy/upstox_client.py) has been modified to load the proxy settings and apply them to the `requests.Session()` object for all API calls.
- **Proxy Verification:**
  - We verified that the proxy works perfectly. Opening the URL `https://127.0.0.1:5000/api/my-ip` in the browser returns the proxy's static IP: **`175.111.136.31`**.

---

## 2. Proxy Credentials Reference

- **Host:** `175.111.136.31`
- **Port:** `50100` (HTTP/HTTPS) / `50101` (SOCKS5)
- **Username / Password:** stored locally in `.env` as `PROXY_URL` — never in this repo.
- **Static IP Address:** `175.111.136.31` (This is the IP that must be registered on Upstox)

---

## 3. The Lockout Issue

Upstox restricts IP modifications at the user account level to **once per calendar week**. Because an IP was modified on June 11 (yesterday), Upstox is blocking any IP updates on existing apps or the creation of new apps with a different IP today.

---

## 4. Next Steps (To do next week — around June 18, 2026 or after Monday reset)

1. **Register the IP on Upstox:**
   - Log into your [Upstox Developer Console](https://developer.upstox.com/).
   - Edit your app (or create a new app named `intra`).
   - Set the **Primary IP** to: **`175.111.136.31`**.
2. **If you created a new app:**
   - Copy the new **API Key** and **API Secret**.
   - Update `"api_key"` and `"api_secret"` in your [config.json](file:///C:/Users/nikhi/.gemini/antigravity/scratch/upstox_intraday_helper%20-%20Copy%20-%20Copy/config.json).
3. **Authenticate & Start the Bot:**
   - Go to **[https://127.0.0.1:5000/](https://127.0.0.1:5000/)** in your browser.
   - Click **Login** to perform the OAuth login and generate a fresh access token for the day.
   - Toggle the bot to **STARTED** on the dashboard.
