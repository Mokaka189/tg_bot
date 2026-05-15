from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database as db
from config import ADMIN_IDS
from game import MODULES

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_panel_text() -> str:
    return (
        "🛡 <b>Режим администратора</b>\n\n"
        "<b>Пользователи</b>\n"
        "/users — все игроки (ник, @username, id)\n"
        "/user &lt;id&gt; — профиль и станции\n\n"
        "<b>Деньги</b>\n"
        "/addmoney &lt;id&gt; &lt;сумма&gt; — выдать\n"
        "/takemoney &lt;id&gt; &lt;сумма&gt; — забрать\n\n"
        "<b>Станции</b> (у каждой свой #id)\n"
        "/addstation &lt;id_игрока&gt; &lt;тип&gt;\n"
        "/delstation &lt;id_станции&gt;\n"
        "/allstations — все станции\n\n"
        "Типы: solar, mine, dock, reactor"
    )


def admin_keyboard_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text="👥 Игроки", callback_data="admin_users"),
            InlineKeyboardButton(text="🛰 Станции", callback_data="admin_stations"),
        ],
        [
            InlineKeyboardButton(text="🛡 Админ-справка", callback_data="admin_help"),
        ],
    ]


async def deny(message: Message) -> None:
    await message.answer("⛔ Команда только для администратора.")


def format_user_line(u: dict) -> str:
    nick = u.get("username")
    uname = f"@{nick}" if nick else "—"
    return (
        f"👤 <b>{u['display_name']}</b>\n"
        f"   id: <code>{u['user_id']}</code> | {uname}\n"
        f"   💎 {u['balance']}"
    )


def format_station_line(s: dict) -> str:
    m = MODULES.get(s["module_key"])
    if m:
        label = f"{m.emoji} {m.name}"
    else:
        label = s["module_key"]
    owner = s.get("display_name") or s["user_id"]
    return f"#{s['id']} {label} — user <code>{s['user_id']}</code> ({owner})"


async def send_users_list(message: Message) -> None:
    users = db.get_all_users()
    if not users:
        await message.answer("Пользователей нет.")
        return

    lines = [f"📋 <b>Игроки ({len(users)})</b>\n"]
    for u in users:
        lines.append(format_user_line(u))
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await message.answer(text)


async def send_all_stations(message: Message) -> None:
    stations = db.list_stations()
    if not stations:
        await message.answer("Станций нет.")
        return

    lines = [f"🛰 <b>Все станции ({len(stations)})</b>\n"]
    for s in stations:
        lines.append(format_station_line(s))

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await message.answer(text)


@router.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await send_users_list(callback.message)
    await callback.answer()


@router.callback_query(F.data == "admin_stations")
async def cb_admin_stations(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await send_all_stations(callback.message)
    await callback.answer()


@router.callback_query(F.data == "admin_help")
async def cb_admin_help(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer(admin_panel_text())
    await callback.answer()


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return
    await message.answer(admin_panel_text())


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return
    await send_users_list(message)


@router.message(Command("user"))
async def cmd_user(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /user &lt;chat_id&gt;")
        return

    uid = int(parts[1])
    user = db.get_user(uid)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    stations = db.list_stations(uid)
    lines = [
        "🔍 <b>Профиль</b>\n",
        format_user_line(user),
        "",
        f"<b>Станции ({len(stations)}):</b>",
    ]
    if stations:
        for s in stations:
            m = MODULES.get(s["module_key"])
            label = f"{m.emoji} {m.name}" if m else s["module_key"]
            lines.append(f"  #{s['id']} — {label}")
    else:
        lines.append("  нет")

    await message.answer("\n".join(lines))


@router.message(Command("addmoney"))
async def cmd_addmoney(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        await message.answer("Использование: /addmoney &lt;id&gt; &lt;сумма&gt;")
        return

    uid, amount = int(parts[1]), int(parts[2])
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    user = db.get_user(uid)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    new_bal = db.update_balance(uid, amount)
    await message.answer(
        f"✅ +{amount} 💎 игроку <code>{uid}</code>\nНовый баланс: <b>{new_bal}</b>"
    )


@router.message(Command("takemoney"))
async def cmd_takemoney(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        await message.answer("Использование: /takemoney &lt;id&gt; &lt;сумма&gt;")
        return

    uid, amount = int(parts[1]), int(parts[2])
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    user = db.get_user(uid)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    new_bal = db.update_balance(uid, -amount)
    if new_bal < 0:
        db.set_balance(uid, 0)
        new_bal = 0

    await message.answer(
        f"✅ −{amount} 💎 у игрока <code>{uid}</code>\nНовый баланс: <b>{new_bal}</b>"
    )


@router.message(Command("addstation", "addstancion"))
async def cmd_addstation(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Использование: /addstation &lt;id_игрока&gt; &lt;тип&gt;\n"
            "Пример: /addstation 6924900203 solar"
        )
        return

    uid = int(parts[1])
    module_key = parts[2].lower()
    ok, text, _ = db.add_station(uid, module_key)
    await message.answer(text)


@router.message(Command("delstation", "delstancion"))
async def cmd_delstation(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /delstation &lt;id_станции&gt;\nПример: /delstation 3")
        return

    station_id = int(parts[1])
    ok, text = db.remove_station(station_id)
    await message.answer(text)


@router.message(Command("allstations"))
async def cmd_allstations(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await deny(message)
        return
    await send_all_stations(message)
