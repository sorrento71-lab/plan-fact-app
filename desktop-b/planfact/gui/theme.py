"""Палитра, шрифты и стили прототипа Б — снято с исходников веб-версии.

Все значения взяты из `ДИЗАЙН_СПЕЦ.md` (а тот — из `frontend/src`), ничего
не придумано. Задача файла: чтобы цвета и размеры были в одном месте и
вкладки не расходились между собой.
"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

# --------------------------------------------------------------------------
# Шрифты (ДИЗАЙН_СПЕЦ.md, раздел 2)
# В вебе базовый шрифт — Roboto с фолбэком на системный; на Windows ближайший
# системный — Segoe UI. Моноширинный в вебе не используется нигде.
# --------------------------------------------------------------------------
FONT_FAMILY = 'Segoe UI'

FONT = {
    'base': 12,
    'tab': 12,
    'button': 11,
    'month': 13,
    'month_label': 11,
    'month_counter': 10,
    'message': 11,
    'legend': 9,
    'legend_chip': 8,
    'hint': 10,
    # таблица план-факта: 11px при ≤7 днях, 10px при ≤14, иначе 9px
    'planfact_wide': 9,
    'planfact_mid': 10,
    'planfact_narrow': 11,
    'table_header': 9,
    'day_header': 8,
    'subheader': 7,
    'timesheet': 11,
    'timesheet_header': 10,
    'timesheet_cell': 9,
    'schedule': 10,
    'meal_title': 20,
    'meal_label': 15,
    'meal_button': 16,
    'meal_row': 16,
}

# --------------------------------------------------------------------------
# Каркас (раздел 1.1)
# --------------------------------------------------------------------------
BODY_BG = '#f5f7fa'
PAGE_BG = 'white'
HEADER_BG = 'white'
HEADER_BORDER = '#d7dde4'
ACTION_ROW_BG = '#fafbfc'
ACTION_ROW_BORDER = '#dfe4ea'
SEPARATOR = '#d7dde4'
TEXT_MUTED = '#666'
TEXT_HINT = '#888'
TEXT_FAINT = '#999'
TABLE_BORDER = '#ddd'
CELL_BORDER = '#ddd'

# --------------------------------------------------------------------------
# Статусы (раздел 1.3) — палитра из frontend/src/constants.js
# --------------------------------------------------------------------------
STATUS_COLORS = {
    'Совпадает': '#92d050',
    'Неполный день': '#ffff00',
    'Отсутствует': '#ff6b6b',
    'Неучтенная работа': '#ffa94d',
    'Явка в выходной': '#ffa94d',
    'Выходной': '#add8e6',
    'Нет данных': '#ffffff',
}
STATUS_TEXT = '#333'
STATUS_TEXT_ON_DARK = 'white'          # только для «Отсутствует»
STATUS_DARK_TEXT = {'Отсутствует'}     # статусы, где текст белый


def status_bg(status: str) -> str:
    return STATUS_COLORS.get(status, '#ffffff')


def status_fg(status: str) -> str:
    return STATUS_TEXT_ON_DARK if status in STATUS_DARK_TEXT else STATUS_TEXT


# --------------------------------------------------------------------------
# Вкладки (раздел 1.7)
# --------------------------------------------------------------------------
TABS = [
    ('planfact', '📊 План-Факт', '#1565c0'),
    ('timesheet', '📋 Табель', '#e74c3c'),
    ('meal', '🍽️ Питание', '#9c27b0'),
    ('schedule', '📅 График', '#00838f'),
]
TAB_BAR_BG = '#f0f2f5'
TAB_INACTIVE_TEXT = '#333'

# --------------------------------------------------------------------------
# Таблица план-факта (раздел 1.2, 1.4, 1.5)
# --------------------------------------------------------------------------
PF_HEADER_BG = '#1565c0'
PF_HEADER_TEXT = 'white'
PF_HEADER_BORDER = '#0d47a1'
PF_SUBHEADER_BG = '#e3f2fd'
PF_SUBHEADER_TEXT = '#0d47a1'
PF_SUBHEADER_BORDER = '#90caf9'
PF_SUBHEADER_IN = '#e8f0fe'        # «Приход», «Уход»
PF_SUBHEADER_FACT = '#f5f5f5'      # «Факт»
PF_SUBHEADER_STAGE = '#fce4ec'     # «Этапы»
PF_SUBHEADER_STAGE_TEXT = '#c62828'
PF_SELECTED_BG = '#e3f2fd'
PF_SELECTED_BORDER = '#1565c0'
PF_PLAN_EDITING = '#fff9c4'
PF_IN_BG = '#e8f5e9'               # приход со значением
PF_OUT_BG = '#fff3e0'              # уход со значением
PF_FACT_BG = '#e3f2fd'             # факт > 0
PF_FACT_EMPTY_BG = '#f5f5f5'
PF_STAGE_BG = '#fff9c4'            # этапы со значением
PF_TIME_TEXT = '#1a237e'           # текст времени при правке

# --------------------------------------------------------------------------
# График (раздел 1.8)
# --------------------------------------------------------------------------
SCHEDULE_TEXT = '#222'
SCHEDULE_CELL_BORDER = '#e3e6ea'
SCHEDULE_CELL_BORDER_BOLD = '#9aa3ad'
SCHEDULE_HEADER_BG = '#e9eef4'
SCHEDULE_WEEKEND_DEFAULT = '#73A0B4'
SCHEDULE_STICKY_BG = '#fff'

# Рамки сверки с планом — inset 2px
CMP_BORDER = {
    'diff': '#d32f2f',          # расхождение
    'db_missing': '#ff9800',    # в графике есть, плана нет
    'graf_missing': '#1976d2',  # план есть, в графике пусто
    'no_employee': '#9e9e9e',   # сотрудника нет в базе
}
CMP_HINT = {
    'diff': 'расхождение с планом в БД',
    'db_missing': 'в графике есть, плана в БД нет',
    'graf_missing': 'план есть, в графике пусто',
    'no_employee': 'сотрудника нет в справочнике БД',
}
SCHEDULE_LEGEND = [
    ('Д', 'дежурство', '#FFFF00', None),
    ('О', 'отпуск', '#92D050', None),
    ('Б', 'больничный', '#FF0000', '#fff'),
    ('Б/С', 'б/с', '#FFC000', None),
    ('вых', 'выходной', '#73A0B4', None),
]

# --------------------------------------------------------------------------
# Табель (раздел 1.9)
# --------------------------------------------------------------------------
TS_HEADER_BG = '#d9d9d9'
TS_WEEKEND_BG = '#d4edda'
TS_DIVIDER_BG = '#e8e8e8'
TS_CELL_BORDER = '#999'
TS_HOURS_TEXT = '#000'
TS_HOURS_EMPTY = '#999'
TS_LEGEND_BG = '#f5f5f5'
TS_LEGEND_BORDER = '#ddd'
TS_PAGE_FONT = 'Arial'

# --------------------------------------------------------------------------
# Питание (раздел 1.10)
# --------------------------------------------------------------------------
MEAL_TITLE = '#1565c0'
MEAL_INPUT_BORDER = '#ccc'
MEAL_CARD_BORDER = '#ddd'
MEAL_ROW_SEPARATOR = '#f0f0f0'
MEAL_INDEX_TEXT = '#999'
MEAL_COUNTER_TEXT = '#666'

# --------------------------------------------------------------------------
# Сообщения (раздел 1.11)
# --------------------------------------------------------------------------
MESSAGE_COLORS = {
    'success': ('#d4edda', '#155724'),
    'error': ('#f8d7da', '#721c24'),
    'warning': ('#fff3cd', '#856404'),
}


def message_kind(text: str) -> str:
    """Тип сообщения — по наличию ✅/❌ в строке, как в MessageBar.js:7-8."""
    if '✅' in text:
        return 'success'
    if '❌' in text:
        return 'error'
    return 'warning'


# --------------------------------------------------------------------------
# Кнопки (раздел 1.6)
# --------------------------------------------------------------------------
BUTTON_COLORS = {
    'refresh': '#1565c0',
    'upload_journal': '#ff9800',
    'upload_schedule': '#4caf50',
    'week': '#1565c0',
    'export_week': '#1565c0',
    'export_month': '#00695c',
    'delete': '#d32f2f',
    'sheet': '#2e7d32',
    'remove_from_schedule': '#b71c1c',
    'export_actual': '#00695c',
    'export_rhythm': '#5e35b1',
    'shifts': '#0277bd',
    'clear': '#c62828',
    'add_employee': '#2e7d32',
    'back': '#6c757d',
    'export_timesheet': '#e74c3c',
    'meal_show': '#1565c0',
    'meal_morning': '#ff9800',
    'meal_lunch': '#4caf50',
}
BUTTON_NEUTRAL_BG = '#f0f0f0'
BUTTON_NEUTRAL_BG_ALT = '#6c757d'
BUTTON_NEUTRAL_TEXT = '#333'
BUTTON_ACTIVE_BG = '#1565c0'
BUTTON_DISABLED_BG = '#ccc'
BUTTON_TEXT = '#fff'
BUTTON_BORDER = '#ccc'


def button_qss(background: str, *, text: str = BUTTON_TEXT, bold: bool = True,
               border: str | None = None, font_size: int | None = None,
               padding: str = '4px 10px') -> str:
    """Стиль кнопки: в вебе это просто цветной прямоугольник без рамки."""
    size = font_size or FONT['button']
    border_rule = f'border: {border};' if border else 'border: none;'
    return (
        f'QPushButton {{ background: {background}; color: {text};'
        f' font-size: {size}px; font-weight: {"bold" if bold else "normal"};'
        f' {border_rule} border-radius: 4px; padding: {padding};'
        f' white-space: nowrap; }}'
        f'QPushButton:hover {{ background: {background}; }}'
        f'QPushButton:disabled {{ background: {BUTTON_DISABLED_BG}; color: #777; }}'
    )


def style_button(button: QPushButton, background: str, *, text: str = BUTTON_TEXT,
                 bold: bool = True, border: str | None = None,
                 font_size: int | None = None, padding: str = '4px 10px') -> QPushButton:
    button.setStyleSheet(button_qss(background, text=text, bold=bold, border=border,
                                    font_size=font_size, padding=padding))
    button.setCursor(button.cursor())
    return button


def make_button(parent: QWidget, title: str, background: str, *, text: str = BUTTON_TEXT,
                bold: bool = True, border: str | None = None,
                font_size: int | None = None, padding: str = '4px 10px') -> QPushButton:
    button = QPushButton(title, parent)
    style_button(button, background, text=text, bold=bold, border=border,
                 font_size=font_size, padding=padding)
    return button


def make_neutral_button(parent: QWidget, title: str, *, active: bool = False) -> QPushButton:
    """Кнопка недели/сортировки: активная синяя, неактивная серая."""
    if active:
        return make_button(parent, title, BUTTON_ACTIVE_BG)
    return make_button(parent, title, BUTTON_NEUTRAL_BG, text=BUTTON_NEUTRAL_TEXT,
                       bold=False)


def panel_qss(background: str, border: str, radius: int = 6) -> str:
    return (f'background: {background}; border: 1px solid {border};'
            f' border-radius: {radius}px;')


def label_qss(color: str, size: int, *, bold: bool = False) -> str:
    weight = 'bold' if bold else 'normal'
    return (f'color: {color}; font-size: {size}px; font-weight: {weight};'
            f' font-family: "{FONT_FAMILY}";')


def table_font_size(days: int) -> int:
    """Размер шрифта таблицы план-факта по числу дней (App.js:318)."""
    if days <= 7:
        return FONT['planfact_narrow']
    if days <= 14:
        return FONT['planfact_mid']
    return FONT['planfact_wide']
