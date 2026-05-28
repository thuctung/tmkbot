"""
Gold Realtime EMA Bot
─────────────────────
Nguồn giá : Twelve Data API (free — realtime XAUUSD)
Tần suất  : mỗi 5 phút
Tín hiệu  : Giá chạm / vượt EMA50 & EMA200
Thông báo : Telegram Bot
"""

import os, time, logging
from collections import deque
from datetime import datetime, timezone

import requests

# ── Cấu hình ──────────────────────────────────────────────────────────────────
TWELVE_API_KEY   = os.getenv("TWELVE_API_KEY", "")      # từ twelvedata.com
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOL           = "XAU/USD"
INTERVAL         = "5min"
CHECK_EVERY_SEC  = int(os.getenv("CHECK_INTERVAL", "300"))   # 5 phút
TOUCH_PCT        = float(os.getenv("TOUCH_THRESHOLD", "0.1")) # 0.1 %
MAX_BARS         = 250
EMA_SHORT, EMA_LONG = 50, 200

# Lấy sẵn 200 nến lịch sử khi khởi động (không cần chờ 16 giờ)
PRELOAD_BARS     = 210

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Buffer & trạng thái ───────────────────────────────────────────────────────
price_buf: deque[float] = deque(maxlen=MAX_BARS)
prev: dict = {"close": None, "ema50": None, "ema200": None}

# ══════════════════════════════════════════════════════════════════════════════
# TWELVE DATA — LẤY GIÁ
# ══════════════════════════════════════════════════════════════════════════════

BASE = "https://api.twelvedata.com"

def _headers():
    return {"Authorization": f"apikey {TWELVE_API_KEY}"}


def fetch_latest_price() -> float | None:
    """
    Lấy giá realtime XAUUSD (endpoint /price — chỉ tốn 1 credit).
    Trả về giá float hoặc None nếu lỗi.
    """
    try:
        r = requests.get(
            f"{BASE}/price",
            params={"symbol": SYMBOL, "apikey": TWELVE_API_KEY},
            timeout=10,
        )
        data = r.json()
        if data.get("status") == "error":
            log.warning(f"Twelve Data lỗi: {data.get('message')}")
            return None
        price = float(data["price"])
        log.info(f"[TwelveData] {SYMBOL} = {price:.3f}")
        return price
    except Exception as e:
        log.error(f"fetch_latest_price: {e}")
        return None


