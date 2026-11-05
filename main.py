import os, re, io, threading, requests
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

def _keep_alive():
    port = int(os.environ.get("PORT", 10000))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
        def log_message(self, *a): pass
    HTTPServer(("0.0.0.0", port), H).serve_forever()
threading.Thread(target=_keep_alive, daemon=True).start()

def get_real_image_from_article(link, fallback):
    """Get real og:image from news article page"""
    try:
        r = requests.get(link, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        html = r.text
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if m and m.group(1).startswith("http"):
            return m.group(1)
        m2 = re.search(r'<meta name="twitter:image" content="([^"]+)"', html)
        if m2 and m2.group(1).startswith("http"):
            return m2.group(1)
    except Exception as e:
        print(f"og:image fail {link}: {e}")
    return fallback

def fetch_news(limit=5):
    try:
        url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = re.sub(r"<[^>]+>", "", item.findtext("description", "").strip())
            if len(desc) > 140: desc = desc[:140] + "..."
            rss_img = None
            for child in item:
                tag = child.tag.lower()
                if "content" in tag or "thumbnail" in tag or "enclosure" in tag:
                    rss_img = child.get("url") or child.get("href")
                    if rss_img: break
            if not rss_img:
                enc = item.find("enclosure")
                if enc is not None: rss_img = enc.get("url")
            # Fetch REAL image from article page
            real_img = get_real_image_from_article(link, rss_img)
            if title and link:
                items.append({"title": title, "link": link, "desc": desc, "image": real_img})
        return items
    except Exception as e:
        print(f"News fetch error: {e}")
        return []

def make_cover(image_url, title):
    """Download real news image, draw title on it like magazine cover"""
    try:
        r = requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        # Crop to 16:9
        w, h = img.size
        target_h = int(w * 9 / 16)
        if h > target_h:
            top = (h - target_h)//2
            img = img.crop((0, top, w, top+target_h))
        else:
            img = img.resize((1080, 608))
        w, h = img.size
        # Dark gradient at bottom
        overlay = Image.new("L", (1, h))
        for y in range(h):
            # 0 at top, 180 at bottom
            alpha = int(180 * max(0, (y - h*0.35) / (h*0.65)) ** 1.5)
            overlay.putpixel((0, y), alpha)
        overlay = overlay.resize((w, h))
        black = Image.new("RGB", (w, h), (0,0,0))
        img = Image.composite(black, img, overlay.point(lambda x: x))
        draw = ImageDraw.Draw(img)
        # Font - try DejaVu, fallback default
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
            font_tag = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        except:
            font_title = ImageFont.load_default()
            font_tag = ImageFont.load_default()
        # Wrap title
        words = title.split()
        lines, cur = [], ""
        for wd in words:
            test = (cur + " " + wd).strip()
            if draw.textlength(test, font=font_title) < w - 80:
                cur = test
            else:
                lines.append(cur); cur = wd
        if cur: lines.append(cur)
        lines = lines[:3]
        # Draw tag
        draw.rectangle([40, h-260, 240, h-210], fill=(220, 38, 38))
        draw.text((55, h-252), "TOP STORY", fill="white", font=font_tag)
        y = h - 200
        for line in lines:
            draw.text((40, y), line, fill="white", font=font_title)
            y += 55
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Make cover fail: {e}")
        return None

async def send_news_messages(bot, chat_id):
    news = fetch_news(5)
    if not news:
        await bot.send_message(chat_id=chat_id, text="Failed to fetch news, try again later.")
        return
    await bot.send_message(chat_id=chat_id, text="📰 <b>CRYPTO DAILY NEWS</b>\n━━━━━━━━━━━━━━━", parse_mode="HTML")
    head = news[0]
    cover = make_cover(head["image"], head["title"]) if head["image"] else None
    caption = f"🔥 <b>{head['title']}</b>\n\n{head['desc']}\n\n👉 <a href=\"{head['link']}\">Read Full Article →</a>"
    try:
        if cover:
            await bot.send_photo(chat_id=chat_id, photo=cover, caption=caption, parse_mode="HTML")
        elif head["image"]:
            await bot.send_photo(chat_id=chat_id, photo=head["image"], caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print(f"Head send fail: {e}")
        await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", disable_web_page_preview=True)
    small = "🗞️ <b>MORE STORIES</b>\n━━━━━━━━━━━━━━━\n\n"
    emojis = ["📈","🏛️","💰","🌐"]
    for i, n in enumerate(news[1:5]):
        small += f"{emojis[i]} <b>{n['title']}</b>\n<a href=\"{n['link']}\">Read →</a>\n\n"
    small += "━━━━━━━━━━━━━━━\n— Crypto Pixie ✨"
    await bot.send_message(chat_id=chat_id, text=small, parse_mode="HTML", disable_web_page_preview=True)

async def send_daily_news(bot):
    if not CHANNEL_ID: return
    try:
        await send_news_messages(bot, CHANNEL_ID)
        print("News sent!")
    except Exception as e:
        print(f"Send news failed: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ Welcome to Crypto Pixie!\n\n/price BTC - Check price\n/news - Get latest 5 news now\n/send <msg> - Send to channel\n/test - Test channel connection")
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price BTC"); return
    coin = context.args[0].upper(); symbol = f"{coin}USDT"
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=10).json()
        if "lastPrice" not in r:
            await update.message.reply_text(f"Coin {coin} not found"); return
        p=float(r["lastPrice"]); chg=float(r["priceChangePercent"])
        await update.message.reply_text(f"{'🟢' if chg>=0 else '🔴'} {coin}: ${p:,.2f}\n24h: {chg:.2f}%")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching latest REAL news...")
    await send_news_messages(context.bot, update.effective_chat.id)
async def send_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID not set"); return
    if not context.args:
        await update.message.reply_text("Usage: /send Hello"); return
    await context.bot.send_message(chat_id=CHANNEL_ID, text=" ".join(context.args))
    await update.message.reply_text("✅ Sent to channel!")
async def test_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ Crypto Pixie connected!")
        await update.message.reply_text("✅ Test sent!")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
async def post_init(app):
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("America/New_York"))
    scheduler.add_job(send_daily_news, CronTrigger(hour=7, minute=0), args=[app.bot])
    scheduler.add_job(send_daily_news, CronTrigger(hour=19, minute=0), args=[app.bot])
    scheduler.start()
    print("Scheduler started: 7AM & 7PM ET - Real News + Real Cover")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("news", news_cmd))
    app.add_handler(CommandHandler("send", send_to_channel))
    app.add_handler(CommandHandler("test", test_channel))
    print("Bot started...")
    app.run_polling()
