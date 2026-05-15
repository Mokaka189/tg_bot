import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from config import DB_PATH, DAILY_COOLDOWN_SEC, STARTING_BALANCE, WORK_COOLDOWN_SEC
from game import MODULES, calc_pending_income, income_label


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


REMOVED_MODULE_KEYS = ("station", "test_reactor")


def _purge_removed_modules(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"DELETE FROM stations WHERE module_key IN ({','.join('?' * len(REMOVED_MODULE_KEYS))})",
        REMOVED_MODULE_KEYS,
    )
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_modules'"
    ).fetchone():
        conn.execute(
            f"DELETE FROM user_modules WHERE module_key IN ({','.join('?' * len(REMOVED_MODULE_KEYS))})",
            REMOVED_MODULE_KEYS,
        )


def _migrate_modules_to_stations(conn: sqlite3.Connection) -> None:
    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_modules'"
    ).fetchone():
        return

    skip = set(REMOVED_MODULE_KEYS)
    rows = conn.execute(
        "SELECT user_id, module_key, quantity FROM user_modules"
    ).fetchall()
    now = _to_iso(_utcnow())
    for row in rows:
        if row["module_key"] in skip:
            continue
        for _ in range(row["quantity"]):
            conn.execute(
                """
                INSERT INTO stations (user_id, module_key, created_at)
                VALUES (?, ?, ?)
                """,
                (row["user_id"], row["module_key"], now),
            )


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 500,
                last_work TEXT,
                last_daily TEXT,
                last_collect TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                module_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            """
        )
        _migrate_modules_to_stations(conn)
        _purge_removed_modules(conn)
        conn.execute("DROP TABLE IF EXISTS user_modules")


def get_or_create_user(
    user_id: int, username: str | None, display_name: str
) -> dict[str, Any]:
    now = _to_iso(_utcnow())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username = ?, display_name = ? WHERE user_id = ?",
                (username, display_name, user_id),
            )
            return dict(row)

        conn.execute(
            """
            INSERT INTO users (user_id, username, display_name, balance, created_at, last_collect)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, display_name, STARTING_BALANCE, now, now),
        )
        return {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "balance": STARTING_BALANCE,
            "last_work": None,
            "last_daily": None,
            "last_collect": now,
            "created_at": now,
        }


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_all_users() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT user_id, username, display_name, balance, created_at
            FROM users
            ORDER BY user_id
            """
        ).fetchall()
        return [dict(r) for r in rows]


def update_balance(user_id: int, delta: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (delta, user_id),
        )
        row = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(row["balance"])


def set_balance(user_id: int, balance: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (max(0, balance), user_id),
        )


def list_stations(user_id: int | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if user_id is None:
            rows = conn.execute(
                """
                SELECT s.id, s.user_id, s.module_key, s.created_at,
                       u.display_name, u.username
                FROM stations s
                JOIN users u ON u.user_id = s.user_id
                ORDER BY s.id
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, user_id, module_key, created_at
                FROM stations
                WHERE user_id = ?
                ORDER BY id
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_station(station_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT s.id, s.user_id, s.module_key, s.created_at,
                   u.display_name, u.username
            FROM stations s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.id = ?
            """,
            (station_id,),
        ).fetchone()
        return dict(row) if row else None


def get_modules(user_id: int) -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT module_key, COUNT(*) AS quantity
            FROM stations
            WHERE user_id = ?
            GROUP BY module_key
            """,
            (user_id,),
        ).fetchall()
        return {row["module_key"]: row["quantity"] for row in rows}


def add_station(user_id: int, module_key: str) -> tuple[bool, str, int | None]:
    module_key = module_key.lower().strip()
    module = MODULES.get(module_key)
    if not module:
        keys = ", ".join(MODULES.keys())
        return False, f"Неизвестный тип. Доступно: {keys}", None

    user = get_user(user_id)
    if not user:
        return False, "Пользователь не найден. Пусть нажмёт /start.", None

    now = _to_iso(_utcnow())
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO stations (user_id, module_key, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, module_key, now),
        )
        station_id = cur.lastrowid

    return (
        True,
        f"{module.emoji} {module.name} выдана. ID станции: <b>#{station_id}</b>",
        station_id,
    )


def remove_station(station_id: int) -> tuple[bool, str]:
    station = get_station(station_id)
    if not station:
        return False, f"Станция #{station_id} не найдена."

    module = MODULES.get(station["module_key"])
    name = module.name if module else station["module_key"]

    with get_conn() as conn:
        conn.execute("DELETE FROM stations WHERE id = ?", (station_id,))

    return True, f"Станция #{station_id} ({name}) удалена у user_id {station['user_id']}."


def buy_module(user_id: int, module_key: str) -> tuple[bool, str]:
    module_key = module_key.lower().strip()
    module = MODULES.get(module_key)
    if not module:
        return False, f"Неизвестный модуль ({module_key}). Открой /shop заново."

    user = get_user(user_id)
    if not user:
        return False, "Сначала нажми /start."

    if user["balance"] < module.price:
        return False, (
            f"Не хватает кредитов. Нужно {module.price} 💎, у тебя {user['balance']} 💎."
        )

    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (module.price, user_id),
        )

    ok, text, station_id = add_station(user_id, module_key)
    if not ok:
        db_refund = module.price
        update_balance(user_id, db_refund)
        return False, text

    return (
        True,
        f"{module.emoji} {module.name} установлена! ID: <b>#{station_id}</b>\n"
        f"−{module.price} 💎 | Доход: +{income_label(module)}",
    )


def pending_income(user: dict[str, Any], modules: dict[str, int]) -> int:
    if not modules:
        return 0
    last_collect = _from_iso(user.get("last_collect"))
    if not last_collect:
        return 0
    elapsed = (_utcnow() - last_collect).total_seconds()
    return calc_pending_income(elapsed, modules)


def collect_income(user_id: int) -> tuple[int, str]:
    user = get_user(user_id)
    if not user:
        return 0, "Сначала нажми /start."

    modules = get_modules(user_id)
    income = pending_income(user, modules)

    if income <= 0:
        return 0, "Пока нечего собирать. Купи модули в /shop или подожди."

    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = balance + ?, last_collect = ? WHERE user_id = ?",
            (income, _to_iso(_utcnow()), user_id),
        )

    return income, f"Собрано +{income} 💎 с модулей станции!"


def can_work(user: dict[str, Any]) -> tuple[bool, int]:
    last = _from_iso(user.get("last_work"))
    if not last:
        return True, 0
    elapsed = (_utcnow() - last).total_seconds()
    if elapsed >= WORK_COOLDOWN_SEC:
        return True, 0
    return False, int(WORK_COOLDOWN_SEC - elapsed)


def mark_work(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_work = ? WHERE user_id = ?",
            (_to_iso(_utcnow()), user_id),
        )


def can_daily(user: dict[str, Any]) -> tuple[bool, int]:
    last = _from_iso(user.get("last_daily"))
    if not last:
        return True, 0
    elapsed = (_utcnow() - last).total_seconds()
    if elapsed >= DAILY_COOLDOWN_SEC:
        return True, 0
    return False, int(DAILY_COOLDOWN_SEC - elapsed)


def mark_daily(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_daily = ? WHERE user_id = ?",
            (_to_iso(_utcnow()), user_id),
        )


def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT user_id, display_name, balance
            FROM users
            ORDER BY balance DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
