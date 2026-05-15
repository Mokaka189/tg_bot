import asyncio
import logging
import random
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import admin
import database as db
from config import ADMIN_IDS, BOT_TOKEN, DAILY_BONUS, PROXY_URL
from game import MODULES, WORK_MAX, WORK_MIN, income_label

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_time(seconds: int) -> str:
    if seconds <= 0:
        return "0 мин"
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def station_text(user: dict, modules: dict[str, int]) -> str:
    lines = [
        f"🛰 <b>Станция командира {user['display_name']}</b>",
        f"💎 Баланс: <b>{user['balance']}</b> кредитов",
        "",
        "<b>Твои станции:</b>",
    ]
    stations = db.list_stations(user["user_id"])
    if not stations:
        lines.append("Пока пусто — зайди в /shop и купи первый модуль.")
    else:
        for s in stations:
            m = MODULES.get(s["module_key"])
            label = f"{m.emoji} {m.name}" if m else s["module_key"]
            lines.append(f"  #{s['id']} — {label}")
        pending = db.pending_income(user, modules)
        lines.extend(
            [
                "",
                f"📦 К сбору: <b>{pending}</b> 💎 (команда /collect)",
            ]
        )
    return "\n".join(lines)


def shop_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for m in MODULES.values():
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{m.emoji} {m.name} — {m.price} 💎",
                    callback_data=f"buy_{m.key}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="🛰 Моя станция", callback_data="my_station")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def main_menu_keyboard(user_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
            InlineKeyboardButton(text="🛒 Магазин", callback_data="shop"),
        ],
        [
            InlineKeyboardButton(text="📦 Собрать", callback_data="collect"),
            InlineKeyboardButton(text="🚀 Миссия", callback_data="work"),
        ],
        [
            InlineKeyboardButton(text="🎁 Ежедневка", callback_data="daily"),
            InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
        ],
    ]
    if user_id and user_id in ADMIN_IDS:
        rows.extend(admin.admin_keyboard_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def cmd_start(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    display = user.full_name or user.username or "Командир"
    db.get_or_create_user(user.id, user.username, display)

    text = (
        "🌌 <b>Добро пожаловать в «Галактическую станцию»!</b>\n\n"
        "Ты — командир космической базы. Покупай модули, они приносят "
        "пассивный доход. Отправляй экспедиции, забирай ежедневную награду "
        "и поднимайся в рейтинге богатейших командиров.\n\n"
        "Стартовый капитал: <b>500</b> 💎\n\n"
        "Команды:\n"
        "/balance — баланс и станция\n"
        "/shop — магазин модулей\n"
        "/collect — собрать доход\n"
        "/work — миссия на астероиды\n"
        "/daily — ежедневный бонус\n"
        "/top — рейтинг\n"
        "/help — справка"
    )
    if user.id in ADMIN_IDS:
        text += f"\n\n{admin.admin_panel_text()}"
    await message.answer(text, reply_markup=main_menu_keyboard(user.id))


async def cmd_help(message: Message) -> None:
    uid = message.from_user.id if message.from_user else None
    text = (
        "📖 <b>Как играть</b>\n\n"
        "1. В /shop покупай модули — они копят кредиты каждый час.\n"
        "2. /collect забирает накопленное (не забывай!).\n"
        "3. /work — быстрые деньги, но кулдаун 30 минут.\n"
        "4. /daily — +250 💎 раз в сутки.\n"
        "5. Развивай станцию от панелей до реактора и побеждай в /top.\n\n"
        "Удачи, командир! 🚀"
    )
    if uid and uid in ADMIN_IDS:
        text += f"\n\n{admin.admin_panel_text()}"
    await message.answer(text, reply_markup=main_menu_keyboard(uid))


async def show_balance(message: Message, user_id: int) -> None:
    user = db.get_user(user_id)
    if not user:
        await message.answer("Нажми /start, чтобы начать игру.")
        return
    modules = db.get_modules(user_id)
    await message.answer(
        station_text(user, modules), reply_markup=main_menu_keyboard(user_id)
    )


async def cmd_buy(message: Message) -> None:
    if not message.from_user or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /buy solar (или mine, dock, reactor)")
        return
    module_key = parts[1].strip().lower()
    ok, text = db.buy_module(message.from_user.id, module_key)
    uid = message.from_user.id if message.from_user else None
    await message.answer(text, reply_markup=main_menu_keyboard(uid))


async def show_shop(message: Message) -> None:
    lines = ["🛒 <b>Магазин модулей</b>\n"]
    for m in MODULES.values():
        lines.append(
            f"{m.emoji} <b>{m.name}</b> — {m.price} 💎\n"
            f"   └ {m.description}\n"
            f"   └ Доход: {income_label(m)}\n"
        )
    lines.append("\nНажми кнопку, чтобы купить:")
    await message.answer("\n".join(lines), reply_markup=shop_keyboard())


async def do_collect(message: Message, user_id: int) -> None:
    amount, text = db.collect_income(user_id)
    if amount > 0:
        user = db.get_user(user_id)
        text += f"\n\n💎 Баланс: <b>{user['balance']}</b>"
    await message.answer(text, reply_markup=main_menu_keyboard(user_id))


async def do_work(message: Message, user_id: int) -> None:
    user = db.get_user(user_id)
    if not user:
        await message.answer("Нажми /start.")
        return

    ok, wait = db.can_work(user)
    if not ok:
        await message.answer(
            f"⏳ Экипаж отдыхает. Следующая миссия через {format_time(wait)}.",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    reward = random.randint(WORK_MIN, WORK_MAX)
    db.update_balance(user_id, reward)
    db.mark_work(user_id)

    events = [
        "добыл редкий изотоп",
        "спас грузовой шаттл",
        "нашёл древний артефакт",
        "отразил пиратскую атаку",
    ]
    await message.answer(
        f"🚀 Экспедиция успешна! Ты {random.choice(events)}.\n"
        f"<b>+{reward}</b> 💎\n\n"
        f"💎 Баланс: <b>{db.get_user(user_id)['balance']}</b>",
        reply_markup=main_menu_keyboard(user_id),
    )


async def do_daily(message: Message, user_id: int) -> None:
    user = db.get_user(user_id)
    if not user:
        await message.answer("Нажми /start.")
        return

    ok, wait = db.can_daily(user)
    if not ok:
        await message.answer(
            f"🎁 Ежедневная награда уже получена. Возвращайся через {format_time(wait)}.",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    db.update_balance(user_id, DAILY_BONUS)
    db.mark_daily(user_id)
    await message.answer(
        f"🎁 Суточный бонус федерации: <b>+{DAILY_BONUS}</b> 💎\n\n"
        f"💎 Баланс: <b>{db.get_user(user_id)['balance']}</b>",
        reply_markup=main_menu_keyboard(user_id),
    )


async def show_top(message: Message) -> None:
    leaders = db.get_leaderboard()
    if not leaders:
        await message.answer("Рейтинг пока пуст.")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ командиров галактики</b>\n"]
    for i, row in enumerate(leaders, start=1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{medal} {row['display_name']} — <b>{row['balance']}</b> 💎")

    user = message.from_user
    if user:
        me = db.get_user(user.id)
        if me:
            rank = next(
                (i for i, r in enumerate(leaders, 1) if r["user_id"] == user.id),
                None,
            )
            if rank:
                lines.append(f"\n📍 Ты на {rank} месте")
            else:
                lines.append(f"\n📍 Твой баланс: {me['balance']} 💎")

    uid = message.from_user.id if message.from_user else None
    await message.answer("\n".join(lines), reply_markup=main_menu_keyboard(uid))


async def on_callback(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        return

    user_id = callback.from_user.id
    data = callback.data

    if data in ("balance", "my_station"):
        user = db.get_user(user_id)
        if user:
            modules = db.get_modules(user_id)
            await callback.message.answer(station_text(user, modules))
        await callback.answer()

    elif data == "shop":
        await show_shop(callback.message)
        await callback.answer()

    elif data == "collect":
        amount, text = db.collect_income(user_id)
        if amount > 0:
            user = db.get_user(user_id)
            text += f"\n\n💎 Баланс: <b>{user['balance']}</b>"
        await callback.message.answer(text)
        await callback.answer("Собрано!" if amount else None, show_alert=not bool(amount))

    elif data == "work":
        await do_work(callback.message, user_id)
        await callback.answer()

    elif data == "daily":
        await do_daily(callback.message, user_id)
        await callback.answer()

    elif data == "top":
        await show_top(callback.message)
        await callback.answer()

    elif data.startswith("buy_") or data.startswith("buy:"):
        module_key = data[4:] if data.startswith("buy_") else data.split(":", 1)[1]
        ok, text = db.buy_module(user_id, module_key)
        await callback.message.answer(
            text, reply_markup=main_menu_keyboard(user_id)
        )
        await callback.answer("Куплено!" if ok else "Ошибка", show_alert=not ok)


def create_bot() -> Bot:
    if PROXY_URL:
        session = AiohttpSession(proxy=PROXY_URL)
        logger.info("Прокси: %s", PROXY_URL)
        return Bot(token=BOT_TOKEN, session=session)
    return Bot(token=BOT_TOKEN)


def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(
        lambda m: show_balance(m, m.from_user.id), Command("balance")
    )
    dp.message.register(show_shop, Command("shop"))
    dp.message.register(cmd_buy, Command("buy"))
    dp.message.register(
        lambda m: do_collect(m, m.from_user.id), Command("collect")
    )
    dp.message.register(lambda m: do_work(m, m.from_user.id), Command("work"))
    dp.message.register(lambda m: do_daily(m, m.from_user.id), Command("daily"))
    dp.message.register(show_top, Command("top"))
    dp.callback_query.register(on_callback, F.data)
    return dp


async def main() -> None:
    if not BOT_TOKEN:
        print(
            "Ошибка: задай BOT_TOKEN в файле .env\n"
            "Скопируй .env.example → .env и вставь токен от @BotFather"
        )
        sys.exit(1)

    db.init_db()
    dp = setup_dispatcher()
    retry_delay = 5

    while True:
        bot = create_bot()
        try:
            logger.info("Бот «Галактическая станция» запущен")
            await dp.start_polling(bot)
            break
        except TelegramNetworkError as exc:
            logger.warning(
                "Нет связи с Telegram (%s). Повтор через %s сек...",
                exc,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
        finally:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
