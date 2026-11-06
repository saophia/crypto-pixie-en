import os
import re
import json
import hashlib
import asyncio
import feedparser
import requests
import threading
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ChatMemberHandler
from telegram.ext import ChatMemberHandler as CMH

# ===== Render 保活 - V54 FIX: 加 do_HEAD, 解决 UptimeRobot 501 =====
def keep_alive():
    port = int(os.getenv("PORT", "10000"))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK - Bot is running")
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()
        def log_message(self, *a):
            pass
    try:
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception as e:
        print(f"Web server failed: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

# ===== 配置 =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "crypto_pixie_bot")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1004218958873"))
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "-1004490905842"))
CHAT_INVITE_LINK = os.getenv("CHAT_INVITE_LINK", "https://t.me/+n3HjK18XQmk0NDhl")

EASTERN = ZoneInfo("America/New_York")

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]

COINS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "DOGE": "dogecoin", "XRP": "ripple"}

COIN_KEYWORDS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth"],
    "SOL": ["solana", "sol"],
    "DOGE": ["dogecoin", "doge"],
    "XRP": ["xrp", "ripple"],
}

# ===== V51: 去重 - Upstash Redis =====
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
_SENT_CACHE = set()

def _title_hash(title: str) -> str:
    return hashlib.md5(title.strip().lower().encode()).hexdigest()

def _upstash_get(key: str):
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    try:
        r = requests.get(
            f"{UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
        return r.json().get("result")
    except:
        return None

def _upstash_set(key: str, value: str):
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return
    try:
        requests.get(
            f"{UPSTASH_URL}/set/{key}/{value}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
    except Exception as e:
        print(f"Upstash set failed: {e}")

def load_sent():
    global _SENT_CACHE
    if _SENT_CACHE:
        return _SENT_CACHE
    raw = _upstash_get("sent_news_hashes")
    if raw:
        try:
            _SENT_CACHE = set(json.loads(raw))
        except:
            _SENT_CACHE = set()
    return _SENT_CACHE

def save_sent(title):
    h = _title_hash(title)
    sent = load_sent()
    if h in sent:
        return
    sent.add(h)
    if len(sent) > 500:
        sent = set(list(sent)[-500:])
    _SENT_CACHE = sent
    try:
        _upstash_set("sent_news_hashes", json.dumps(list(sent)))
    except Exception as e:
        print(f"Save sent failed: {e}")

# ===== 欢迎文案 =====
WHALE_WELCOME_TEXT = (
    "<b>🐋 WHALE CHATROOM</b>\n"
    "<i>Where Smart Money Moves First</i>\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "We do only 3 things daily:\n\n"
    "<b>1. 💎 3-5 Precision Signals</b>\n"
    "Entry • Stop-Loss • Take-Profit, ready to follow\n\n"
    "<b>2. 🔥 Whale Moves Tracking</b>\n"
    "What whales are buying / selling, in real time\n\n"
    "<b>3. 📊 Elliott Wave + Review</b>\n"
    "Not just what moves, but why it moves\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "<b>No noise. No hype. Just real edge.</b>"
)

def get_whale_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Join Whale Chatroom", url="https://t.me/+n3HjKI8XQmk0NDhl")],
        [InlineKeyboardButton("🔍 View More Crypto Details", url=get_bot_link())],
    ])

def get_bot_link():
    username = BOT_USERNAME.strip() if BOT_USERNAME else "crypto_pixie_bot"
    return f"https://t.me/{username}?start=from_channel"

def get_join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Join Discussion Group", url=CHAT_INVITE_LINK)],
        [InlineKeyboardButton("🔍 View More Crypto Details", url=get_bot_link())],
    ])

# ===== V55.4: Start 下面只留鲸鱼按钮 =====
def get_start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐋 Join Whale Chatroom", url="https://t.me/+n3HjKI8XQmk0NDhl")],
    ])

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
    text = text.replace("<", "").replace(">", "")
    return text.strip()[:280]

