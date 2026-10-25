import asyncio
from telegram import Bot
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL, DRY_RUN

async def publish_text(title: str, body: str):
    if DRY_RUN:
        return {"status": "dry_run", "message_id": None}
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в .env")
    if not TELEGRAM_CHANNEL:
        raise RuntimeError("Не задан TELEGRAM_CHANNEL в .env")
    text = body.strip()
    # Заголовок должен быть первым предложением для более предсказуемого кросс-постинга.
    if not text.startswith(title):
        text = f"{title}\n\n{text}"
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=text,
            disable_web_page_preview=True
        )
    return {"status": "published", "message_id": msg.message_id}

def publish(title, body):
    return asyncio.run(publish_text(title, body))
