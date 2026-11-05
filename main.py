import os
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ Welcome to Crypto Pixie!\n\n"
        "/price BTC - Check price\n"
        "/send <消息> - Send to channel\n"
        "/test - Test channel connection"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price BTC")
        return
    coin = context.args[0].upper()
    symbol_map = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "DOGE": "dogecoin", "BNB": "binancecoin", "XRP": "ripple"}
    coin_id = symbol_map.get(coin, coin.lower())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10).json()
        data = r.get(coin_id)
        if not data:
            await update.message.reply_text(f"Coin {coin} not found")
            return
        p = data["usd"]
        chg = data.get("usd_24h_change", 0)
        emoji = "🟢" if chg >= 0 else "🔴"
        await update.message.reply_text(f"{emoji} {coin}: ${p:,.2f}\n24h: {chg:.2f}%")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

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

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        raise SystemExit(1)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("send", send_to_channel))
    app.add_handler(CommandHandler("test", test_channel))
    print("Bot started...")
    app.run_polling()
