import os
import re
import threading
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import feedparser
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes

# ===== Render 保活 =====
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
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1004218958873"))
EASTERN = ZoneInfo("America/New_York")

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]

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
    return ""

def fetch_us_news(limit=10):
    all_news = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
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
    return "BTC price unavailable"

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
    return text

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
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", disable_web_page_preview=True)
        print(f"Digest sent: {len(news_list)} news image={bool(image_url)}")
    except Exception as e:
        print(f"Digest FAILED: {e}")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    if app.job_queue:
        app.job_queue.run_daily(send_digest, time=dtime(hour=10, minute=0, tzinfo=EASTERN), name="daily_digest")
        print("JobQueue OK - Daily Digest scheduled ET 10:00")
    else:
        print("WARNING: JobQueue is None! Daily Digest will NOT auto-send. Fix requirements.txt to python-telegram-bot[job-queue]==20.7")
    print("Scheduler - Only Daily Digest ET 10:00")
    print(f"CHANNEL_ID={CHANNEL_ID}")
    app.run_polling(drop_pending_updates=True, allowed_updates=[])

if __name__ == "__main__":
    main()
