# 📊 TradingView → EMA Signal → Telegram Bot

Nhận dữ liệu giá từ TradingView qua Webhook, tính **EMA50 / EMA200**, và gửi cảnh báo về **Telegram** khi giá chạm hoặc vượt qua các đường EMA.

---

## 🏗️ Kiến trúc

```
TradingView Alert  ──►  Webhook Server (Railway)  ──►  Telegram Bot
     (JSON)               Flask + EMA Logic              Thông báo
```

---

## 🚀 Hướng dẫn deploy lên Railway (Miễn phí)

### Bước 1 – Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gõ `/newbot` → đặt tên → nhận **Token**
3. Tìm **@userinfobot** → gửi tin nhắn bất kỳ → nhận **Chat ID** (số âm nếu là group)

### Bước 2 – Upload code lên GitHub

```bash
git init
git add .
git commit -m "first commit"
git remote add origin https://github.com/YOUR_USERNAME/tradingview-bot.git
git push -u origin main
```

### Bước 3 – Deploy lên Railway

1. Vào [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Chọn repo vừa tạo
3. Vào tab **Variables**, thêm:

| Key | Value |
|-----|-------|
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID của bạn |
| `WEBHOOK_SECRET` | Mật khẩu tự đặt (vd: `abc123xyz`) |

4. Railway tự động deploy → copy **Public Domain** (vd: `https://my-bot.up.railway.app`)

### Bước 4 – Cấu hình TradingView Alert

1. Mở TradingView → chọn cặp tiền + khung thời gian
2. Tạo Alert → tab **Notifications** → bật **Webhook URL**
3. Nhập URL: `https://YOUR_APP.up.railway.app/webhook`
4. Tab **Alert message** → nhập JSON:

```json
{
  "secret": "abc123xyz",
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "close": {{close}}
}
```

> **Quan trọng:** `{{ticker}}`, `{{interval}}`, `{{close}}` là biến TradingView tự điền.

5. Chọn tần suất: **Once Per Bar Close** (khuyến nghị)
6. Nhấn **Create**

---

## 📱 Các loại thông báo Telegram

| Tín hiệu | Ý nghĩa |
|----------|---------|
| 🔵 Giá chạm EMA50 | Giá trong vùng ±0.1% quanh EMA50 |
| 🟠 Giá chạm EMA200 | Giá trong vùng ±0.1% quanh EMA200 |
| 🟢 Giá vượt lên EMA50 | Breakout bullish ngắn hạn |
| 🔴 Giá phá xuống EMA50 | Breakdown bearish ngắn hạn |
| 🚀 Giá vượt lên EMA200 | Tín hiệu BULLISH mạnh |
| 💀 Giá phá xuống EMA200 | Tín hiệu BEARISH mạnh |

---

## 🧪 Test thủ công

```bash
# Cài đặt
pip install -r requirements.txt

# Tạo file .env từ .env.example và điền thông tin
cp .env.example .env

# Chạy local
python main.py

# Gửi test webhook (terminal khác)
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"my_secret_key","symbol":"BTCUSDT","timeframe":"1h","close":67500}'

# Kiểm tra status
curl http://localhost:5000/status
```

---

## ⚙️ Giải thích code

- **`price_store`**: Lưu tối đa 210 nến gần nhất cho mỗi symbol/timeframe (đủ để tính EMA200)
- **`calc_ema()`**: Tính EMA chuẩn với hệ số k = 2/(period+1)
- **`detect_signals()`**: So sánh giá hiện tại với EMA, phát hiện cross và touch
- **`send_telegram()`**: Gửi message HTML về Telegram Bot API

---

## 📝 Lưu ý quan trọng

- Server cần **tích lũy đủ 50 nến** trước khi tính EMA50, **200 nến** cho EMA200
- Nếu restart server, dữ liệu nến sẽ mất → cần gửi lại đủ lịch sử
- Để lưu trữ lâu dài, có thể nâng cấp dùng **SQLite** hoặc **Redis**
- Railway free tier: 500 giờ/tháng, đủ cho 1 bot chạy liên tục

---

## 🔧 Nâng cấp tùy chọn

- Thêm **nhiều symbol** cùng lúc: chỉ cần tạo nhiều Alert trên TradingView
- Thêm **Stop Loss / Take Profit** tính theo ATR
- Lưu lịch sử tín hiệu vào **SQLite**
- Gửi **chart screenshot** qua Telegram (dùng TradingView screenshot API)
