import os, asyncio, aiohttp, random, time, re, io
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from flask import Flask
import threading
from PIL import Image, ImageDraw, ImageFont
import xml.etree.ElementTree as ET

TOKEN = os.getenv("BOT_TOKEN")
REPORT_CHAT_ID = os.getenv("REPORT_CHAT_ID") or "-1003734717383"
CHANNEL_ID = os.getenv("CHANNEL_ID") or "-1004496994086"
CHAT_INVITE_LINK = os.getenv("CHAT_INVITE_LINK") or "https://t.me/+QCwJQgsg9EliY2Qx"

if not TOKEN: raise ValueError("BOT_TOKEN not set!")
bot = Bot(token=TOKEN)
dp = Dispatcher()
CACHE = {}; PRICE_HISTORY = {}; LAST_ALERT = {}; CACHE_TTL = 300
ET_TZ = ZoneInfo("America/New_York")
LAST_REPORTS = {"morning": None, "evening": None}
ALERT_COOLDOWN = 3600
WATCH_LIST = ["BTC","ETH","TON","SOL","DOGE","PEPE","NOT","DOGS"]

WELCOME_TEXT = """🐋 Crypto Pixie | Whale Chat - Accurate Signals
📈 What you get every day:
💎 3-5 accurate signals - entry, stop, take profit
💰 Forecast for BTC, ETH, TON and top coins
🔥 Fresh news + where whales are moving money
📊 Wave analysis and review of your trades
No noise here. We earn here.
👇 Tap to join the whale chat:
https://t.me/+QCwJQgsg9EliY2Qx
"""

def calc_rsi_fixed(prices, period=14):
    if len(prices) < period+1: return 50
    deltas = [prices[i]-prices[i-1] for i in range(1, len(prices))]
    gains = [d if d>0 else 0 for d in deltas[-period:]]
    losses = [-d if d<0 else 0 for d in deltas[-period:]]
    ag = sum(gains)/period or 0.01; al = sum(losses)/period or 0.01
    return 100 - (100/(1+ag/al if al!=0 else 1))

async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=10) as r:
            if r.status==200: return await r.json()
    except Exception as e:
        print(f"fetch fail {url} {e}")
    return None

