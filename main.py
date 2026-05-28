"""
Gold M5 EMA Bot
───────────────
Nguồn giá  : Twelve Data — nến M5 (5 phút) realtime
Tín hiệu   : Giá chạm / vượt EMA50 & EMA200
Thông báo  : Telegram
Status page: HTTP server tích hợp — xem tại /
"""

import os, time, threading, logging
from collections import deque
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

# ── Cấu hình ──────────────────────────────────────────────────────────────────
TWELVE_API_KEY   = os.getenv("TWELVE_API_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOL           = "XAU/USD"
INTERVAL         = "5min"          # ← M5
CHECK_EVERY_SEC  = int(os.getenv("CHECK_INTERVAL", "300"))
TOUCH_PCT        = float(os.getenv("TOUCH_THRESHOLD", "0.1"))
MAX_BARS         = 250
EMA_SHORT        = 50
EMA_LONG         = 200
PRELOAD_BARS     = 210
PORT             = int(os.getenv("PORT", "8080"))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Shared state (thread-safe reads vì chỉ 1 writer) ─────────────────────────
price_buf: deque[float] = deque(maxlen=MAX_BARS)
prev = {"close": None, "ema50": None, "ema200": None}

bot_state = {
    "status":       "starting",   # starting | running | error
    "last_price":   None,
    "last_checked": None,         # ISO string UTC
    "ema50":        None,
    "ema200":       None,
    "bars":         0,
    "signals_sent": 0,
    "uptime_start": datetime.now(timezone.utc).isoformat(),
    "last_signal":  None,
    "last_error":   None,
}

# ══════════════════════════════════════════════════════════════════════════════
# TWELVE DATA
# ══════════════════════════════════════════════════════════════════════════════

BASE = "https://api.twelvedata.com"


def preload_history() -> list[float]:
    """Tải PRELOAD_BARS nến M5 gần nhất — dùng khi khởi động."""
    try:
        log.info(f"⏳ Tải {PRELOAD_BARS} nến M5 lịch sử...")
        r = requests.get(
            f"{BASE}/time_series",
            params={
                "symbol":     SYMBOL,
                "interval":   INTERVAL,
                "outputsize": PRELOAD_BARS,
                "apikey":     TWELVE_API_KEY,
            },
            timeout=15,
        )
        data = r.json()
        if data.get("status") == "error":
            log.warning(f"preload lỗi: {data.get('message')}")
            return []
        candles = data.get("values", [])
        closes  = [float(c["close"]) for c in reversed(candles)]
        log.info(f"✅ Tải xong {len(closes)} nến")
        return closes
    except Exception as e:
        log.error(f"preload_history: {e}")
        return []


def fetch_latest_m5_close() -> float | None:
    """
    Lấy nến M5 mới nhất đã đóng từ Twelve Data.
    Dùng /time_series outputsize=2 để lấy nến đã hoàn thành (index 1).
    """
    try:
        r = requests.get(
            f"{BASE}/time_series",
            params={
                "symbol":     SYMBOL,
                "interval":   INTERVAL,
                "outputsize": 2,
                "apikey":     TWELVE_API_KEY,
            },
            timeout=10,
        )
        data = r.json()
        if data.get("status") == "error":
            log.warning(f"fetch lỗi: {data.get('message')}")
            return None
        candles = data.get("values", [])
        # index 0 = nến mới nhất (có thể chưa đóng)
        # index 1 = nến đã đóng hoàn toàn ← dùng cái này
        if len(candles) < 2:
            return None
        close = float(candles[1]["close"])
        dt    = candles[1]["datetime"]
        log.info(f"[M5 close] {SYMBOL} = {close:.3f}  ({dt})")
        return close
    except Exception as e:
        log.error(f"fetch_latest_m5_close: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# EMA
# ══════════════════════════════════════════════════════════════════════════════

def calc_ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    k   = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 3)


# ══════════════════════════════════════════════════════════════════════════════
# PHÁT HIỆN TÍN HIỆU
# ══════════════════════════════════════════════════════════════════════════════

def detect(close: float, ema50, ema200) -> list[str]:
    global prev
    msgs = []
    pc, pe50, pe200 = prev["close"], prev["ema50"], prev["ema200"]
    thr = TOUCH_PCT / 100

    def near(p, e):           return abs(p - e) / e <= thr
    def x_up(p, e, pp, pe):   return pp is not None and pe is not None and pp <= pe < p
    def x_dn(p, e, pp, pe):   return pp is not None and pe is not None and pp >= pe > p

    if ema50:
        if x_up(close, ema50, pc, pe50):
            msgs.append(f"🟢 <b>VÀNG M5</b> — Giá vượt lên EMA50 📈\nGiá: <b>${close:,.3f}</b>  |  EMA50: <b>${ema50:,.3f}</b>\n⚡ <i>Tín hiệu tăng ngắn hạn</i>")
        elif x_dn(close, ema50, pc, pe50):
            msgs.append(f"🔴 <b>VÀNG M5</b> — Giá phá xuống EMA50 📉\nGiá: <b>${close:,.3f}</b>  |  EMA50: <b>${ema50:,.3f}</b>\n⚡ <i>Tín hiệu giảm ngắn hạn</i>")
        elif near(close, ema50):
            msgs.append(f"🔵 <b>VÀNG M5</b> — Giá chạm vùng EMA50\nGiá: <b>${close:,.3f}</b>  |  EMA50: <b>${ema50:,.3f}</b>\n👀 <i>Theo dõi vùng hỗ trợ / kháng cự</i>")

    if ema200:
        if x_up(close, ema200, pc, pe200):
            msgs.append(f"🚀 <b>VÀNG M5</b> — Vượt EMA200 BULLISH MẠNH! 🔥\nGiá: <b>${close:,.3f}</b>  |  EMA200: <b>${ema200:,.3f}</b>\n📈 <i>Xu hướng tăng dài hạn xác nhận</i>")
        elif x_dn(close, ema200, pc, pe200):
            msgs.append(f"💀 <b>VÀNG M5</b> — Phá EMA200 BEARISH! ⚠️\nGiá: <b>${close:,.3f}</b>  |  EMA200: <b>${ema200:,.3f}</b>\n📉 <i>Cảnh báo đảo chiều xu hướng</i>")
        elif near(close, ema200):
            msgs.append(f"🟠 <b>VÀNG M5</b> — Giá chạm vùng EMA200\nGiá: <b>${close:,.3f}</b>  |  EMA200: <b>${ema200:,.3f}</b>\n👀 <i>Vùng EMA200 — rất quan trọng!</i>")

    prev = {"close": close, "ema50": ema50, "ema200": ema200}
    return msgs


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def tg(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# BOT LOOP (chạy trong thread riêng)
# ══════════════════════════════════════════════════════════════════════════════

def bot_loop():
    global bot_state

    if not TWELVE_API_KEY:
        bot_state["status"]     = "error"
        bot_state["last_error"] = "Thiếu TWELVE_API_KEY"
        log.error("❌ Thiếu TWELVE_API_KEY")
        return

    # Preload lịch sử
    history = preload_history()
    if history:
        price_buf.extend(history)

    bot_state["bars"]   = len(price_buf)
    bot_state["status"] = "running"

    tg(
        f"🤖 <b>Gold M5 EMA Bot online!</b>\n"
        f"📡 Nguồn: Twelve Data — nến M5\n"
        f"📦 Khởi động với {len(price_buf)} nến\n"
        f"⏱ Kiểm tra mỗi 5 phút"
    )

    hourly_tick = 0

    while True:
        try:
            close = fetch_latest_m5_close()

            if close is None:
                bot_state["last_error"] = f"Không lấy được giá lúc {datetime.now(timezone.utc).strftime('%H:%M')}"
                time.sleep(60)
                continue

            price_buf.append(close)
            prices = list(price_buf)
            bars   = len(prices)

            ema50  = calc_ema(prices, EMA_SHORT) if bars >= EMA_SHORT else None
            ema200 = calc_ema(prices, EMA_LONG)  if bars >= EMA_LONG  else None

            # Cập nhật shared state
            now_iso = datetime.now(timezone.utc).isoformat()
            bot_state.update({
                "last_price":   close,
                "last_checked": now_iso,
                "ema50":        ema50,
                "ema200":       ema200,
                "bars":         bars,
                "last_error":   None,
            })

            log.info(f"Close={close:.3f}  EMA50={ema50 or 'N/A'}  EMA200={ema200 or 'N/A'}  Bars={bars}")

            # Tín hiệu
            signals = detect(close, ema50, ema200)
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
            for sig in signals:
                tg(f"{sig}\n🕐 {ts}")
                bot_state["signals_sent"] += 1
                bot_state["last_signal"]   = ts
                log.info("📨 Gửi tín hiệu Telegram")

            # Status mỗi 1 giờ
            hourly_tick += 1
            if hourly_tick >= 12:
                e50  = f"${ema50:,.3f}"  if ema50  else "⏳"
                e200 = f"${ema200:,.3f}" if ema200 else f"⏳ cần {max(0, EMA_LONG - bars)} nến"
                trend = "—"
                if ema50 and ema200:
                    if close > ema50 > ema200:   trend = "📈 Tăng mạnh"
                    elif close < ema50 < ema200: trend = "📉 Giảm mạnh"
                    elif ema50 > ema200:         trend = "🟡 EMA50 trên EMA200"
                    else:                        trend = "🟡 EMA50 dưới EMA200"
                tg(
                    f"📊 <b>VÀNG M5 — Cập nhật {ts}</b>\n"
                    f"{'─'*28}\n"
                    f"💰 Giá:    <b>${close:,.3f}</b>\n"
                    f"📉 EMA50:  <b>{e50}</b>\n"
                    f"📉 EMA200: <b>{e200}</b>\n"
                    f"📌 {trend}\n"
                    f"📦 Nến: {bars}  |  Tín hiệu: {bot_state['signals_sent']}"
                )
                hourly_tick = 0

        except Exception as e:
            bot_state["last_error"] = str(e)
            log.error(f"Lỗi vòng lặp: {e}", exc_info=True)

        time.sleep(CHECK_EVERY_SEC)


# ══════════════════════════════════════════════════════════════════════════════
# STATUS WEB PAGE
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)


def _trend_label():
    c  = bot_state["last_price"]
    e5 = bot_state["ema50"]
    e2 = bot_state["ema200"]
    if not (c and e5 and e2):
        return "⏳ Đang thu thập dữ liệu..."
    if c > e5 > e2:   return "📈 Tăng mạnh  (Giá > EMA50 > EMA200)"
    if c < e5 < e2:   return "📉 Giảm mạnh  (Giá < EMA50 < EMA200)"
    if e5 > e2:       return "🟡 EMA50 trên EMA200"
    return               "🟡 EMA50 dưới EMA200"


@app.route("/")
def index():
    s     = bot_state
    price = f"${s['last_price']:,.3f}" if s["last_price"] else "—"
    e50   = f"${s['ema50']:,.3f}"      if s["ema50"]      else "⏳"
    e200  = f"${s['ema200']:,.3f}"     if s["ema200"]      else f"⏳ cần {max(0, EMA_LONG - s['bars'])} nến nữa"
    checked = s["last_checked"] or "—"
    status_color = {"running": "#22c55e", "starting": "#f59e0b", "error": "#ef4444"}.get(s["status"], "#888")
    status_label = {"running": "🟢 Đang chạy", "starting": "🟡 Đang khởi động", "error": "🔴 Lỗi"}.get(s["status"], s["status"])
    bars_html = (
        f'<div class="progress-wrap"><div class="progress-bar" style="width:{min(100, s["bars"]/EMA_LONG*100):.0f}%"></div></div>'
        f'<small>{s["bars"]} / {EMA_LONG} nến</small>'
    )
    error_html = f'<p class="error">⚠️ {s["last_error"]}</p>' if s["last_error"] else ""
    last_sig   = s["last_signal"] or "Chưa có"

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Gold M5 EMA Bot</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:24px}}
  h1{{font-size:1.6rem;font-weight:700;margin-bottom:4px;color:#fde68a}}
  .sub{{color:#94a3b8;font-size:.85rem;margin-bottom:24px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}}
  .card{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}}
  .card .label{{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:6px}}
  .card .value{{font-size:1.5rem;font-weight:700;color:#f1f5f9}}
  .card .value.big{{font-size:2rem;color:#fbbf24}}
  .status-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;background:{status_color};margin-right:6px;animation:pulse 2s infinite}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
  .trend-box{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155;margin-bottom:24px;font-size:1.1rem}}
  .progress-wrap{{background:#334155;border-radius:8px;height:8px;margin:8px 0 4px}}
  .progress-bar{{background:#22c55e;height:8px;border-radius:8px;transition:width .5s}}
  small{{color:#64748b;font-size:.8rem}}
  .error{{color:#f87171;background:#450a0a;padding:10px 14px;border-radius:8px;margin-top:12px}}
  footer{{margin-top:24px;color:#475569;font-size:.8rem;text-align:center}}
  .refresh{{color:#475569;font-size:.75rem;text-align:right;margin-bottom:8px}}
</style>
</head>
<body>
<h1>🥇 Gold M5 EMA Bot</h1>
<p class="sub">XAUUSD • Khung M5 • EMA50 / EMA200 • Tự động refresh 30 giây</p>
<p class="refresh">Cập nhật lần cuối: {checked}</p>

<div class="grid">
  <div class="card">
    <div class="label">Trạng thái</div>
    <div class="value" style="font-size:1.1rem"><span class="status-dot"></span>{status_label}</div>
  </div>
  <div class="card">
    <div class="label">Giá XAUUSD</div>
    <div class="value big">{price}</div>
  </div>
  <div class="card">
    <div class="label">EMA 50 (M5)</div>
    <div class="value">{e50}</div>
  </div>
  <div class="card">
    <div class="label">EMA 200 (M5)</div>
    <div class="value">{e200}</div>
  </div>
  <div class="card">
    <div class="label">Tín hiệu đã gửi</div>
    <div class="value">{s['signals_sent']}</div>
  </div>
  <div class="card">
    <div class="label">Tín hiệu gần nhất</div>
    <div class="value" style="font-size:1rem">{last_sig}</div>
  </div>
</div>

<div class="trend-box">
  <div class="label" style="margin-bottom:8px">Xu hướng hiện tại</div>
  {_trend_label()}
</div>

<div class="card" style="margin-bottom:16px">
  <div class="label">Tiến trình thu thập dữ liệu EMA200</div>
  {bars_html}
</div>

{error_html}

<footer>Bot chạy từ {s['uptime_start'][:16].replace("T"," ")} UTC &nbsp;•&nbsp; Nguồn: Twelve Data &nbsp;•&nbsp; Interval: 5min</footer>
</body>
</html>"""
    return html


@app.route("/health")
def health():
    return jsonify({"status": bot_state["status"], "uptime": bot_state["uptime_start"]}), 200


@app.route("/api/status")
def api_status():
    return jsonify(bot_state), 200


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# Bot thread khởi động ở module level → chạy được cả gunicorn lẫn python trực tiếp
# ══════════════════════════════════════════════════════════════════════════════

_bot_thread = threading.Thread(target=bot_loop, daemon=True, name="bot-loop")
_bot_thread.start()
log.info(f"🌐 Status page sẽ chạy trên PORT={PORT}")

if __name__ == "__main__":
    # Chạy trực tiếp: python main.py (local dev)
    app.run(host="0.0.0.0", port=PORT, debug=False)
