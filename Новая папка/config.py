import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PROXY_URL = os.getenv("PROXY_URL", "")
# Для Vercel: https://твой-проект.vercel.app (без слэша в конце)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
DB_PATH = Path(__file__).parent / "galaxy_station.db"

# Telegram user id админов через запятую
ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "6924900203").split(",")
    if x.strip().isdigit()
}

STARTING_BALANCE = 500
DAILY_BONUS = 250
WORK_COOLDOWN_SEC = 30 * 60
DAILY_COOLDOWN_SEC = 24 * 60 * 60
