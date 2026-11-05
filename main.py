async def send_news_messages(bot, chat_id):
    news = fetch_news(5)
    if not news:
        await bot.send_message(chat_id=chat_id, text="Failed to fetch news, try again later.")
        return

    # --- ONE MESSAGE ONLY: Photo + All news in caption ---
    head = news[0]

    def short(t, n=75):
        t = t.strip()
        return t if len(t) <= n else t[:n] + "..."

    # Build ONE caption, must be < 1024 chars for Telegram photo
    caption = "📰 <b>CRYPTO DAILY NEWS</b>\n\n"
    caption += f"🔥 <b>{short(head['title'], 90)}</b>\n"
    caption += f"{short(head['desc'], 110)}\n"
    caption += f"👉 <a href=\"{head['link']}\">Read Full Article →</a>\n\n"
    caption += "━━━━━━━━━━━━━━━\n🗞️ <b>MORE STORIES</b>\n\n"

    emojis = ["📈", "🏛️", "💰", "🌐"]
    for i, n in enumerate(news[1:5]):
        caption += f"{emojis[i]} <b>{short(n['title'], 65)}</b>\n"
        caption += f"<a href=\"{n['link']}\">Read →</a>\n\n"
    caption += "— Crypto Pixie ✨"

    # Safety: cut to 1000 chars if too long
    if len(caption) > 1000:
        caption = caption[:1000]

    cover = make_cover(head["image"], head["title"]) if head["image"] else None
    try:
        if cover:
            await bot.send_photo(chat_id=chat_id, photo=cover, caption=caption, parse_mode="HTML")
        elif head["image"]:
            await bot.send_photo(chat_id=chat_id, photo=head["image"], caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print(f"Send single news failed: {e}")
        await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", disable_web_page_preview=True)
