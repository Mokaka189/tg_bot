import requests
import time
import json
from PIL import Image
from io import BytesIO
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import os # Импортируем модуль os

# Настройки логирования
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Ваши настройки API ---
base_url = 'https://api-inference.modelscope.ai/'
# Получаем API ключ ModelScope из переменной окружения
api_key = os.environ.get("MODEL_SCOPE_API_KEY") 
if not api_key:
    logger.error("MODEL_SCOPE_API_KEY не установлен в переменных окружения!")
    # В среде развертывания лучше явно выходить, если ключи не настроены
    exit(1)

common_headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}
# --- Конец ваших настроек API ---

# Получаем токен Telegram бота из переменной окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен в переменных окружения!")
    # В среде развертывания лучше явно выходить, если 
    # ключи не настроены
    exit(1)

# Состояние для отслеживания ожидания запроса на генерацию
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет сообщение при получении команды /start."""
    keyboard = [[InlineKeyboardButton("Сгенерировать изображение", callback_data="generate_image")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Я бот для генерации изображений.", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия кнопок."""
    query = update.callback_query
    await query.answer()

    if query.data == "generate_image":
        user_states[query.from_user.id] = "waiting_for_prompt"
        await query.edit_message_text("Пожалуйста, введите текст для генерации изображения:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает текстовые сообщения пользователя."""
    user_id = update.message.from_user.id
    if user_id in user_states and user_states[user_id] == "waiting_for_prompt":
        prompt = update.message.text
        await update.message.reply_text(f"Начинаю генерацию изображения по запросу: '{prompt}'. Это может занять некоторое время...")
        del user_states[user_id] # Сбрасываем состояние

        try:
            image_url = await generate_image_from_prompt(prompt)
            if image_url:
                await update.message.reply_photo(image_url, caption="Ваше сгенерированное изображение:")
            else:
                await update.message.reply_text("Не удалось сгенерировать изображение. Пожалуйста, попробуйте еще раз.")
        except Exception as e:
            logger.error(f"Ошибка при генерации изображения для пользователя {user_id}: {e}")
            await update.message.reply_text("Произошла ошибка при попытке сгенерировать изображение. Пожалуйста, попробуйте позже.")
    else:
        await update.message.reply_text("Нажмите 'Сгенерировать изображение', чтобы начать.")

async def generate_image_from_prompt(prompt: str) -> str | None:
    """
    Генерирует изображение, используя ваш API, и возвращает URL изображения.
    """
    response = requests.post(
        f"{base_url}v1/images/generations",
        headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
        data=json.dumps({
            "model": "DiffSynth-Studio/Z-Image-Turbo-DistillPatch",
            "prompt": prompt
        }, ensure_ascii=False).encode('utf-8')
    )
    response.raise_for_status()
    task_id = response.json()["task_id"]

    for _ in range(20): # Попытки проверки статуса, можно увеличить или уменьшить
        time.sleep(5) # Ждем 5 секунд перед каждой проверкой
        result = requests.get(
            f"{base_url}v1/tasks/{task_id}",
            headers={**common_headers, "X-ModelScope-Task-Type": "image_generation"},
        )
        result.raise_for_status()
        data = result.json()

        if data["task_status"] == "SUCCEED":
            if data["output_images"]:
                return data["output_images"][0]
            else:
                logger.warning(f"Генерация успешно завершена, но URL изображения не найден в ответе: {data}")
                return None
        elif data["task_status"] == "FAILED":
            logger.error(f"Генерация изображения провалилась для task_id {task_id}: {data}")
            return None
        elif data["task_status"] == "RUNNING" or data["task_status"] == "PENDING":
            continue # Продолжаем ждать
        else:
            logger.warning(f"Неизвестный статус задачи {task_id}: {data['task_status']}")
            return None

    logger.error(f"Время ожидания генерации изображения для task_id {task_id} истекло.")
    return None

def main() -> None:
    """Запускает бота."""
    logger.info("Функция main() вызвана.")
    try:
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        logger.info("Application успешно построен.")

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Обработчики добавлены.")

        logger.info("Запускаем бота (run_polling)...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Бот остановлен (run_polling завершился).")
    except Exception as e:
        logger.exception("Произошла ошибка при запуске бота:") # Используем exception для полного стектрейса

if __name__ == "__main__":
    logger.info("Скрипт запущен напрямую.")
    main()
