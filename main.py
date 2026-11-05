import os
import re
import json
import feedparser
import requests
import threading
from datetime import datetime, time as dtime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ===== Render 保活 =====
def keep_alive():
    port = int(os.getenv("PORT", "10000"))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK - Bot is running")
        def log_message(self, *a):
            pass
    try:
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception as e:
        print(f"Web server failed: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

# ===== 配置 =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1004218958873"))
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "-1004490905842"))
CHAT_INVITE_LINK = os.getenv("CHAT_INVITE_LINK", "https://t.me/+n3HjK18XQmk0NDhl")

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]

SENT_FILE = "sent_news.json"

# ===== 底部按钮 - 2个 =====
def get_join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Join Discussion Group", url=CHAT_INVITE_LINK)],
        [InlineKeyboardButton("📊 Check BTC Price in Group", url=CHAT_INVITE_LINK)]
    ])

# ===== 防重复 + 24h =====
def load_sent():
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()

def save_sent(title):
    sent = load_sent()
    sent.add(title)
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent)[-200:], f, ensure_ascii=False)
    except Exception as e:
        print(f"Save sent failed: {e}")

def is_fresh(published_str):
    if not published_str:
        return True
    try:
        pub = parsedate_to_datetime(published_str)
        diff = (datetime.now(pub.tzinfo) - pub).total_seconds() / 3600
        return diff <= 24
    except:
        return True

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
    # 防止标题里的 < > 破坏 HTML 解析
    text = text.replace("<", "").replace(">", "")
    return text.strip()[:280]

def fetch_us_news(limit=10):
    all_news = []
    sent = load_sent()
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = entry.title.strip().replace("<", "").replace(">", "")
                published = getattr(entry, 'published', '')
                if not is_fresh(published):
                    continue
                if title in sent:
                    continue
                all_news.append({
                    "title": title,
                    "summary": clean_html(getattr(entry, 'summary', '') or getattr(entry, 'description', '')),
                    "link": entry.link,
                    "source": source,
                    "published": published
                })
        except Exception as e:
            print(f"Feed failed {source}: {e}")
    seen = set()
    uniq = []
    for n in all_news:
        if n['title'] not in seen:
            seen.add(n['title'])
            uniq.append(n)
    return uniq[:limit]

def get_market_mood():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        v = r['data'][0]['value']
        c = r['data'][0]['value_classification']
        return f"{c} ({v}/100) - Fear & Greed Index"
    except:
        return "Neutral - Market waiting for US macro data"

def get_btc_price_line():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=5).json()
        price = float(r['lastPrice'])
        change = float(r['priceChangePercent'])
        emoji = "🟢" if change >= 0 else "🔴"
        return f"{emoji} BTC ${price:,.0f} ({change:+.2f}% 24h)"
    except:
        return "BTC price unavailable"

# ===== 模版 V42 - 新版面 =====
def format_breaking(news):
    return (
        f"🚨 <b>BREAKING</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{news['title']}</b>\n\n"
        f"{news['summary']}\n\n"
        f"Source: {news['source']}\n"
        f"Read more: {news['link']}"
    )

def format_digest(news_list, date_str):
    if not news_list:
        return "No news today"

    top = news_list[0]

    text = f"<b>🇺🇸 US CRYPTO DIGEST | {date_str}</b>\n"
    text += f"Your daily 5-min US crypto briefing\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    # TOP STORY
    text += f"🔥 <b>TOP STORY</b>\n"
    text += f"<b>{top['title']}</b>\n"
    text += f"{top['summary']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    # TOP 5
    text += f"📰 <b>TODAY'S TOP 5</b>\n\n"
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]
    for i, n in enumerate(news_list[:5]):
        text += f"{emojis[i]} <b>{n['title']}</b>\n{n['summary']}\n\n"

    # MARKET
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"📊 <b>MARKET SNAPSHOT</b>\n"
    text += f"{get_btc_price_line()}\n"
    text += f"🧭 {get_market_mood()}\n"
    text += f"💬 Send <code>BTC</code> / <code>ETH</code> / <code>SOL</code> in group for live price"

    return text

