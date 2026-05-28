"""
Gold EMA Bot — Tự động theo dõi giá Vàng (XAUUSD)
Nguồn giá: Forex-Data-Feed qua yfinance (GC=F) hoặc fallback Metals API
Kiểm tra mỗi 5 phút → tính EMA50/EMA200 → gửi Telegram khi có tín hiệu
"""

import os, time, logging
from collections import deque
from datetime import datetime, timezone

import requests

# ── Cấu hình ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", "300"))   # 5 phút = 300 giây
TOUCH_THRESHOLD  = float(os.getenv("TOUCH_THRESHOLD", "0.001"))  # ±0.1%
MAX_BARS         = 250  # Giữ đủ để tính EMA200

EMA_SHORT = 50
EMA_LONG  = 200

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Buffer giá & trạng thái ───────────────────────────────────────────────────
price_buf: deque[float] = deque(maxlen=MAX_BARS)
prev_state: dict = {"close": None, "ema50": None, "ema200": None}

# ══════════════════════════════════════════════════════════════════════════════
# 1. LẤY GIÁ VÀNG
# ══════════════════════════════════════════════════════════════════════════════

def fetch_gold_yfinance() -> float | None:
    """Lấy giá vàng mới nhất từ Yahoo Finance (GC=F = Gold Futures)."""
    try:
        import yfinance as yf
        ticker = yf.Ticker("GC=F")
        df = ticker.history(period="1d", interval="5m")
        if df.empty:
            return None
        price = float(df["Close"].iloc[-1])
        log.info(f"[yfinance] XAUUSD = {price:.2f}")
        return price
    except Exception as e:
        log.warning(f"[yfinance] Lỗi: {e}")
        return None


def fetch_gold_metals_api() -> float | None:
    """
    Fallback: Metals-API free tier
    Đăng ký miễn phí tại https://metals-api.com → lấy API key
    Điền vào biến môi trường METALS_API_KEY
    """
    api_key = os.getenv("METALS_API_KEY", "")
    if not api_key:
        return None
    try:
        url = f"https://metals-api.com/api/latest?access_key={api_key}&base=USD&symbols=XAU"
        r = requests.get(url, timeout=10)
        data = r.json()
        # Trả về USD/troy oz
        xau_per_usd = data["rates"]["XAU"]
        price = round(1 / xau_per_usd, 2)  # Convert: giá 1 oz vàng tính bằng USD
        log.info(f"[metals-api] XAUUSD = {price:.2f}")
        return price
    except Exception as e:
        log.warning(f"[metals-api] Lỗi: {e}")
        return None


def fetch_gold_frankfurter() -> float | None:
    """
    Fallback 2: frankfurter.app (hoàn toàn free, không cần key)
    Chỉ có giá cuối ngày — dùng khi không có nguồn nào khác.
    """
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=XAU&to=USD", timeout=10)
        data = r.json()
        price = round(data["rates"]["USD"], 2)
        log.info(f"[frankfurter] XAUUSD = {price:.2f}")
        return price
    except Exception as e:
        log.warning(f"[frankfurter] Lỗi: {e}")
        return None


def get_gold_price() -> float | None:
    """Thử các nguồn theo thứ tự ưu tiên."""
    return (
        fetch_gold_yfinance()
        or fetch_gold_metals_api()
        or fetch_gold_frankfurter()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. TÍNH EMA
# ══════════════════════════════════════════════════════════════════════════════

def calc_ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 3)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PHÁT HIỆN TÍN HIỆU
# ══════════════════════════════════════════════════════════════════════════════

def detect_signals(close: float, ema50: float | None, ema200: float | None) -> list[str]:
    global prev_state
    signals = []

    prev_close = prev_state["close"]
    prev_e50   = prev_state["ema50"]
    prev_e200  = prev_state["ema200"]

    def near(price, ema):
        return abs(price - ema) / ema <= TOUCH_THRESHOLD

    def cross_above(now, ema_now, before, ema_before):
        return (before is not None and ema_before is not None
                and before <= ema_before and now > ema_now)

    def cross_below(now, ema_now, before, ema_before):
        return (before is not None and ema_before is not None
                and before >= ema_before and now < ema_now)

    # ── EMA50 ──────────────────────────────────────────────────────────────
    if ema50:
        if cross_above(close, ema50, prev_close, prev_e50):
            signals.append(
                f"🟢 <b>VÀNG (XAUUSD)</b> — Giá vượt lên EMA50 📈\n"
                f"Giá: <b>${close:,.2f}</b>  |  EMA50: <b>${ema50:,.2f}</b>\n"
                f"⚡ Tín hiệu: <i>Breakout ngắn hạn TĂNG</i>"
            )
        elif cross_below(close, ema50, prev_close, prev_e50):
            signals.append(
                f"🔴 <b>VÀNG (XAUUSD)</b> — Giá phá xuống EMA50 📉\n"
                f"Giá: <b>${close:,.2f}</b>  |  EMA50: <b>${ema50:,.2f}</b>\n"
                f"⚡ Tín hiệu: <i>Breakdown ngắn hạn GIẢM</i>"
            )
        elif near(close, ema50):
            signals.append(
                f"🔵 <b>VÀNG (XAUUSD)</b> — Giá đang chạm EMA50\n"
                f"Giá: <b>${close:,.2f}</b>  |  EMA50: <b>${ema50:,.2f}</b>\n"
                f"👀 <i>Quan sát vùng hỗ trợ / kháng cự</i>"
            )

    # ── EMA200 ─────────────────────────────────────────────────────────────
    if ema200:
        if cross_above(close, ema200, prev_close, prev_e200):
            signals.append(
                f"🚀 <b>VÀNG (XAUUSD)</b> — Giá vượt EMA200 — BULLISH MẠNH! 📈\n"
                f"Giá: <b>${close:,.2f}</b>  |  EMA200: <b>${ema200:,.2f}</b>\n"
                f"🔥 Tín hiệu: <i>Xu hướng tăng dài hạn xác nhận</i>"
            )
        elif cross_below(close, ema200, prev_close, prev_e200):
            signals.append(
                f"💀 <b>VÀNG (XAUUSD)</b> — Giá phá xuống EMA200 — BEARISH! 📉\n"
                f"Giá: <b>${close:,.2f}</b>  |  EMA200: <b>${ema200:,.2f}</b>\n"
                f"⚠️ Tín hiệu: <i>Cảnh báo đảo chiều xu hướng</i>"
            )
        elif near(close, ema200):
            signals.append(
                f"🟠 <b>VÀNG (XAUUSD)</b> — Giá đang chạm EMA200\n"
                f"Giá: <b>${close:,.2f}</b>  |  EMA200: <b>${ema200:,.2f}</b>\n"
                f"👀 <i>Vùng quan trọng — theo dõi sát</i>"
            )

    # Lưu trạng thái
    prev_state = {"close": close, "ema50": ema50, "ema200": ema200}
    return signals