# ===== V55.3 NEW: 从 RSS 里取新闻配图 =====
def get_entry_image(entry):
    try:
        media = getattr(entry, 'media_content', None)
        if media and len(media) > 0:
            url = media[0].get('url', '')
            if url.startswith('http'):
                return url
    except:
        pass
    try:
        thumb = getattr(entry, 'media_thumbnail', None)
        if thumb and len(thumb) > 0:
            url = thumb[0].get('url', '')
            if url.startswith('http'):
                return url
    except:
        pass
    try:
        enc = getattr(entry, 'enclosures', None)
        if enc and len(enc) > 0:
            url = enc[0].get('href', '') or enc[0].get('url', '')
            if url.startswith('http') and any(x in url.lower() for x in ['.jpg', '.jpeg', '.png', '.webp']):
                return url
    except:
        pass
    try:
        for l in getattr(entry, 'links', []):
            if l.get('type', '').startswith('image/'):
                return l.get('href', '')
    except:
        pass
    return ""

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
                if _title_hash(title) in sent:
                    continue
                all_news.append({
                    "title": title,
                    "summary": clean_html(getattr(entry, 'summary', '') or getattr(entry, 'description', '')),
                    "link": entry.link,
                    "source": source,
                    "published": published,
                    "image": get_entry_image(entry)
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

def fetch_all_news_for_coin(limit=20):
    all_news = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.title.strip().replace("<", "").replace(">", "")
                published = getattr(entry, 'published', '')
                if not is_fresh(published):
                    continue
                all_news.append({
                    "title": title,
                    "summary": clean_html(getattr(entry, 'summary', '') or getattr(entry, 'description', '')),
                    "link": entry.link,
                    "source": source,
                    "published": published,
                    "image": get_entry_image(entry)
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

def get_fear_greed_value():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        v = int(r['data'][0]['value'])
        c = r['data'][0]['value_classification']
        if v <= 25:
            tip = "Extreme fear - historically a accumulation window"
        elif v <= 45:
            tip = "Fear - avoid chasing highs"
        elif v <= 55:
            tip = "Neutral - waiting for direction"
        elif v <= 75:
            tip = "Greed - watch for overheating"
        else:
            tip = "Extreme greed - watch for pullback risk"
        return v, c, tip
    except:
        return 50, "Neutral", "Market waiting for US macro data"

def get_btc_price_line():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true",
            timeout=6
        ).json()
        price = r['bitcoin']['usd']
        change = r['bitcoin']['usd_24h_change']
        emoji = "🟢" if change >= 0 else "🔴"
        return f"{emoji} BTC ${price:,.0f} ({change:+.2f}% 24h)"
    except Exception as e:
        print(f"CoinGecko BTC failed: {e}")
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=6).json()
        price = float(r['data']['amount'])
        return f"🟢 BTC ${price:,.0f} (Coinbase Spot)"
    except Exception as e:
        print(f"Coinbase BTC failed: {e}")
    try:
        r = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=6).json()
        price = float(r['result']['XXBTZUSD']['c'][0])
        return f"🟢 BTC ${price:,.0f} (Kraken Spot)"
    except Exception as e:
        print(f"All price sources failed: {e}")
        return "BTC price unavailable"

def get_coin_price(symbol):
    coin_id = COINS[symbol]
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true&include_24hr_high_low=true&include_24hr_vol=true",
            timeout=6
        ).json()
        d = r[coin_id]
        return d['usd'], d.get('usd_24h_change', 0), d.get('usd_24h_high', 0), d.get('usd_24h_low', 0), d.get('usd_24h_vol', 0), "CoinGecko"
    except Exception as e:
        print(f"CoinGecko {symbol} failed: {e}")
    try:
        r = requests.get(f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot", timeout=6).json()
        price = float(r['data']['amount'])
        return price, 0, 0, 0, 0, "Coinbase"
    except Exception as e:
        print(f"Coinbase {symbol} failed: {e}")
    return None, 0, 0, 0, 0, ""

def format_coin_detail(symbol):
    price, change, high, low, vol, src = get_coin_price(symbol)
    if price is None:
        return f"Price for {symbol} temporarily unavailable, please try again later"
    fg_value, fg_label, fg_tip = get_fear_greed_value()
    emoji = "🟢" if change >= 0 else "🔴" if change != 0 else "⚪"
    coin_name = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "DOGE": "Dogecoin", "XRP": "XRP"}.get(symbol, symbol)
    text = f"<b>🪙 {coin_name} ({symbol}) Details</b>\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"
    text += f"📊 <b>Price</b>\n"
    text += f"{emoji} ${price:,.2f}"
    if src != "Coinbase":
        text += f" ({change:+.2f}% 24h)"
    text += f"\n"
    if high and low:
        text += f"24h High: ${high:,.2f}\n"
        text += f"24h Low: ${low:,.2f}\n"
    if vol:
        text += f"24h Volume: ${vol/1e6:.1f}M\n"
    text += f"Source: {src}\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"🧭 <b>Fear & Greed Index</b>\n"
    text += f"{fg_label} ({fg_value}/100)\n"
    text += f"{fg_tip}\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"📰 <b>{symbol} Related News</b>\n\n"
    all_news = fetch_all_news_for_coin(30)
    keywords = COIN_KEYWORDS.get(symbol, [symbol.lower()])
    matched = []
    for n in all_news:
        title_low = n['title'].lower()
        summary_low = n['summary'].lower()
        if any(k in title_low or k in summary_low for k in keywords):
            matched.append(n)
        if len(matched) >= 3:
            break
    if not matched:
        matched = all_news[:3]
        text += "No exclusive news for this coin, here are latest market updates:\n\n"
    for i, n in enumerate(matched, 1):
        text += f"{i}. <b>{n['title']}</b>\n"
        text += f"{n['summary'][:150]}...\n"
        text += f"Source: {n['source']} | {n['link']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "💬 Send <code>BTC</code> / <code>ETH</code> / <code>SOL</code> / <code>DOGE</code> / <code>XRP</code> to check other coins"
    return text

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
    rest = news_list[1:6]
    text = f"<b>🇺🇸 US CRYPTO DIGEST | {date_str}</b>\n"
    text += f"Your daily 5-min US crypto briefing\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"
    text += f"🔥 <b>TOP STORY</b>\n"
    text += f"<b>{top['title']}</b>\n"
    text += f"{top['summary']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"
    text += f"📰 <b>TODAY'S TOP 5</b>\n\n"
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]
    for i, n in enumerate(rest[:5]):
        text += f"{emojis[i]} <b>{n['title']}</b>\n{n['summary']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"📊 <b>MARKET SNAPSHOT</b>\n"
    text += f"{get_btc_price_line()}\n"
    text += f"🧭 {get_market_mood()}\n"
    text += f"💬 Tap below to check coin details in bot"
    return text

