import os
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# --- Render Web Service 需要一个端口，不然会报 No open ports ---
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

# --- Bot 逻辑 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ Welcome to Crypto Pixie!\n\n"
        "Use /price BTC to check price.\n"
        "Use /price ETH to check ETH.\n"
        "Use /help to see all commands."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - Start bot\n"
        "/price <COIN> - e.g. /price BTC\n"
        "/help - Show help"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price BTC")
        return

    coin = context.args[0].upper()
    # 用 CoinGecko 免费接口
    symbol_map = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "DOGE": "dogecoin",
        "BNB": "binancecoin",
        "XRP": "ripple",
        "ADA": "cardano",
        "USDT": "tether",
    }
    coin_id = symbol_map.get(coin, coin.lower())

    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10).json()
        data = r.get(coin_id)
        if not data:
            await update.message.reply_text(f"Coin {coin} not found, try /price BTC")
            return
        p = data["usd"]
        chg = data.get("usd_24h_change", 0)
        emoji = "🟢" if chg >= 0 else "🔴"
        await update.message.reply_text(
            f"{emoji} {coin} Price: ${p:,.2f}\n24h Change: {chg:.2f}%"
        )
    except Exception as e:
        await update.message.reply_text(f"Error fetching price: {e}")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        raise SystemExit(1)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("price", price))

    print("Bot started...")
    app.run_polling()