# ══════════════════════════════════════════════════════════════════════════════
# 4. GỬI TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Chưa cấu hình Telegram — bỏ qua.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Telegram lỗi: {e}")
        return False


def send_status_update(close: float, ema50, ema200, bars: int):
    """Gửi bản tin cập nhật định kỳ mỗi giờ."""
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    e50_str  = f"${ema50:,.2f}"  if ema50  else "Chưa đủ dữ liệu"
    e200_str = f"${ema200:,.2f}" if ema200 else f"Cần thêm {EMA_LONG - bars} nến"

    trend = "—"
    if ema50 and ema200:
        if close > ema50 > ema200:
            trend = "📈 TĂNG mạnh (Giá > EMA50 > EMA200)"
        elif close < ema50 < ema200:
            trend = "📉 GIẢM mạnh (Giá < EMA50 < EMA200)"
        elif ema50 > ema200:
            trend = "🟡 Trung lập — EMA50 trên EMA200"
        else:
            trend = "🟡 Trung lập — EMA50 dưới EMA200"

    msg = (
        f"📊 <b>CẬP NHẬT GIÁ VÀNG</b> — {now}\n"
        f"{'─'*28}\n"
        f"💰 Giá hiện tại: <b>${close:,.2f}</b>\n"
        f"📉 EMA50:  <b>{e50_str}</b>\n"
        f"📉 EMA200: <b>{e200_str}</b>\n"
        f"📌 Xu hướng: {trend}\n"
        f"📦 Dữ liệu: {bars} nến 5 phút"
    )
    send_telegram(msg)


# ══════════════════════════════════════════════════════════════════════════════
# 5. VÒNG LẶP CHÍNH
# ══════════════════════════════════════════════════════════════════════════════

def run():
    log.info("🚀 Gold EMA Bot khởi động...")
    send_telegram("🤖 <b>Gold EMA Bot đã khởi động!</b>\nTheo dõi XAUUSD mỗi 5 phút\nEMA50 & EMA200 | Tín hiệu chạm và vượt")

    hourly_counter = 0  # Gửi status mỗi 12 lần (= 1 giờ)

    while True:
        try:
            close = get_gold_price()

            if close is None:
                log.warning("Không lấy được giá — thử lại sau.")
                time.sleep(60)
                continue

            price_buf.append(close)
            prices = list(price_buf)
            bars   = len(prices)

            ema50  = calc_ema(prices, EMA_SHORT) if bars >= EMA_SHORT else None
            ema200 = calc_ema(prices, EMA_LONG)  if bars >= EMA_LONG  else None

            log.info(
                f"Giá=${close:,.2f} | EMA50={ema50 or 'N/A'} | "
                f"EMA200={ema200 or 'N/A'} | Bars={bars}/{MAX_BARS}"
            )

            # Phát hiện và gửi tín hiệu
            signals = detect_signals(close, ema50, ema200)
            now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
            for sig in signals:
                send_telegram(f"{sig}\n🕐 {now_str}")
                log.info(f"📨 Đã gửi tín hiệu Telegram")

            # Gửi status mỗi 1 giờ
            hourly_counter += 1
            if hourly_counter >= 12:
                send_status_update(close, ema50, ema200, bars)
                hourly_counter = 0

            # Cảnh báo nếu chưa đủ dữ liệu (chỉ log, không spam Telegram)
            if bars < EMA_LONG:
                log.info(f"⏳ Đang thu thập dữ liệu: {bars}/{EMA_LONG} nến để tính EMA200")

        except Exception as e:
            log.error(f"Lỗi vòng lặp: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