def preload_history() -> list[float]:
    """
    Lấy PRELOAD_BARS nến 5 phút gần nhất khi khởi động.
    Dùng endpoint /time_series — tốn 1 credit nhưng trả về nhiều nến.
    Giúp tính ngay EMA200 mà không cần chờ 16 giờ.
    """
    try:
        log.info(f"⏳ Đang tải {PRELOAD_BARS} nến lịch sử XAUUSD 5m...")
        r = requests.get(
            f"{BASE}/time_series",
            params={
                "symbol":    SYMBOL,
                "interval":  INTERVAL,
                "outputsize": PRELOAD_BARS,
                "apikey":    TWELVE_API_KEY,
            },
            timeout=15,
        )
        data = r.json()
        if data.get("status") == "error":
            log.warning(f"preload lỗi: {data.get('message')}")
            return []

        # Dữ liệu trả về mới nhất trước — đảo ngược thành cũ → mới
        candles = data.get("values", [])
        closes  = [float(c["close"]) for c in reversed(candles)]
        log.info(f"✅ Tải xong {len(closes)} nến lịch sử")
        return closes
    except Exception as e:
        log.error(f"preload_history: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# TÍNH EMA
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

def detect(close: float, ema50: float | None, ema200: float | None) -> list[str]:
    global prev
    msgs = []

    pc, pe50, pe200 = prev["close"], prev["ema50"], prev["ema200"]
    thr = TOUCH_PCT / 100

    def near(p, e):      return abs(p - e) / e <= thr
    def x_up(p, e, pp, pe):   return pp is not None and pe is not None and pp <= pe < p
    def x_dn(p, e, pp, pe):   return pp is not None and pe is not None and pp >= pe > p

    # ── EMA 50 ────────────────────────────────────────────────
    if ema50:
        if x_up(close, ema50, pc, pe50):
            msgs.append(
                f"🟢 <b>VÀNG (XAUUSD)</b> — Giá vượt lên EMA50 📈\n"
                f"Giá: <b>${close:,.3f}</b>  |  EMA50: <b>${ema50:,.3f}</b>\n"
                f"⚡ <i>Tín hiệu tăng ngắn hạn</i>"
            )
        elif x_dn(close, ema50, pc, pe50):
            msgs.append(
                f"🔴 <b>VÀNG (XAUUSD)</b> — Giá phá xuống EMA50 📉\n"
                f"Giá: <b>${close:,.3f}</b>  |  EMA50: <b>${ema50:,.3f}</b>\n"
                f"⚡ <i>Tín hiệu giảm ngắn hạn</i>"
            )
        elif near(close, ema50):
            msgs.append(
                f"🔵 <b>VÀNG (XAUUSD)</b> — Giá chạm vùng EMA50\n"
                f"Giá: <b>${close:,.3f}</b>  |  EMA50: <b>${ema50:,.3f}</b>\n"
                f"👀 <i>Theo dõi vùng hỗ trợ / kháng cự</i>"
            )

    # ── EMA 200 ───────────────────────────────────────────────
    if ema200:
        if x_up(close, ema200, pc, pe200):
            msgs.append(
                f"🚀 <b>VÀNG (XAUUSD)</b> — Vượt EMA200 — BULLISH MẠNH! 🔥\n"
                f"Giá: <b>${close:,.3f}</b>  |  EMA200: <b>${ema200:,.3f}</b>\n"
                f"📈 <i>Xu hướng tăng dài hạn xác nhận</i>"
            )
        elif x_dn(close, ema200, pc, pe200):
            msgs.append(
                f"💀 <b>VÀNG (XAUUSD)</b> — Phá EMA200 — BEARISH! ⚠️\n"
                f"Giá: <b>${close:,.3f}</b>  |  EMA200: <b>${ema200:,.3f}</b>\n"
                f"📉 <i>Cảnh báo đảo chiều xu hướng</i>"
            )
        elif near(close, ema200):
            msgs.append(
                f"🟠 <b>VÀNG (XAUUSD)</b> — Giá chạm vùng EMA200\n"
                f"Giá: <b>${close:,.3f}</b>  |  EMA200: <b>${ema200:,.3f}</b>\n"
                f"👀 <i>Vùng EMA200 — rất quan trọng!</i>"
            )

    prev = {"close": close, "ema50": ema50, "ema200": ema200}
    return msgs


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def tg(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram chưa cấu hình.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        log.error(f"Telegram: {e}")


def status_msg(close: float, ema50, ema200, bars: int) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    def fmt(v): return f"${v:,.3f}" if v else "⏳ chưa đủ dữ liệu"

    trend = "—"
    if ema50 and ema200:
        if close > ema50 > ema200:   trend = "📈 Tăng mạnh  (Giá > EMA50 > EMA200)"
        elif close < ema50 < ema200: trend = "📉 Giảm mạnh  (Giá < EMA50 < EMA200)"
        elif ema50 > ema200:         trend = "🟡 EMA50 trên EMA200 — chú ý breakout"
        else:                        trend = "🟡 EMA50 dưới EMA200 — thận trọng"

    need200 = f"  (cần thêm {max(0, EMA_LONG - bars)} nến)" if bars < EMA_LONG else ""

    return (
        f"📊 <b>VÀNG (XAUUSD)</b> — {now}\n"
        f"{'─'*30}\n"
        f"💰 Giá:   <b>${close:,.3f}</b>\n"
        f"📉 EMA50:  <b>{fmt(ema50)}</b>\n"
        f"📉 EMA200: <b>{fmt(ema200)}</b>{need200}\n"
        f"📌 Xu hướng: {trend}\n"
        f"📦 Nến đã thu: {bars}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# VÒNG LẶP CHÍNH
# ══════════════════════════════════════════════════════════════════════════════

def run():
    if not TWELVE_API_KEY:
        log.error("❌ Thiếu TWELVE_API_KEY — bot dừng lại.")
        return

    log.info("🚀 Gold Realtime EMA Bot khởi động...")

    # ── Tải lịch sử ngay khi khởi động ──
    history = preload_history()
    if history:
        price_buf.extend(history)
        log.info(f"Buffer sẵn sàng: {len(price_buf)} nến")

    tg(
        "🤖 <b>Gold EMA Bot đã online!</b>\n"
        f"📡 Nguồn: Twelve Data (realtime XAUUSD)\n"
        f"⏱ Kiểm tra mỗi 5 phút\n"
        f"📦 Dữ liệu khởi động: {len(price_buf)} nến"
    )

    hourly_tick = 0  # gửi status mỗi 12 lần = 1 giờ

    while True:
        try:
            close = fetch_latest_price()

            if close is None:
                log.warning("Không lấy được giá, thử lại sau 60 giây...")
                time.sleep(60)
                continue

            price_buf.append(close)
            prices = list(price_buf)
            bars   = len(prices)

            ema50  = calc_ema(prices, EMA_SHORT) if bars >= EMA_SHORT else None
            ema200 = calc_ema(prices, EMA_LONG)  if bars >= EMA_LONG  else None

            log.info(
                f"Close={close:.3f}  EMA50={ema50 or 'N/A'}  "
                f"EMA200={ema200 or 'N/A'}  Bars={bars}"
            )

            # Tín hiệu
            signals = detect(close, ema50, ema200)
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
            for sig in signals:
                tg(f"{sig}\n🕐 {ts}")
                log.info("📨 Tín hiệu gửi Telegram")

            # Status mỗi 1 giờ
            hourly_tick += 1
            if hourly_tick >= 12:
                tg(status_msg(close, ema50, ema200, bars))
                hourly_tick = 0

        except Exception as e:
            log.error(f"Lỗi vòng lặp: {e}", exc_info=True)

        time.sleep(CHECK_EVERY_SEC)


if __name__ == "__main__":
    run()