async def get_real_price(session, sym):
    try:
        data = await fetch_json(session, f"https://www.okx.com/api/v5/market/ticker?instId={sym}-USDT")
        if data and data.get('data'):
            d = data['data'][0]
            last = float(d.get('last') or 0); open24 = float(d.get('open24h') or 0)
            if last > 0 and open24 > 0: return last, (last-open24)/open24*100
            if last > 0: return last, 0.0
    except Exception as e: print(f"OKX spot fail {sym} {e}")
    try:
        data = await fetch_json(session, f"https://www.okx.com/api/v5/market/ticker?instId={sym}-USDT-SWAP")
        if data and data.get('data'):
            d = data['data'][0]
            last = float(d.get('last') or 0); open24 = float(d.get('open24h') or 0)
            if last>0 and open24>0: return last, (last-open24)/open24*100
            if last>0: return last, 0.0
    except Exception as e: print(f"OKX swap fail {sym} {e}")
    try:
        data = await fetch_json(session, f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym}USDT")
        if data and data.get('result') and data['result'].get('list'):
            d = data['result']['list'][0]
            last = float(d.get('lastPrice') or 0); change = float(d.get('price24hPcnt') or 0)*100
            if last>0: return last, change
    except Exception as e: print(f"Bybit fail {sym} {e}")
    try:
        cg_map = {"BTC":"bitcoin","ETH":"ethereum","TON":"the-open-network","SOL":"solana","DOGE":"dogecoin","PEPE":"pepe","NOT":"notcoin","DOGS":"dogs"}
        cg_id = cg_map.get(sym, sym.lower())
        cg = await fetch_json(session, f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true")
        if cg and cg_id in cg:
            p=float(cg[cg_id]['usd']); c=float(cg[cg_id].get('usd_24h_change',0))
            if p>0: return p, c
    except Exception as e: print(f"CG fail {sym} {e}")
    try:
        bn = await fetch_json(session, f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={sym}USDT")
        if bn and 'lastPrice' in bn: return float(bn['lastPrice']), float(bn['priceChangePercent'])
    except Exception as e: print(f"Binance vision fail {sym} {e}")
    return None, None

# ===== US NEWS - DIRECT RSS, NO rss2json =====
async def get_top5_news():
    real_news = []
    crypto_keywords = ["bitcoin","btc","ethereum","eth","ton","crypto","blockchain","token","solana","sol","doge","usdt","tether","binance","coin","mining","defi","etf","xrp","sec","whale"]
    async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=8)) as s:
        rss_sources = [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
        ]
        for rss_url in rss_sources:
            try:
                async with s.get(rss_url) as r:
                    if r.status != 200:
                        print(f"RSS {r.status} {rss_url}"); continue
                    text = await r.text()
                    root = ET.fromstring(text)
                    for item in root.findall(".//item")[:10]:
                        title = (item.findtext("title") or "").strip()
                        link = (item.findtext("link") or "").strip()
                        desc_raw = item.findtext("description") or ""
                        desc = re.sub(r"<[^>]+>", "", desc_raw)[:140]
                        image = None
                        for child in item:
                            tag = child.tag.lower()
                            if "content" in tag or "thumbnail" in tag or "enclosure" in tag:
                                image = child.get("url") or child.get("href")
                                if image: break
                        if len(title) < 15: continue
                        low = title.lower()
                        if "openai" in low: continue
                        if not any(k in low for k in crypto_keywords): continue
                        if any(x['url']==link for x in real_news): continue
                        real_news.append({"title": title[:90], "url": link, "desc": desc, "image": image})
                        if len(real_news) >= 5: break
            except Exception as e:
                print(f"RSS fail {rss_url}: {e}"); continue
            if len(real_news) >= 5: break
    print(f"Got {len(real_news)} US news")
    if len(real_news) < 3:
        real_news = [
            {"title":"Bitcoin trades near $76,800, ETF outflows hit $399M","url":"https://www.coindesk.com/","desc":"Bitcoin holds near key level as ETF outflows continue.","image":None},
            {"title":"Fear & Greed Index drops to 26 - market in fear zone","url":"https://www.coindesk.com/","desc":"Sentiment turns fearful across crypto market.","image":None},
            {"title":"TON holds $1.58-1.64 as altcoins fall","url":"https://cointelegraph.com/","desc":"TON shows resilience while altcoins drop.","image":None},
            {"title":"Lisk shuts down Layer-2, plans to burn 5.2M LSK","url":"https://cointelegraph.com/","desc":"Lisk announces L2 shutdown and token burn.","image":None},
            {"title":"Liquid Network restores L-BTC backing after exploit","url":"https://cointelegraph.com/","desc":"Liquid restores peg after incident.","image":None},
        ]
    return real_news[:5]