# ===== V55.3: Breaking 带图, 没图兜底文字 =====
async def send_breaking(context: ContextTypes.DEFAULT_TYPE, news=None):
    if not news:
        news_list = fetch_us_news(1)
        if not news_list:
            print("Breaking: 没有新新闻，跳过")
            return
        news = news_list[0]
    text = format_breaking(news)
    try:
        image_url = news.get('image', '')
        if image_url:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=image_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=get_join_keyboard()
            )
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", reply_markup=get_join_keyboard(), disable_web_page_preview=True)
        save_sent(news['title'])
        print(f"Breaking sent: {news['title']} image={bool(image_url)}")
    except Exception as e:
        print(f"Breaking photo FAILED: {e} - fallback to text")
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", reply_markup=get_join_keyboard(), disable_web_page_preview=True)
            save_sent(news['title'])
        except Exception as e2:
            print(f"Breaking text fallback FAILED: {e2}")

# ===== V55.3: Digest 带图 - 先发 Top Story 大图, 再发全文 =====
async def send_digest(context: ContextTypes.DEFAULT_TYPE):
    news_list = fetch_us_news(8)
    if not news_list:
        print("Digest: 24h 内没有新新闻，跳过")
        return
    date_str = datetime.now(EASTERN).strftime("%b %d")
    text = format_digest(news_list, date_str)
    try:
        top = news_list[0]
        image_url = top.get('image', '')
        if image_url:
            photo_caption = (
                f"<b>🇺🇸 US CRYPTO DIGEST | {date_str}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🔥 <b>TOP STORY</b>\n"
                f"<b>{top['title']}</b>\n\n"
                f"{top['summary']}"
            )
            if len(photo_caption) > 1000:
                photo_caption = photo_caption[:1000]
            try:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=image_url,
                    caption=photo_caption,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Digest photo FAILED: {e}, continue to send text only")
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", reply_markup=get_join_keyboard(), disable_web_page_preview=True)
        for n in news_list[:6]:
            save_sent(n['title'])
        print(f"Digest sent: {len(news_list)} news image={bool(image_url)}")
    except Exception as e:
        print(f"Digest FAILED: {e}")

# ===== V55: 自动 Breaking 定时任务 =====
async def auto_breaking_job(context: ContextTypes.DEFAULT_TYPE):
    print("Auto Breaking check...")
    await send_breaking(context)

# ===== V53 FIX: 不依赖 job_queue, 用 asyncio 定时删除 =====
async def _delete_after_delay(bot, chat_id, message_id, delay=600):
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        print(f"Whale welcome deleted: {message_id} after {delay}s")
    except Exception as e:
        print(f"Delete welcome failed: {message_id} - {e} - Check bot is admin with Delete Messages permission")

def schedule_delete(context, chat_id, message_id, delay=600):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_delete_after_delay(context.bot, chat_id, message_id, delay))
        print(f"Scheduled delete: {message_id} in {delay}s via asyncio")
    except Exception as e:
        print(f"Schedule delete failed: {e}")

