import os
import threading
import requests
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

def _keep_alive():
    port = int(os.environ.get("PORT", 10000))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *a):
            pass
    HTTPServer(("0.0.0.0", port), H).serve_forever()

threading.Thread(target=_keep_alive, daemon=True).start()

def fetch_news(limit=5):
    """Fetch latest crypto news from CoinDesk RSS"""
    try:
        url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            if title and link:
                items.append((title, link))
        return items
    except Exception as e:
        print(f"News fetch error: {e}")
        return []

async def send_daily_news(bot):
    if not CHANNEL_ID:
        print("CHANNEL_ID not set, skip news")
        return
    news = fetch_news(5)
    if not news:
        print("No news fetched")
        return
    text = "📰 **Crypto Daily News**\n\n"
    for i, (title, link) in enumerate(news, 1):
        text += f"{i}. [{title}]({link})\n\n"
    text += "— Crypto Pixie ✨"
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown", disable_web_page_preview=False)
        print("News sent!")
    except Exception as e:
        print(f"Send news failed: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ Welcome to Crypto Pixie!\n\n"
        "/price BTC - Check price\n"
        "/news - Get latest 5 news now\n"
        "/send <msg> - Send to channel\n"
        "/test - Test channel connection"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price BTC")
        return
    coin = context.args[0].upper()
    symbol = f"{coin}USDT"
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        r = requests.get(url, timeout=10).json()
        if "lastPrice" not in r:
            await update.message.reply_text(f"Coin {coin} not found on Binance")
            return
        p = float(r["lastPrice"])
        chg = float(r["priceChangePercent"])
        emoji = "🟢" if chg >= 0 else "🔴"
        await update.message.reply_text(f"{emoji} {coin}: ${p:,.2f}\n24h: {chg:.2f}%")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching latest news...")
    news = fetch_news(5)
    if not news:
        await update.message.reply_text("Failed to fetch news, try again later.")
        return
    text = "📰 **Crypto Daily News**\n\n"
    for i, (title, link) in enumerate(news, 1):
        text += f"{i}. [{title}]({link})\n\n"
    text += "— Crypto Pixie ✨"
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=False)

async def send_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID not set in Render")
        return
    if not context.args:
        await update.message.reply_text("Usage: /send Hello everyone")
        return
    text = " ".join(context.args)
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
        await update.message.reply_text("✅ Sent to channel!")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")

async def test_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID not set")
        return
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ Crypto Pixie connected! Bot is working.")
        await update.message.reply_text("✅ Test sent to channel, check it!")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}\nCheck bot is admin in channel.")

async def post_init(app):
    # Scheduler: US Eastern Time 7AM & 7PM daily
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("America/New_York"))
    scheduler.add_job(send_daily_news, CronTrigger(hour=7, minute=0), args=[app.bot])
    scheduler.add_job(send_daily_news, CronTrigger(hour=19, minute=0), args=[app.bot])
    scheduler.start()
    print("Scheduler started: 7AM & 7PM ET daily news")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        raise SystemExit(1)
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("news", news_cmd))
    app.add_handler(CommandHandler("send", send_to_channel))
    app.add_handler(CommandHandler("test", test_channel))
    print("Bot started...")
    app.run_polling()