def make_cover(image_url, title):
    try:
        import requests
        r = requests.get(image_url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        w, h = img.size
        target_h = int(w * 9 / 16)
        if h > target_h:
            top = (h - target_h)//2
            img = img.crop((0, top, w, top+target_h))
        else:
            img = img.resize((1080, 608))
        w, h = img.size
        overlay = Image.new("L", (1, h))
        for y in range(h):
            alpha = int(180 * max(0, (y - h*0.35) / (h*0.65)) ** 1.5)
            overlay.putpixel((0, y), alpha)
        overlay = overlay.resize((w, h))
        black = Image.new("RGB", (w, h), (0,0,0))
        img = Image.composite(black, img, overlay.point(lambda x: x))
        draw = ImageDraw.Draw(img)
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
            font_tag = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        except:
            font_title = ImageFont.load_default(); font_tag = ImageFont.load_default()
        words = title.split(); lines, cur = [], ""
        for wd in words:
            test = (cur + " " + wd).strip()
            if draw.textlength(test, font=font_title) < w - 80: cur = test
            else: lines.append(cur); cur = wd
        if cur: lines.append(cur)
        lines = lines[:3]
        draw.rectangle([40, h-260, 240, h-210], fill=(220, 38, 38))
        draw.text((55, h-252), "TOP STORY", fill="white", font=font_tag)
        y = h - 200
        for line in lines:
            draw.text((40, y), line, fill="white", font=font_title); y += 55
        buf = io.BytesIO(); img.save(buf, format="JPEG", quality=88); buf.seek(0)
        return buf
    except Exception as e:
        print(f"Make cover fail: {e}"); return None

async def get_analysis(symbol="btc"):
    sym=symbol.upper()
    async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as s:
        price_usd, change = await get_real_price(s, sym)
        if price_usd is None:
            fallback = {"BTC":76474,"ETH":2700,"TON":1.62,"SOL":145,"DOGE":0.14}
            price_usd = fallback.get(sym, 0); change = -0.51 if sym=="BTC" else 0.0
        closes=[]
        kl = await fetch_json(s,f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT&bar=1D&limit=20")
        if kl and kl.get('data'):
            try: closes=[float(k[4]) for k in reversed(kl['data'])]
            except: pass
        if not closes: closes=[price_usd*(0.98+random.random()*0.04) for _ in range(20)] if price_usd>0 else [100]*20
        ma7=sum(closes[-7:])/7 if closes else 0
        ma7_text=f"MA7 below price (bearish)" if price_usd and price_usd < ma7 else f"MA7 above price (bullish)"
        rsi=calc_rsi_fixed(closes)
        rsi_text=f"{rsi:.0f} (oversold)" if rsi<=38 else f"{rsi:.0f} (overbought)" if rsi>=65 else f"{rsi:.0f} (neutral)"
        fg_val,fg_text=26,"Fear"
        fg=await fetch_json(s,"https://api.alternative.me/fng/?limit=1")
        if fg and 'data' in fg:
            try: fg_val=int(fg['data'][0]['value']); fg_text=fg['data'][0]['value_classification']
            except: pass
        top = await get_top5_news()
        usdt_rub=83.9
        rub=await fetch_json(s,"https://www.okx.com/api/v5/market/ticker?instId=USDT-RUB")
        if rub and rub.get('data'):
            try: usdt_rub=float(rub['data'][0]['last'])
            except: pass
        conclusion="Fundamentally positive, technically oversold. Rebound possible." if rsi<=38 else "Fundamentally positive, technically overbought. Pullback possible." if rsi>=68 else "Fundamentally positive, technically neutral."
        return {"price":price_usd,"change":change,"ma7_text":ma7_text,"rsi_text":rsi_text,"fg_val":fg_val,"fg_text":fg_text,"news":top[:3],"rub":usdt_rub,"conclusion":conclusion}

def format_text(symbol,a):
    date=datetime.now().strftime("%d.%m.%Y")
    price_str = f"${a['price']:,.2f} ({a['change']:+.2f}%)" if a['price']>0 else "price temporarily unavailable"
    news_lines="".join([f'{i}. <a href="{n["url"]}">{n["title"]}</a>\n' for i,n in enumerate(a['news'],1)]) if a['news'] else "No news yet\n"
    return f"""📊 {symbol.upper()} Analysis | {date}
💰 Price: {price_str}
📈 Technicals: {a['ma7_text']}, RSI {a['rsi_text']}
🧠 Sentiment: Fear & Greed {a['fg_val']} ({a['fg_text']})
📋 What moves price today:
{news_lines}
⚠️ Conclusion: {a['conclusion']}
Not financial advice
💱 T-Bank USDT Rate: {a['rub']:.1f} RUB 👉 @tbank_usdt_bot
#{symbol.upper()}"""

async def build_digest(is_morning=True):
    results={}
    for sym in ["BTC","ETH","TON","SOL"]:
        results[sym]=await get_analysis(sym); await asyncio.sleep(0.5)
    top5=await get_top5_news()
    date=datetime.now(ET_TZ).strftime("%d.%m.%Y")
    def fmt(p,c):
        if p is None or p==0: return "loading..."
        return f"${p:,.0f} ({c:+.2f}%)" if abs(p)>10 else f"${p:.3f} ({c:+.2f}%)"
    def ch(sym):
        p=results[sym]['price']; c=results[sym]['change']
        if p is None or p==0: return "0.00%"
        return f"{c:+.2f}%"
    news_block="".join([f'{i}. <a href="{n["url"]}">{n["title"][:85]}</a>\n' for i,n in enumerate(top5,1)])
    if is_morning:
        text=f"""☀️ <b>MORNING DIGEST | {date} ET</b>
💰 Market: BTC {fmt(results['BTC']['price'], results['BTC']['change'])} | TON {fmt(results['TON']['price'], results['TON']['change'])}
🧠 Fear: {results['BTC']['fg_val']} ({results['BTC']['fg_text']})
🔥 <b>TOP-5 US News:</b>
{news_block}
⚡️ Conclusion: {results['BTC']['conclusion']}
#morning #BTC #TON"""
    else:
        text=f"""🌙 <b>EVENING RECAP | {date} ET</b>
Today: BTC {ch('BTC')} | ETH {ch('ETH')} | TON {ch('TON')}
🧠 Fear & Greed: {results['BTC']['fg_val']}
📌 <b>What happened today:</b>
{news_block}
Tomorrow at 7:00 AM ET morning digest.
#evening #TON"""
    return text, top5, results

async def send_single_news(chat_id):
    try:
        top5 = await get_top5_news()
        if not top5:
            await bot.send_message(chat_id=int(chat_id), text="Failed to fetch news, try again later."); return
        head = top5[0]
        def short(t, n=75):
            t = t.strip(); return t if len(t) <= n else t[:n] + "..."
        caption = "📰 <b>CRYPTO DAILY NEWS</b>\n\n"
        caption += f"🔥 <b>{short(head['title'], 90)}</b>\n"
        caption += f"{short(head.get('desc',''), 110)}\n"
        caption += f"👉 <a href=\"{head['url']}\">Read Full Article →</a>\n\n"
        caption += "━━━━━━━━━━━━━━━\n🗞️ <b>MORE STORIES</b>\n\n"
        emojis = ["📈", "🏛️", "💰", "🌐"]
        for i, n in enumerate(top5[1:5]):
            caption += f"{emojis[i]} <b>{short(n['title'], 65)}</b>\n"
            caption += f"<a href=\"{n['url']}\">Read →</a>\n\n"
        caption += "— Crypto Pixie ✨"
        if len(caption) > 1000: caption = caption[:1000]
        cover = None
        try:
            if head.get('image'):
                cover = await asyncio.to_thread(make_cover, head.get('image'), head['title'])
        except Exception as e:
            print(f"cover skip: {e}"); cover = None
        if cover:
            await bot.send_photo(chat_id=int(chat_id), photo=cover, caption=caption, parse_mode="HTML")
        elif head.get('image'):
            await bot.send_photo(chat_id=int(chat_id), photo=head['image'], caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=int(chat_id), text=caption, parse_mode="HTML", disable_web_page_preview=True)
        print("✅ Single news sent")
    except Exception as e:
        print(f"❌ Single news FAILED: {e}")

async def send_digest(is_morning=True):
    try:
        me=await bot.get_me()
        if is_morning:
            await send_single_news(CHANNEL_ID); await asyncio.sleep(1)
        text, top5, results = await build_digest(is_morning)
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"BTC ${results['BTC']['price']:,.0f} - Analysis" if results['BTC']['price']>0 else "BTC - Analysis", url=f"https://t.me/{me.username}?start=analyze")],
            [InlineKeyboardButton(text="💬 Whale Chat", url=CHAT_INVITE_LINK)]
        ])
        await bot.send_message(chat_id=int(CHANNEL_ID), text=text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
        print(f"✅ Digest sent")
    except Exception as e: print(f"❌ DIGEST FAILED: {e}")

async def price_alert_loop():
    await asyncio.sleep(10)
    async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as session:
        while True:
            try:
                for sym in WATCH_LIST:
                    price, _ = await get_real_price(session, sym)
                    if not price: continue
                    now=time.time()
                    if sym not in PRICE_HISTORY: PRICE_HISTORY[sym]=[]
                    PRICE_HISTORY[sym].append((now,price))
                    PRICE_HISTORY[sym]=[(t,p) for t,p in PRICE_HISTORY[sym] if now-t<=3600]
                    if len(PRICE_HISTORY[sym])<2: continue
                    price_5m=next((p for t,p in reversed(PRICE_HISTORY[sym]) if now-t>=300),None)
                    price_1h=PRICE_HISTORY[sym][0][1]
                    if not price_5m: continue
                    change_5m=(price-price_5m)/price_5m*100; change_1h=(price-price_1h)/price_1h*100
                    should=None
                    if abs(change_5m)>=2.5: should=f"⚡️ {sym} PUMP" if change_5m>0 else f"⚡️ {sym} DUMP"
                    elif abs(change_1h)>=4.0: should=f"🚨 {sym} UP +{change_1h:.1f}%" if change_1h>0 else f"🚨 {sym} DOWN {change_1h:.1f}%"
                    if should:
                        if sym in LAST_ALERT and now-LAST_ALERT[sym]<ALERT_COOLDOWN: continue
                        LAST_ALERT[sym]=now
                        me=await bot.get_me()
                        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{sym} Analysis", url=f"https://t.me/{me.username}?start={sym}")],[InlineKeyboardButton(text="Chat", url=CHAT_INVITE_LINK)]])
                        txt=f"{should} | {datetime.now(ET_TZ).strftime('%H:%M')} ET\n${price:,.4f} {change_5m:+.2f}% 5m"
                        try: await bot.send_message(chat_id=int(REPORT_CHAT_ID), text=txt, reply_markup=kb)
                        except: pass
                await asyncio.sleep(60)
            except: await asyncio.sleep(60)

async def scheduler_loop():
    print(f"Scheduler v37 US News EN - Final")
    while True:
        try:
            now_et=datetime.now(ET_TZ)
            if now_et.hour==7 and 0 <= now_et.minute < 2:
                if LAST_REPORTS["morning"]!=now_et.date(): await send_digest(True); LAST_REPORTS["morning"]=now_et.date()
            if now_et.hour==19 and 0 <= now_et.minute < 2:
                if LAST_REPORTS["evening"]!=now_et.date(): await send_digest(False); LAST_REPORTS["evening"]=now_et.date()
            await asyncio.sleep(30)
        except: await asyncio.sleep(60)

async def delete_after(msg:Message, delay:int):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

@dp.chat_member()
async def on_new_channel_subscriber(event: ChatMemberUpdated):
    try:
        if event.chat.type != "channel": return
        is_new = event.old_chat_member.status in ["left", "kicked"] and event.new_chat_member.status in ["member", "administrator", "creator", "restricted"]
        if not is_new: return
        if event.new_chat_member.user.is_bot: return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Enter whale chat", url=CHAT_INVITE_LINK)]])
        msg = await bot.send_message(chat_id=event.chat.id, text=WELCOME_TEXT, reply_markup=kb)
        asyncio.create_task(delete_after(msg, 600))
    except Exception as e: print(f"WELCOME FAILED: {e}")

async def handle_any(m:Message):
    try:
        if m.from_user and m.from_user.is_bot: return
        txt_full=m.text or ""
        if txt_full.startswith("/"): return
        sym=''.join(filter(str.isalnum,txt_full.lower().strip().split()[0]))[:10]
        if len(sym)<2: return
        key=(m.chat.id, sym.lower()); now=time.time()
        if key in CACHE:
            ts,fid=CACHE[key]
            if now-ts<CACHE_TTL:
                warn=await m.answer(f"⚠️ {sym.upper()} recently", reply_to_message_id=fid)
                asyncio.create_task(delete_after(warn,30)); asyncio.create_task(delete_after(m,30)); return
        a=await get_analysis(sym); text=format_text(sym,a)
        sent=await m.answer(text,parse_mode="HTML",disable_web_page_preview=True)
        CACHE[key]=(now, sent.message_id)
    except Exception as e: print(e)

@dp.message(Command("start"))
async def start(m:Message): await m.answer("Hi! Send ticker: BTC, ETH, TON...")
@dp.message(Command("report"))
async def manual_report(m:Message):
    await m.answer(f"Sending digest..."); await send_digest(False)
@dp.message(Command("news"))
async def news_cmd(m:Message):
    await m.answer("Fetching latest US news..."); await send_single_news(m.chat.id)

@dp.message(F.text)
async def private_msg(m:Message): await handle_any(m)
@dp.channel_post(F.text)
async def channel_msg(m:Message): await handle_any(m)

async def main():
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(price_alert_loop())
    await dp.start_polling(bot, allowed_updates=["message","channel_post","chat_member","my_chat_member"])

app=Flask(__name__)
@app.route('/')
def home(): return 'ok v37 US News EN Final'

def run_flask():
    port=int(os.environ.get("PORT",10000)); app.run(host='0.0.0.0',port=port)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    asyncio.run(main())