async def on_channel_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return
    cm = update.chat_member
    if cm.chat.id != CHANNEL_ID:
        return
    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status
    user = cm.new_chat_member.user
    if user.is_bot:
        return
    if new_status != "member":
        return
    if old_status not in ["left", "kicked"]:
        return
    print(f"New channel member: {user.username or user.id}")
    try:
        sent = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=WHALE_WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=get_whale_keyboard(),
            disable_web_page_preview=True
        )
        schedule_delete(context, CHANNEL_ID, sent.message_id, 600)
        print(f"Whale welcome sent: {sent.message_id}, will delete in 10min")
    except Exception as e:
        print(f"Whale welcome FAILED: {e}")

# ===== 命令 =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = context.args[0] if context.args else ""
    if payload == "from_channel":
        await update.message.reply_text(
            "👋 Welcome to Crypto Pixie Bot!\n\n"
            "💬 Send <code>BTC</code> / <code>ETH</code> / <code>SOL</code> / <code>DOGE</code> / <code>XRP</code> to check other coins",
            parse_mode="HTML"
        )
        return
    # V55.4: 1号 - 直接搜到 Bot 点进来 - Whale 引流版, 只留鲸鱼按钮
    await update.message.reply_text(
        "🐋 <b>Whale Chatroom — Precision Trading Signals</b>\n\n"
        "📈 <b>Daily offerings:</b>\n"
        "💎 3–5 high-precision trading signals, including entry, stop-loss, and take-profit levels\n"
        "💰 Market forecasts for BTC, ETH, SOL, and other major cryptocurrencies\n"
        "🔥 Latest market developments + tracking of \"whale\" (large-capital) movements\n"
        "📊 Elliott Wave analysis and reviews of your own trades\n\n"
        "No small talk — just actionable insights.",
        parse_mode="HTML",
        reply_markup=get_start_keyboard()
    )

async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking news in last 24h...")
    before = len(load_sent())
    await send_digest(context)
    after = len(load_sent())
    if after > before:
        await update.message.reply_text("✅ Digest sent to channel")
    else:
        await update.message.reply_text("No new news in 24h, skipped")

async def cmd_breaking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking new Breaking...")
    before = len(load_sent())
    await send_breaking(context)
    after = len(load_sent())
    if after > before:
        await update.message.reply_text("✅ Breaking sent to channel")
    else:
        await update.message.reply_text("No new Breaking, skipped")

async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news_list = fetch_us_news(1)
    if not news_list:
        await update.message.reply_text("No new news in 24h")
        return
    n = news_list[0]
    text = format_breaking(n)
    try:
        if n.get('image'):
            await update.message.reply_photo(photo=n['image'], caption=text, parse_mode="HTML", reply_markup=get_join_keyboard())
        else:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_join_keyboard())
    except:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_join_keyboard())

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_digest(update, context)

async def cmd_test_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sent = await context.bot.send_message(chat_id=CHANNEL_ID, text=WHALE_WELCOME_TEXT, parse_mode="HTML", reply_markup=get_whale_keyboard(), disable_web_page_preview=True)
        schedule_delete(context, CHANNEL_ID, sent.message_id, 600)
        await update.message.reply_text("✅ Whale welcome 已发到频道，10分钟后自动删除")
    except Exception as e:
        await update.message.reply_text(f"发送失败: {e}")

async def handle_group_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip().upper()
    if text in COINS:
        await update.message.reply_text("Checking details...", disable_notification=True)
        detail = format_coin_detail(text)
        await update.message.reply_text(detail, parse_mode="HTML", disable_web_page_preview=True)

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
    app.add_handler(CommandHandler("testwelcome", cmd_test_welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_msg))
    app.add_handler(CMH(on_channel_join, CMH.CHAT_MEMBER))
    if app.job_queue:
        app.job_queue.run_daily(send_digest, time=dtime(hour=10, minute=0, tzinfo=EASTERN), name="daily_digest")
        # V55.3: 每 4 小时自动检查 Breaking, 第一次 60 秒后执行
        app.job_queue.run_repeating(auto_breaking_job, interval=14400, first=60, name="auto_breaking")
        print("JobQueue OK - Daily Digest scheduled ET 10:00 + Auto Breaking every 4h")
    else:
        print("WARNING: JobQueue is None! Daily Digest will NOT auto-send. Fix requirements.txt to python-telegram-bot[job-queue]==20.7")
    print("Scheduler v55.4 US News + Whale Welcome + Upstash Dedup + ET 10AM + Async Delete + HEAD Fix + Auto Breaking 4h + News With Image + Start Whale Single Button")
    print(f"CHANNEL_ID={CHANNEL_ID} BOT_USERNAME={BOT_USERNAME} BOT_LINK={get_bot_link()}")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "chat_member", "my_chat_member"])

if __name__ == "__main__":
    main()
