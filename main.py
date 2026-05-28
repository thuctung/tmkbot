"""
TradingView Webhook → EMA Signal → Telegram Notifier
Nhận tín hiệu từ TradingView, tính EMA50/EMA200, gửi cảnh báo Telegram
"""

import os
import json
import logging
from collections import deque
from datetime import datetime

import requests
from flask import Flask, request, jsonify

# ── Cấu hình ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")   # Bot token từ @BotFather
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "") # Chat/Group ID
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "my_secret_key")  # Bảo mật webhook
MAX_CANDLES     = 210  # Giữ đủ nến để tính EMA200

EMA_SHORT = 50
EMA_LONG  = 200

# ── App & Logging ──────────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Lưu trữ nến theo từng symbol/timeframe ────────────────────────────────────
# Cấu trúc: price_store[symbol][timeframe] = deque of close prices
price_store: dict[str, dict[str, deque]] = {}

# Trạng thái tín hiệu trước đó (để phát hiện cross)
signal_state: dict[str, dict] = {}

# ── Helper: Tính EMA ──────────────────────────────────────────────────────────
def calc_ema(prices: list[float], period: int) -> float | None:
    """Tính EMA của `period` nến từ list giá đóng cửa."""
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 4)

# ── Helper: Gửi Telegram ──────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram chưa cấu hình – bỏ qua gửi tin.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Telegram gửi thành công.")
        return True
    except Exception as e:
        log.error(f"Telegram lỗi: {e}")
        return False

# ── Logic phát hiện tín hiệu ──────────────────────────────────────────────────
def detect_signals(symbol: str, tf: str, close: float,
                   ema50: float | None, ema200: float | None) -> list[str]:
    """
    Phát hiện:
    - Giá chạm / vượt EMA50  (±0.1%)
    - Giá chạm / vượt EMA200 (±0.1%)
    """
    signals = []
    key = f"{symbol}_{tf}"
    prev = signal_state.get(key, {})
    threshold = 0.001  # 0.1% vùng "chạm"

    def near(price, ema):
        return abs(price - ema) / ema <= threshold

    def crossed_above(price, ema, prev_price, prev_ema):
        if prev_price is None or prev_ema is None:
            return False
        return prev_price <= prev_ema and price > ema

    def crossed_below(price, ema, prev_price, prev_ema):
        if prev_price is None or prev_ema is None:
            return False
        return prev_price >= prev_ema and price < ema

    prev_close = prev.get("close")
    prev_ema50  = prev.get("ema50")
    prev_ema200 = prev.get("ema200")

    # ── EMA50 ──
    if ema50:
        if near(close, ema50):
            signals.append(("touch_ema50", f"🔵 <b>{symbol} [{tf}]</b> Giá chạm EMA50\n"
                            f"Giá: <b>{close}</b> | EMA50: <b>{ema50}</b>"))
        elif crossed_above(close, ema50, prev_close, prev_ema50):
            signals.append(("cross_above_ema50", f"🟢 <b>{symbol} [{tf}]</b> Giá vượt lên trên EMA50 📈\n"
                            f"Giá: <b>{close}</b> | EMA50: <b>{ema50}</b>"))
        elif crossed_below(close, ema50, prev_close, prev_ema50):
            signals.append(("cross_below_ema50", f"🔴 <b>{symbol} [{tf}]</b> Giá phá xuống dưới EMA50 📉\n"
                            f"Giá: <b>{close}</b> | EMA50: <b>{ema50}</b>"))

    # ── EMA200 ──
    if ema200:
        if near(close, ema200):
            signals.append(("touch_ema200", f"🟠 <b>{symbol} [{tf}]</b> Giá chạm EMA200\n"
                            f"Giá: <b>{close}</b> | EMA200: <b>{ema200}</b>"))
        elif crossed_above(close, ema200, prev_close, prev_ema200):
            signals.append(("cross_above_ema200", f"🚀 <b>{symbol} [{tf}]</b> Giá vượt lên trên EMA200 – BULLISH 📈\n"
                            f"Giá: <b>{close}</b> | EMA200: <b>{ema200}</b>"))
        elif crossed_below(close, ema200, prev_close, prev_ema200):
            signals.append(("cross_below_ema200", f"💀 <b>{symbol} [{tf}]</b> Giá phá xuống dưới EMA200 – BEARISH 📉\n"
                            f"Giá: <b>{close}</b> | EMA200: <b>{ema200}</b>"))

    # Lưu trạng thái
    signal_state[key] = {"close": close, "ema50": ema50, "ema200": ema200}
    return [s[1] for s in signals]

# ── Webhook endpoint ───────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    TradingView gửi JSON dạng:
    {
      "secret":    "my_secret_key",
      "symbol":    "BTCUSDT",
      "timeframe": "1h",
      "close":     67500.0
    }
    """
    # Kiểm tra Content-Type
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON không hợp lệ"}), 400

    # Xác thực secret
    if data.get("secret") != WEBHOOK_SECRET:
        log.warning("Webhook secret sai!")
        return jsonify({"error": "Unauthorized"}), 401

    symbol = data.get("symbol", "UNKNOWN").upper()
    tf     = data.get("timeframe", "?")
    close  = float(data.get("close", 0))

    if close <= 0:
        return jsonify({"error": "Giá close không hợp lệ"}), 400

    # Lưu giá vào buffer
    if symbol not in price_store:
        price_store[symbol] = {}
    if tf not in price_store[symbol]:
        price_store[symbol][tf] = deque(maxlen=MAX_CANDLES)

    price_store[symbol][tf].append(close)
    prices = list(price_store[symbol][tf])
    count  = len(prices)

    # Tính EMA
    ema50  = calc_ema(prices, EMA_SHORT) if count >= EMA_SHORT  else None
    ema200 = calc_ema(prices, EMA_LONG)  if count >= EMA_LONG   else None

    log.info(f"{symbol} [{tf}] Close={close} | EMA50={ema50} | EMA200={ema200} | Bars={count}")

    # Phát hiện và gửi tín hiệu
    msgs = detect_signals(symbol, tf, close, ema50, ema200)
    now  = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    for msg in msgs:
        full_msg = f"{msg}\n🕐 {now}"
        log.info(f"Tín hiệu: {full_msg}")
        send_telegram(full_msg)

    return jsonify({
        "symbol":  symbol,
        "tf":      tf,
        "close":   close,
        "ema50":   ema50,
        "ema200":  ema200,
        "bars":    count,
        "signals": len(msgs),
    }), 200


# ── Status endpoint ────────────────────────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    summary = {}
    for sym, tfs in price_store.items():
        summary[sym] = {tf: len(prices) for tf, prices in tfs.items()}
    return jsonify({"status": "ok", "data": summary})


# ── Chạy local ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
