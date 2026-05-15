from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleInfo:
    key: str
    name: str
    emoji: str
    price: int
    income_per_hour: int = 0
    description: str = ""


def income_label(module: ModuleInfo) -> str:
    return f"{module.income_per_hour} 💎/час"


def module_rate(module: ModuleInfo, quantity: int) -> tuple[int, str]:
    return module.income_per_hour * quantity, "час"


def calc_pending_income(elapsed_seconds: float, modules: dict[str, int]) -> int:
    if elapsed_seconds <= 0:
        return 0
    hours = elapsed_seconds / 3600
    total = 0.0
    for key, qty in modules.items():
        m = MODULES.get(key)
        if not m:
            continue
        total += m.income_per_hour * qty * hours
    return int(total)


MODULES: dict[str, ModuleInfo] = {
    "solar": ModuleInfo(
        key="solar",
        name="Солнечная панель",
        emoji="☀️",
        price=200,
        income_per_hour=8,
        description="Базовая энергия для станции",
    ),
    "mine": ModuleInfo(
        key="mine",
        name="Астероидная шахта",
        emoji="⛏️",
        price=900,
        income_per_hour=35,
        description="Добывает редкие металлы",
    ),
    "dock": ModuleInfo(
        key="dock",
        name="Торговый док",
        emoji="🛸",
        price=3500,
        income_per_hour=120,
        description="Торговля с кораблями флота",
    ),
    "reactor": ModuleInfo(
        key="reactor",
        name="Термоядерный реактор",
        emoji="⚛️",
        price=12000,
        income_per_hour=500,
        description="Мощный источник энергии",
    ),
}

WORK_MIN = 40
WORK_MAX = 120
