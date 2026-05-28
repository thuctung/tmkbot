# 🥇 Gold EMA Bot — Theo dõi Vàng FREE, không cần TradingView

Bot tự động lấy giá **vàng (XAUUSD)** mỗi 5 phút, tính **EMA50 / EMA200**,
và gửi cảnh báo về **Telegram** khi có tín hiệu.

> ✅ Hoàn toàn miễn phí — không cần TradingView Pro

---

## 🏗️ Kiến trúc

```
Yahoo Finance (yfinance)
       │  lấy giá mỗi 5 phút
       ▼
  Python Script  ──►  Tính EMA50 / EMA200  ──►  Phát hiện tín hiệu
       │
       ▼
  Telegram Bot  ──►  Thông báo tức thì
```

---

## 📱 Các loại thông báo

| Biểu tượng | Tín hiệu |
|-----------|---------|
| 🔵 | Giá đang chạm vùng EMA50 (±0.1%) |
| 🟠 | Giá đang chạm vùng EMA200 (±0.1%) |
| 🟢 | Giá vượt lên trên EMA50 — tăng ngắn hạn |
| 🔴 | Giá phá xuống EMA50 — giảm ngắn hạn |
| 🚀 | Giá vượt EMA200 — BULLISH mạnh |
| 💀 | Giá phá EMA200 — BEARISH cảnh báo |
| 📊 | Cập nhật trạng thái mỗi 1 giờ |

---

## 🚀 Hướng dẫn deploy (Railway — Miễn phí)

### Bước 1 — Tạo Telegram Bot
1. Tìm **@BotFather** → gõ `/newbot` → lấy **Token**
2. Tìm **@userinfobot** → lấy **Chat ID** (số nguyên)

### Bước 2 — Upload lên GitHub
```bash
git init
git add .
git commit -m "gold ema bot"
git remote add origin https://github.com/USERNAME/gold-ema-bot.git
git push -u origin main
```

### Bước 3 — Deploy lên Railway
1. Vào [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
2. Chọn repo vừa tạo
3. Vào **Settings → Variables**, thêm:

| Biến | Giá trị |
|------|---------|
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID (số nguyên) |
| `CHECK_INTERVAL` | `300` (5 phút) |

4. Railway tự build và chạy — xong!

> 💡 **Lưu ý Railway Free:** 500 giờ/tháng. Nếu cần chạy 24/7 thì dùng gói $5/tháng hoặc deploy lên **Render.com** (free tier không giới hạn giờ cho worker).

---

## 🧪 Test chạy local

```bash
# Cài thư viện
pip install -r requirements.txt

# Tạo .env
cp .env.example .env
# Điền TELEGRAM_TOKEN và TELEGRAM_CHAT_ID vào .env

# Chạy
python main.py
```

---

## ⚙️ Tùy chỉnh

| Biến môi trường | Mặc định | Ý nghĩa |
|----------------|----------|---------|
| `CHECK_INTERVAL` | `300` | Kiểm tra mỗi N giây |
| `TOUCH_THRESHOLD` | `0.001` | Vùng "chạm" ±0.1% |

---

## ⚠️ Lưu ý

- EMA200 cần **200 nến 5 phút = ~16 giờ** để tính lần đầu sau khi khởi động
- EMA50 cần **50 nến = ~4 giờ**
- Bot gửi **status update mỗi 1 giờ** kể cả khi không có tín hiệu
- Nguồn giá: yfinance `GC=F` (Gold Futures NY) — sát với XAUUSD spot
