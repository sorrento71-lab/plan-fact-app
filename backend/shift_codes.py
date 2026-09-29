"""Единые правила кодов смен графика и плана.

До ноября 2026 смена в графике и плане кодировалась длительностью:
«11» (ритм 2 через 2), «9» и «8» (5 через 2), дополнительная смена — «Д».
С 01.11.2026 схема меняется: «Я» — основная смена, «В» — доп смена.

Все зависимости (правка ячеек, импорт плана из графика, перенос плана в
график, расстановка по ритму, очистка, план-факт, табель, медосмотр,
выгрузки) обязаны приводить значения к схеме конкретного месяца через
функции этого модуля, а не сравнивать коды напрямую.
"""
from datetime import date, datetime
from typing import Iterable, Optional

# Месяц, с которого действует новая схема обозначений.
NEW_SCHEME_START = date(2026, 11, 1)

MAIN_CODE = 'Я'    # основная смена
EXTRA_CODE = 'В'   # доп смена

# Коды старой схемы: смена по длительности и дополнительная смена.
LEGACY_MAIN_CODES = ('11', '9', '8')
LEGACY_EXTRA_CODE = 'Д'
LEGACY_EXTRA_ALIASES = ('Д', 'ДЕЖ', 'ДОП', 'ДОП СМЕНА', 'Д.СМЕНА', 'ДЕЖУРСТВО')

# Коды, которые сменой не являются (отпуск, больничный, без содержания, прогул).
NON_SHIFT_CODES = ('О', 'Б', 'Б/С', 'П')

# Часы плана по коду значения. «Я» и «В» — по 11 часов (как «11» и «Д»).
PLAN_HOURS = {
    '11': 11.0,
    '9': 9.0,
    '8': 8.0,
    'Д': 11.0,
    MAIN_CODE: 11.0,
    EXTRA_CODE: 11.0,
}

# Ритмы старой схемы: значение -> (рабочих дней, дней отдыха).
LEGACY_CYCLES = {
    '11': (2, 2),
    '9': (5, 2),
    '8': (5, 2),
}

# Новая схема длительность смены не кодирует: цикл подбирается по рисунку
# месяца среди этих вариантов (первый — при равном счёте).
NEW_SCHEME_CYCLES = ((2, 2), (5, 2))

# Порядок вывода значений в подсказках и выгрузках.
LEGEND_NEW = ((MAIN_CODE, 'основная смена'), (EXTRA_CODE, 'доп смена'))
LEGEND_LEGACY = (
    ('11', '11-часовая смена (2 через 2)'),
    ('9', '9-часовая смена (5 через 2)'),
    ('8', '8-часовая смена (5 через 2)'),
    (LEGACY_EXTRA_CODE, 'доп смена'),
)


def _key(value) -> str:
    """Значение в верхнем регистре без лишних пробелов (для сравнения кодов)."""
    if value is None:
        return ''
    return ' '.join(str(value).split()).strip().upper().replace('Ё', 'Е')


def _as_date(day) -> Optional[date]:
    if day is None:
        return None
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    return None


def uses_new_scheme(day=None) -> bool:
    """True, если для этой даты (месяца) действует схема «Я»/«В»."""
    value = _as_date(day)
    return value is not None and value >= NEW_SCHEME_START


def canonical(value, day=None) -> str:
    """Приводит значение к схеме месяца.

    С ноября 2026 «11», «9», «8» читаются как основная смена «Я»,
    «Д» — как доп смена «В». До ноября значения возвращаются как есть.
    """
    text = '' if value is None else str(value).strip()
    if not text:
        return ''
    if not uses_new_scheme(day):
        return text
    key = _key(text)
    if key in LEGACY_MAIN_CODES or key == MAIN_CODE:
        return MAIN_CODE
    if key in LEGACY_EXTRA_ALIASES or key == EXTRA_CODE:
        return EXTRA_CODE
    return text


def shift_values(day=None) -> tuple:
    """Коды, которые означают «в этот день стоит смена»."""
    return (MAIN_CODE, EXTRA_CODE) if uses_new_scheme(day) else LEGACY_MAIN_CODES


def main_shift_values(day=None) -> tuple:
    """Коды основной смены — те, по которым считается ритм."""
    return (MAIN_CODE,) if uses_new_scheme(day) else LEGACY_MAIN_CODES


def is_shift(value, day=None) -> bool:
    return _key(value) in shift_values(day)


def is_non_shift(value) -> bool:
    """Отпуск/больничный/б/с/прогул — сменой не являются."""
    return _key(value) in NON_SHIFT_CODES


def rhythm_cycles(value, day=None) -> tuple:
    """Варианты ритма (рабочих, отдыха) для значения источника.

    Старая схема: ритм задан кодом (11 — 2 через 2, 9 и 8 — 5 через 2).
    Новая схема: длительность не закодирована, поэтому варианты перебираются
    по фактическому рисунку смен в листе.
    """
    if uses_new_scheme(day):
        return NEW_SCHEME_CYCLES
    cycle = LEGACY_CYCLES.get(_key(value))
    return () if cycle is None else (cycle,)


def plan_hours(value) -> float:
    """Часы плана по коду значения (0 — если код часами не является)."""
    return PLAN_HOURS.get(_key(value), 0.0)


def legend(day=None) -> list:
    """Пояснения к кодам смен для легенды интерфейса и подсказок."""
    source = LEGEND_NEW if uses_new_scheme(day) else LEGEND_LEGACY
    return [{'code': code, 'text': text} for code, text in source]


def describe(day=None) -> str:
    """Короткое перечисление смен месяца — для подписей кнопок и сообщений."""
    return ', '.join(f'{code} — {text}' for code, text in
                     (LEGEND_NEW if uses_new_scheme(day) else LEGEND_LEGACY))


def shift_order(day=None) -> tuple:
    """Порядок значений смен для сортировки в выдаче."""
    return (MAIN_CODE, EXTRA_CODE) if uses_new_scheme(day) else LEGACY_MAIN_CODES


def normalize_many(values: Iterable, day=None) -> list:
    """Приводит список значений к схеме месяца, сохраняя порядок."""
    return [canonical(value, day) for value in values]
