"""
Точка входа для Vercel (webhook).
Локально бот запускай: python bot.py
"""
import logging
import os

from aiogram.types import Update
from fastapi import FastAPI, Request, Response

import database as db
from bot import create_bot, setup_dispatcher
from config import BOT_TOKEN, WEBHOOK_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = create_bot()
dp = setup_dispatcher()

app = FastAPI(title="Galaxy Station Bot")


def resolve_webhook_base() -> str | None:
    if WEBHOOK_URL:
        return WEBHOOK_URL
    vercel_url = os.getenv("VERCEL_URL", "").strip()
    if not vercel_url:
        return None
    if vercel_url.startswith("http"):
        return vercel_url.rstrip("/")
    return f"https://{vercel_url}"


@app.on_event("startup")
async def on_startup() -> None:
    db.init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан")
        return

    base = resolve_webhook_base()
    if not base:
        logger.warning("WEBHOOK_URL / VERCEL_URL не задан — webhook не установлен")
        return

    webhook_url = f"{base}/api/webhook"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info("Webhook установлен: %s", webhook_url)


@app.get("/")
async def health() -> dict:
    return {
        "ok": True,
        "service": "Galaxy Station Bot",
        "webhook_base": resolve_webhook_base(),
    }


@app.post("/api/webhook")
async def telegram_webhook(request: Request) -> Response:
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Ошибка обработки webhook")
    return Response(content="ok", media_type="text/plain")
