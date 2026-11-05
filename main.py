import os, requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I'm Crypto Pixie ✨\nSend me BTC / ETH / SOL to get analysis.\nSend /report for latest digest.")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Latest Digest\nBTC: Watching $90k support.\nETH: Watching $3,200.\nThis is a demo signal, full version coming soon.")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.upper().strip()
    if text in ["BTC","ETH","SOL","TON","DOGE"]:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={text}USDT", timeout=5).json()
            price = float(r['price'])
            await update.message.reply_text(f"💰 {text}/USDT: ${price:,.2f}\nTrend: Watching key level. Stay tuned for full signal.")
        except:
            await update.message.reply_text(f"Can't fetch {text} price now, try again.")
    else:
        await update.message.reply_text("Send me BTC / ETH / SOL / TON / DOGE")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("report", report))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
app.run_polling()