# ===== 发送函数 =====
async def send_breaking(context: ContextTypes.DEFAULT_TYPE, news=None):
    if not news:
        news_list = fetch_us_news(1)
        if not news_list:
            print("Breaking: 没有新新闻，跳过")
            return
        news = news_list[0]
    text = format_breaking(news)
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", reply_markup=get_join_keyboard(), disable_web_page_preview=True)
        save_sent(news['title'])
        print(f"Breaking sent: {news['title']}")
    except Exception as e:
        print(f"Breaking FAILED: {e}")

async def send_digest(context: ContextTypes.DEFAULT_TYPE):
    news_list = fetch_us_news(8)
    if not news_list:
        print("Digest: 24h 内没有新新闻，跳过")
        return
    date_str = datetime.now().strftime("%b %d")
    text = format_digest(news_list, date_str)
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", reply_markup=get_join_keyboard(), disable_web_page_preview=True)
        for n in news_list[:5]:
            save_sent(n['title'])
        print(f"Digest sent: {len(news_list)} news")
    except Exception as e:
        print(f"Digest FAILED: {e}")

# ===== 命令 =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇺🇸 US Crypto News Bot\n\n"
        "频道: Breaking + Daily Digest\n"
        "群: 价格分析 + 讨论\n\n"
        "命令:\n"
        "/digest - 立刻发一条 Digest 到频道\n"
        "/breaking - 立刻发一条 Breaking 到频道\n"
        "/news - 看最新 1 条新闻\n"
        "/report - 手动发 Digest\n"
        "在群里发 BTC / ETH / SOL 直接分析"
    )

async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("正在检查 24h 内新新闻...")
    before = len(load_sent())
    await send_digest(context)
    after = len(load_sent())
    if after > before:
        await update.message.reply_text("✅ Digest 已发到频道")
    else:
        await update.message.reply_text("24h 内没有新新闻，已跳过，没重复发")

async def cmd_breaking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("正在检查新 Breaking...")
    before = len(load_sent())
    await send_breaking(context)
    after = len(load_sent())
    if after > before:
        await update.message.reply_text("✅ Breaking 已发到频道")
    else:
        await update.message.reply_text("没有新 Breaking，已跳过，没重复发")

async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news_list = fetch_us_news(1)
    if not news_list:
        await update.message.reply_text("24h 内没有新新闻")
        return
    await update.message.reply_text(format_breaking(news_list[0]), parse_mode="HTML", reply_markup=get_join_keyboard())

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_digest(update, context)

async def handle_group_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip().upper()
    if text in ["BTC", "ETH", "SOL", "DOGE", "XRP"]:
        try:
            coin = text.lower()
            r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={coin}USDT", timeout=5).json()
            price = float(r['lastPrice'])
            change = float(r['priceChangePercent'])
            emoji = "🟢" if change >= 0 else "🔴"
            await update.message.reply_text(
                f"{emoji} {text}/USDT: ${price:,.2f} ({change:+.2f}% 24h)\n\n"
                f"24h High: ${float(r['highPrice']):,.2f}\n"
                f"24h Low: ${float(r['lowPrice']):,.2f}\n"
                f"Volume: ${float(r['quoteVolume'])/1e6:.1f}M"
            )
        except Exception as e:
            await update.message.reply_text(f"暂时查不到 {text} 价格")
            print(e)

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("breaking", cmd_breaking))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_msg))
    if app.job_queue:
        app.job_queue.run_daily(send_digest, time=dtime(hour=14, minute=0), name="daily_digest")
    print("Scheduler v42 US News + New Layout - Final Channel")
    print(f"CHANNEL_ID={CHANNEL_ID} REPORT_CHAT_ID={REPORT_CHAT_ID}")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
