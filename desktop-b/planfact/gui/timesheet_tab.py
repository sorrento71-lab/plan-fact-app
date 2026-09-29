"""Вкладка «Табель» (форма Т-13) — экранная копия веб-версии.

Вид и логика сняты с `frontend/src/Timesheet.js` и разделов 1.9, 2, 6 файла
`ДИЗАЙН_СПЕЦ.md`:

* на каждого сотрудника **две физические строки** — коды явок и часы
  (`Timesheet.js:590-782`), между сотрудниками — строка-разделитель 4px
  без рамок (`Timesheet.js:784-786`);
* месяц делится на две половины: I (1–15) и II (16–конец месяца)
  (`Timesheet.js:238-239`), между ними — узкая колонка-разделитель `#e8e8e8`;
* итоговые колонки `Дни I / Часы I / Дни II / Часы II / Дни всего / Часы всего`
  заполнены только в первой строке сотрудника и выделены жирным;
* под таблицей — легенда кодов и статистика (раздел 6.4).

Данные берутся только через `planfact.core` (никакого FastAPI на этой стороне).
Выгрузка XLSX — долгая операция (до 30 секунд), поэтому выполняется в `QThread`.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem,
                               QTableWidgetSelectionRange, QVBoxLayout, QWidget)

from .. import core
from . import theme, widgets
from .common import AppState, item, setup_table

# --------------------------------------------------------------------------
# Геометрия таблицы (раздел 6.3 спецификации)
# --------------------------------------------------------------------------
COL_NO = 0
COL_NAME = 1                             # в вебе порядок № · Фамилия, инициалы · Таб. №
COL_TAB = 2
PINNED_COLUMNS = 3                      # № · ФИО · Таб. №

TOTAL_LABELS = ['Дни I', 'Часы I', 'Дни II', 'Часы II', 'Дни всего', 'Часы всего']

DAY_COLUMN_WIDTH = 24                   # min-width: 22px в вебе
DIVIDER_COLUMN_WIDTH = 6                # колонка-разделитель между половинами
TOTAL_COLUMN_WIDTH = 58                 # min-width: 40px в вебе
ROW_HEIGHT = 17                         # одна строка сотрудника (кодов либо часов)
SEPARATOR_HEIGHT = 4                    # строка-разделитель между сотрудниками
HEADER_HEIGHT = 34                      # две строки шапки: число дня + день недели

CELL_FONT = theme.FONT['timesheet_cell']          # 9px
HEADER_FONT = theme.FONT['timesheet_header']      # 10px
TABLE_FONT = theme.FONT['timesheet']              # 11px
PAGE_FONT = theme.FONT['base']                    # 12px

EXPORT_TITLE = '📥 Выгрузить табель (XLSX)'

# Роль ячейки-разделителя: у неё в вебе нет рамок (border: none)
NO_BORDER_ROLE = Qt.ItemDataRole.UserRole + 5

LEGEND_ITEMS = [
    ('я', 'явка (часы внизу)'),
    ('О', 'отпуск'),
    ('Б', 'больничный'),
    ('В', 'выходной'),
    ('б/с', 'без содержания'),
    ('Р', 'работа в выходной'),
    ('К', 'командировка'),
    ('ПР', 'простой'),
]
LEGEND_HTML = '&nbsp;&nbsp;'.join(f'<b>{code}</b> — {text}' for code, text in LEGEND_ITEMS)


# --------------------------------------------------------------------------
# Логика ячеек — дословный перенос функций Timesheet.js
# --------------------------------------------------------------------------
def format_hours(hours) -> str:
    """`formatHours()` (Timesheet.js:248-252): 0 и пусто — пусто, целое — без дробей."""
    if not hours:
        return ''
    value = float(hours)
    if value.is_integer():
        return str(int(value))
    return str(round(value, 1))


_CODE_BY_PLAN = {
    'Я': 'я', 'О': 'О', 'Б': 'Б', 'В': 'В', 'ВЫХ': 'В',
    'Б/С': 'б/с', 'Р': 'Р', 'К': 'К', 'ПР': 'ПР',
}


def get_code(day: dict | None) -> str:
    """`getCode()` (Timesheet.js:255-278) — код в первой строке сотрудника."""
    if not day:
        return ''
    if (day.get('fact_hours') or 0) > 0:
        return 'я'
    if day.get('mark') == 'Я':
        return 'я'
    plan_type = (day.get('plan_type') or '').strip().upper()
    return _CODE_BY_PLAN.get(plan_type, '')


def get_hours_display(day: dict | None) -> str:
    """`getHoursDisplay()` (Timesheet.js:281-287) — часы во второй строке."""
    if not day:
        return ''
    hours = day.get('fact_hours') or 0
    return format_hours(hours) if hours > 0 else ''


def has_attendance(day: dict | None) -> bool:
    """`hasAttendance()` (Timesheet.js:290-296) — день идёт в счётчик «Дни»."""
    if not day:
        return False
    if (day.get('fact_hours') or 0) > 0:
        return True
    if day.get('mark') == 'Я':
        return True
    return (day.get('plan_type') or '').strip().upper() == 'Я'


# --------------------------------------------------------------------------
# Оформление ячеек
# --------------------------------------------------------------------------
def _font(size: int, bold: bool = False) -> QFont:
    """Шрифт таблицы табеля: Arial, размеры — в px, как в вебе."""
    font = QFont(theme.TS_PAGE_FONT)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _label_qss(color: str, size: int, *, bold: bool = False) -> str:
    return (f'color: {color}; font-size: {size}px;'
            f' font-weight: {"bold" if bold else "normal"};'
            f' font-family: "{theme.TS_PAGE_FONT}", sans-serif;')


def _panel_qss(name: str, background: str, border: str, radius: int) -> str:
    """Стиль панели строго по objectName: иначе он попал бы и во вложенные QLabel."""
    return (f'#{name} {{ background: {background}; border: 1px solid {border};'
            f' border-radius: {radius}px; }}')


def _hex6(value) -> str | None:
    """Разворачивает 3-значный HEX: `common.qcolor` понимает только 6 знаков."""
    if not isinstance(value, str):
        return value
    text = value.lstrip('#')
    if len(text) == 3:
        return '#' + ''.join(ch * 2 for ch in text)
    return value


def _cell(text='', *, size: int = CELL_FONT, bold: bool = False, bg=None, fg=None,
          center: bool = False, tooltip: str | None = None,
          selectable: bool = True) -> QTableWidgetItem:
    cell = item(text, bg=_hex6(bg), fg=_hex6(fg), center=center, tooltip=tooltip)
    cell.setFont(_font(size, bold))
    if not selectable:                       # строка-разделитель не выделяется
        cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
    return cell


class _TimesheetHeader(QHeaderView):
    """Шапка таблицы табеля: фон `#d9d9d9`, выходные — `#d4edda` (раздел 1.9).

    Стили QSS красят все секции шапки одинаково, а выходные дни должны быть
    зелёными, поэтому секции рисуются вручную: фон берётся из
    `Qt.BackgroundRole`, рамка — `#999`, текст — из `FontRole`/`DisplayRole`.
    """

    def __init__(self, orientation: Qt.Orientation,
                 parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self.setFont(_font(HEADER_FONT))
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setStretchLastSection(False)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setMinimumSectionSize(1)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)

    def paintSection(self, painter, rect, logicalIndex) -> None:    # noqa: N802 — имя из Qt
        model = self.model()
        orientation = self.orientation()
        background = _brush_color(model.headerData(
            logicalIndex, orientation, Qt.ItemDataRole.BackgroundRole))

        painter.save()
        painter.fillRect(rect, background or QColor(theme.TS_HEADER_BG))
        pen = QPen(QColor(theme.TS_CELL_BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        edge = rect.adjusted(0, 0, -1, -1)
        painter.drawLine(edge.bottomLeft(), edge.bottomRight())
        painter.drawLine(edge.topRight(), edge.bottomRight())

        text = model.headerData(logicalIndex, orientation, Qt.ItemDataRole.DisplayRole)
        if text:
            font = model.headerData(logicalIndex, orientation, Qt.ItemDataRole.FontRole)
            painter.setFont(font if isinstance(font, QFont) else self.font())
            painter.setPen(QColor('#000'))
            alignment = model.headerData(logicalIndex, orientation,
                                         Qt.ItemDataRole.TextAlignmentRole)
            flags = int(alignment) if alignment is not None else int(Qt.AlignmentFlag.AlignCenter)
            painter.drawText(rect.adjusted(1, 1, -1, -1), flags, str(text))
        painter.restore()


def _brush_color(value) -> QColor | None:
    if isinstance(value, QBrush) and value.style() != Qt.BrushStyle.NoBrush:
        return value.color()
    return None


class _TimesheetGridDelegate(QStyledItemDelegate):
    """Сетка ячеек `#999`, нарисованная вручную.

    В веб-версии у строки-разделителя между сотрудниками рамок нет
    (`Timesheet.js:785` — `border: none`), а штатная сетка QTableWidget
    нарисовала бы рамку и вокруг неё.
    """

    def paint(self, painter, option, index) -> None:        # noqa: N802 — имя из Qt
        super().paint(painter, option, index)
        if index.data(NO_BORDER_ROLE):
            return
        painter.save()
        pen = QPen(QColor(theme.TS_CELL_BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        rect = option.rect
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()


class TimesheetExportWorker(QThread):
    """Сборка xlsx в фоне: выгрузка табеля может занимать до 30 секунд."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, year: int, month: int, sort_field: str,
                 sort_direction: str) -> None:
        super().__init__()
        self._year = year
        self._month = month
        self._sort_field = sort_field
        self._sort_direction = sort_direction

    def run(self) -> None:                                  # noqa: D102 — метод Qt
        try:
            result = core.export_timesheet(
                self._year, self._month,
                sort_field=self._sort_field, sort_direction=self._sort_direction,
            )
        except Exception as exc:                            # noqa: BLE001
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.done.emit(result)


class TimesheetTab(QWidget):
    """Вкладка «📋 Табель»: таблица Т-13, строка действий, легенда, статистика."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state

        # Сортировка — как в вебе: поле и направление (Timesheet.js:14-15)
        self.sort_field = 'employee_name'
        self.sort_direction = 'asc'

        self._data: dict = {}
        self._employees: list[dict] = []
        self._days: list[dict] = []
        self._half1: list[dict] = []
        self._half2: list[dict] = []
        self._row_owner: dict[int, int] = {}       # строка таблицы → номер сотрудника
        self._col_divider = 0
        self._col_totals = 0
        self._worker: TimesheetExportWorker | None = None
        self._selecting = False
        self._message_seq = 0

        self._build_ui()
        self._sync_sort_buttons()
        self._rebuild()                            # шапка видна ещё до загрузки данных

        # Qt нельзя уничтожать вместе с окном, пока поток выгрузки жив
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._stop_worker)

    # ------------------------------------------------------------------
    # построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Вся вкладка — Arial 12px (Timesheet.js:315-316 переопределяет шрифт body)
        font = QFont(theme.TS_PAGE_FONT)
        font.setPixelSize(PAGE_FONT)
        self.setFont(font)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.PAGE_BG))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)     # padding: 10px
        root.setSpacing(8)

        self.message = widgets.MessageBar(self)     # полоса сообщений вкладки
        root.addWidget(self.message)
        root.addWidget(self._build_action_row())
        root.addWidget(self._build_table(), 1)
        root.addWidget(self._build_legend())
        root.addWidget(self._build_stats())

    def _build_action_row(self) -> QWidget:
        """Строка действий: назад · сортировка · выгрузка · обновление (раздел 6.2)."""
        panel = QFrame(self)
        panel.setObjectName('tsActionRow')
        panel.setStyleSheet(
            _panel_qss('tsActionRow', theme.ACTION_ROW_BG,
                       theme.ACTION_ROW_BORDER, 6))
        row = QHBoxLayout(panel)
        row.setContentsMargins(10, 4, 10, 4)        # padding: 4px 10px
        row.setSpacing(12)                          # gap: 6px 12px

        self.back_button = theme.make_button(panel, '◀ Назад', theme.BUTTON_COLORS['back'])
        self.back_button.setToolTip('Вернуться на вкладку «План-Факт»')
        self.back_button.clicked.connect(lambda: self.state.open_tab('planfact'))
        row.addWidget(self.back_button)
        row.addWidget(widgets.separator(panel))

        self.sort_name_button = theme.make_neutral_button(panel, 'ФИО ↕', active=True)
        self.sort_name_button.setToolTip('Сортировка по ФИО')
        self.sort_name_button.clicked.connect(lambda: self._toggle_sort('employee_name'))
        row.addWidget(self.sort_name_button)

        self.sort_tab_button = theme.make_neutral_button(panel, 'Таб. № ↕')
        self.sort_tab_button.setToolTip('Сортировка по табельному номеру')
        self.sort_tab_button.clicked.connect(lambda: self._toggle_sort('tab_number'))
        row.addWidget(self.sort_tab_button)
        row.addWidget(widgets.separator(panel))

        self.export_button = theme.make_button(
            panel, EXPORT_TITLE, theme.BUTTON_COLORS['export_timesheet'])
        self.export_button.setToolTip('Выгрузить табель в формате XLSX')
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)

        self.refresh_button = theme.make_button(
            panel, '🔄 Обновить данные', theme.BUTTON_COLORS['refresh'])
        self.refresh_button.setToolTip('Перечитать табель за выбранный месяц')
        self.refresh_button.clicked.connect(self.load)
        row.addWidget(self.refresh_button)

        row.addStretch(1)
        self.period_hint = QLabel('', panel)
        self.period_hint.setTextFormat(Qt.TextFormat.RichText)
        self.period_hint.setStyleSheet(_label_qss(theme.TEXT_HINT, theme.FONT['hint']))
        row.addWidget(self.period_hint)
        return panel

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(self)
        setup_table(self.table, font_size=TABLE_FONT, row_height=ROW_HEIGHT,
                    grid_color=theme.TS_CELL_BORDER)
        self.table.setShowGrid(False)               # сетку рисует делегат выше
        self.table.setItemDelegate(_TimesheetGridDelegate(self.table))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setStyleSheet(
            f'QTableWidget {{ background: white; border: 1px solid #ccc;'
            f' border-radius: 4px; font-family: "{theme.TS_PAGE_FONT}";'
            f' font-size: {TABLE_FONT}px; }}'
            f'QTableWidget::item:selected {{ background: {theme.PF_SELECTED_BG};'
            f' color: #333; }}'
        )

        # шапку рисует _TimesheetHeader: QSS не умеет красить секции по одной
        header = _TimesheetHeader(Qt.Orientation.Horizontal, self.table)
        self.table.setHorizontalHeader(header)
        header.setFixedHeight(HEADER_HEIGHT)
        # полоса шапки до правого края таблицы: колонки уже вьюпорта
        header.setStyleSheet(f'background: {theme.TS_HEADER_BG};')
        header.sectionClicked.connect(self._on_header_clicked)
        self.table.verticalHeader().setMinimumSectionSize(1)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        return self.table

    def _build_legend(self) -> QWidget:
        """Легенда кодов под таблицей (раздел 6.4, Timesheet.js:795-819)."""
        panel = QFrame(self)
        panel.setObjectName('tsLegend')
        panel.setStyleSheet(_panel_qss('tsLegend', theme.TS_LEGEND_BG,
                                       theme.TS_LEGEND_BORDER, 4))
        row = QHBoxLayout(panel)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(12)

        title = QLabel('📋 Коды:', panel)
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(_label_qss('#333', TABLE_FONT, bold=True))
        row.addWidget(title)

        codes = QLabel(LEGEND_HTML, panel)
        codes.setTextFormat(Qt.TextFormat.RichText)
        codes.setStyleSheet(_label_qss('#333', TABLE_FONT))
        row.addWidget(codes)

        chip = QLabel('', panel)
        chip.setObjectName('tsLegendChip')
        chip.setFixedSize(22, 14)
        chip.setStyleSheet(f'#tsLegendChip {{ background: {theme.TS_WEEKEND_BG};'
                           f' border-radius: 2px; }}')
        row.addWidget(chip)

        caption = QLabel('— выходной день', panel)
        caption.setStyleSheet(_label_qss('#333', TABLE_FONT))
        row.addWidget(caption)
        row.addStretch(1)
        return panel

    def _build_stats(self) -> QWidget:
        """Статистика под таблицей (раздел 6.4, Timesheet.js:822-835)."""
        holder = QWidget(self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        self._stat_labels: list[QLabel] = []
        for _ in range(5):
            label = QLabel('', holder)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setStyleSheet(_label_qss(theme.TEXT_MUTED, TABLE_FONT))
            row.addWidget(label)
            self._stat_labels.append(label)
        row.addStretch(1)
        return holder

    # ------------------------------------------------------------------
    # данные
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Загрузить табель за текущий период (год/месяц — из общего состояния)."""
        self._hide_message()
        try:
            data = core.load_timesheet(self.state.year, self.state.month)
        except Exception as exc:                    # noqa: BLE001 — вкладка не падает
            message = f'❌ Ошибка: {exc}'
            self.message.show_message(message)
            self.state.say(message, 3000)
            return

        self._data = data or {}
        self._employees = list(self._data.get('employees') or [])
        self._rebuild()
        if self._employees:
            self.state.say(f'✅ Табель загружен: {len(self._employees)} сотрудников', 3000)
        else:
            self.message.show_message('Нет данных для отображения табеля')

    def _month_days(self) -> list[dict]:
        """Все дни периода: число, день недели и признак выходного."""
        period = self._data.get('period') or {}
        first = _parse_iso(period.get('from')) or date(self.state.year, self.state.month, 1)
        last = _parse_iso(period.get('to')) or core.month_period(self.state.year, self.state.month)[1]

        days: list[dict] = []
        current = first
        while current <= last:
            days.append({
                'date': current,
                'iso': current.isoformat(),
                'day': current.day,
                'weekday': core.WEEKDAY_SHORT[current.weekday()],
                'weekend': current.weekday() >= 5,     # Сб и Вс (Timesheet.js:188-191)
            })
            current += timedelta(days=1)
        return days

    def _sorted_employees(self) -> list[dict]:
        """Сортировка как в вебе: по строке в нижнем регистре (Timesheet.js:221-227)."""
        def key(employee: dict) -> str:
            return str(employee.get(self.sort_field) or '').lower()

        return sorted(self._employees, key=key, reverse=self.sort_direction == 'desc')

    @staticmethod
    def _day_tooltip(day: dict | None) -> str | None:
        if not day:
            return None
        parts = []
        if day.get('plan_type'):
            parts.append(f"План: {day['plan_type']}")
        hours = day.get('fact_hours') or 0
        if hours > 0:
            parts.append(f'Факт: {format_hours(hours)} ч')
        if day.get('mark'):
            parts.append(f"Отметка: {day['mark']}")
        if not parts:
            return None
        return f"{day.get('date', '')} · " + ' · '.join(parts)

    # ------------------------------------------------------------------
    # сборка таблицы
    # ------------------------------------------------------------------
    def _rebuild(self) -> None:
        """Перерисовать таблицу: шапка, две строки на сотрудника, разделители."""
        self._days = self._month_days()
        self._half1 = [d for d in self._days if d['day'] <= 15]
        self._half2 = [d for d in self._days if d['day'] > 15]
        self._col_divider = PINNED_COLUMNS + len(self._half1)
        self._col_totals = self._col_divider + 1 + len(self._half2)
        columns = self._col_totals + len(TOTAL_LABELS)

        employees = self._sorted_employees()

        self.table.clear()                          # сбрасывает ячейки, шапку и объединения
        self.table.setColumnCount(columns)
        self.table.setRowCount(len(employees) * 3)
        self._row_owner = {}

        self._set_headers()
        self._set_column_widths()
        self._fill_rows(employees, columns)
        self._update_hint()
        self._update_stats()

    def _day_columns(self) -> list[tuple[int, dict]]:
        """Пары (номер колонки, день месяца) по обеим половинам, слева направо."""
        columns = [(PINNED_COLUMNS + i, day) for i, day in enumerate(self._half1)]
        columns += [(self._col_divider + 1 + i, day) for i, day in enumerate(self._half2)]
        return columns

    def _set_headers(self) -> None:
        """Шапка: фон #d9d9d9, выходные — #d4edda, числа дней с днём недели."""
        pinned = [('№', Qt.AlignmentFlag.AlignCenter),
                  ('Фамилия, инициалы', Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                  ('Таб. №', Qt.AlignmentFlag.AlignCenter)]

        backgrounds = {col: theme.TS_WEEKEND_BG if day['weekend'] else theme.TS_HEADER_BG
                       for col, day in self._day_columns()}

        for col, (text, align) in enumerate(pinned):
            cell = QTableWidgetItem(text)
            cell.setFont(_font(HEADER_FONT))
            cell.setBackground(QColor(theme.TS_HEADER_BG))
            cell.setTextAlignment(align)
            self.table.setHorizontalHeaderItem(col, cell)

        for col, day in self._day_columns():
            cell = QTableWidgetItem(f"{day['day']}\n{day['weekday']}")
            cell.setFont(_font(CELL_FONT))          # числа дней — 9px
            cell.setBackground(QColor(backgrounds[col]))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setToolTip(f"{day['iso']} ({day['weekday']})")
            self.table.setHorizontalHeaderItem(col, cell)

        divider = QTableWidgetItem('')
        divider.setBackground(QColor(theme.TS_HEADER_BG))
        self.table.setHorizontalHeaderItem(self._col_divider, divider)

        for i, label in enumerate(TOTAL_LABELS):
            cell = QTableWidgetItem(label)
            cell.setFont(_font(CELL_FONT))
            cell.setBackground(QColor(theme.TS_HEADER_BG))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setHorizontalHeaderItem(self._col_totals + i, cell)

    def _set_column_widths(self) -> None:
        self.table.setColumnWidth(COL_NO, 30)
        self.table.setColumnWidth(COL_TAB, 70)
        self.table.setColumnWidth(COL_NAME, 200)
        for col, _day in self._day_columns():
            self.table.setColumnWidth(col, DAY_COLUMN_WIDTH)
        self.table.setColumnWidth(self._col_divider, DIVIDER_COLUMN_WIDTH)
        for i in range(len(TOTAL_LABELS)):
            self.table.setColumnWidth(self._col_totals + i, TOTAL_COLUMN_WIDTH)

    def _fill_rows(self, employees: list[dict], columns: int) -> None:
        day_columns = self._day_columns()

        for index, employee in enumerate(employees):
            row = index * 3
            self._row_owner[row] = index
            self._row_owner[row + 1] = index

            day_map = {d.get('date'): d for d in employee.get('days') or []}
            days = [day_map.get(day['iso']) for _col, day in day_columns]
            codes = [get_code(day) for day in days]
            hours = [get_hours_display(day) for day in days]

            half1 = days[:len(self._half1)]
            half2 = days[len(self._half1):]
            days1 = sum(1 for day in half1 if has_attendance(day))
            days2 = sum(1 for day in half2 if has_attendance(day))
            hours1 = sum((day or {}).get('fact_hours') or 0 for day in half1)
            hours2 = sum((day or {}).get('fact_hours') or 0 for day in half2)
            totals = [days1, format_hours(hours1), days2, format_hours(hours2),
                      days1 + days2, format_hours(hours1 + hours2)]

            # Строка 1: коды явок
            self.table.setItem(row, COL_NO, _cell(index + 1, center=True))
            self.table.setItem(row, COL_TAB, _cell(employee.get('tab_number') or '',
                                                   center=True))
            self.table.setItem(row, COL_NAME, _cell(employee.get('employee_name') or ''))
            for (col, day), code in zip(day_columns, codes):
                self.table.setItem(row, col, _cell(
                    code,
                    bg=theme.TS_WEEKEND_BG if day['weekend'] else None,
                    center=True,
                    tooltip=self._day_tooltip(day_map.get(day['iso'])),
                ))
            self.table.setItem(row, self._col_divider, _cell(bg=theme.TS_DIVIDER_BG))
            for i, value in enumerate(totals):
                self.table.setItem(row, self._col_totals + i,
                                   _cell(value, bold=True, center=True))

            # Строка 2: часы (первые три колонки и итоги пустые)
            for col in range(PINNED_COLUMNS):
                self.table.setItem(row + 1, col, _cell())
            for (col, day), value in zip(day_columns, hours):
                self.table.setItem(row + 1, col, _cell(
                    value,
                    bg=theme.TS_WEEKEND_BG if day['weekend'] else None,
                    fg=theme.TS_HOURS_TEXT if value else theme.TS_HOURS_EMPTY,
                    center=True,
                    tooltip=self._day_tooltip(day_map.get(day['iso'])),
                ))
            self.table.setItem(row + 1, self._col_divider, _cell(bg=theme.TS_DIVIDER_BG))
            for i in range(len(TOTAL_LABELS)):
                self.table.setItem(row + 1, self._col_totals + i, _cell())

            # Разделитель между сотрудниками: 4px, без рамок
            separator = _cell(selectable=False)
            separator.setData(NO_BORDER_ROLE, True)
            self.table.setItem(row + 2, 0, separator)
            self.table.setSpan(row + 2, 0, 1, columns)
            self.table.setRowHeight(row + 2, SEPARATOR_HEIGHT)

    def _update_hint(self) -> None:
        month_name = core.MONTH_NAMES[self.state.month - 1]
        self.period_hint.setText(
            f'{month_name} {self.state.year} · Сотрудников: '
            f'<b>{len(self._employees)}</b>'
        )

    def _update_stats(self) -> None:
        hours_total = sum(
            (day.get('fact_hours') or 0)
            for employee in self._employees
            for day in employee.get('days') or []
        )
        texts = [
            f'👥 Сотрудников: <b>{len(self._employees)}</b>',
            f'📅 Дней: <b>{len(self._days)}</b>',
            f'📅 I половина: <b>{len(self._half1)} дней</b>',
            f'📅 II половина: <b>{len(self._half2)} дней</b>',
            f'🕒 Часов всего: <b>{format_hours(hours_total) or "0"}</b>',
        ]
        for label, text in zip(self._stat_labels, texts):
            label.setText(text)

    # ------------------------------------------------------------------
    # сортировка и выделение
    # ------------------------------------------------------------------
    def _toggle_sort(self, field: str) -> None:
        """Первый клик — по возрастанию, повторный — по убыванию (Timesheet.js:212-219)."""
        if field == self.sort_field:
            self.sort_direction = 'desc' if self.sort_direction == 'asc' else 'asc'
        else:
            self.sort_field = field
            self.sort_direction = 'asc'
        self._sync_sort_buttons()
        self._rebuild()

    def _sync_sort_buttons(self) -> None:
        for button, field in ((self.sort_name_button, 'employee_name'),
                              (self.sort_tab_button, 'tab_number')):
            active = self.sort_field == field
            if active:
                mark = '↑' if self.sort_direction == 'asc' else '↓'
            else:
                mark = '↕'
            title = f'{"ФИО" if field == "employee_name" else "Таб. №"} {mark}'
            button.setText(title)
            if active:
                theme.style_button(button, theme.BUTTON_ACTIVE_BG)
            else:
                theme.style_button(button, theme.BUTTON_NEUTRAL_BG,
                                   text=theme.BUTTON_NEUTRAL_TEXT, bold=False)

    def _on_header_clicked(self, section: int) -> None:
        """Клик по шапке «ФИО» / «Таб. №» — та же сортировка, что кнопками."""
        if section == COL_NAME:
            self._toggle_sort('employee_name')
        elif section == COL_TAB:
            self._toggle_sort('tab_number')

    def _on_selection_changed(self) -> None:
        """Клик по строке выделяет сотрудника целиком — обе его строки."""
        if self._selecting:
            return
        employee = self._row_owner.get(self.table.currentRow())
        if employee is None:
            return
        rows = [row for row, owner in self._row_owner.items() if owner == employee]
        self._selecting = True
        try:
            self.table.clearSelection()
            for row in rows:
                self.table.setRangeSelected(
                    QTableWidgetSelectionRange(row, 0, row, self.table.columnCount() - 1),
                    True,
                )
        finally:
            self._selecting = False

    # ------------------------------------------------------------------
    # выгрузка XLSX (в фоне — сборка занимает до 30 секунд)
    # ------------------------------------------------------------------
    def _export(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_export_busy(True)
        self._show_message('⏳ Выгрузка табеля...')

        worker = TimesheetExportWorker(self.state.year, self.state.month,
                                       self.sort_field, self.sort_direction)
        worker.done.connect(self._export_done)
        worker.failed.connect(self._export_failed)
        self._worker = worker
        worker.start()

    def _export_done(self, result) -> None:
        self._set_export_busy(False)
        filename = getattr(result, 'filename', '') or 'Табель.xlsx'
        suggested = os.path.join(os.path.expanduser('~'), 'Downloads', filename)
        path, _selected = QFileDialog.getSaveFileName(
            self, 'Сохранить табель', suggested, 'Excel (*.xlsx)')
        if not path:
            self._hide_message()
            self.state.say('Сохранение отменено', 3000)
            return
        try:
            saved = result.save(path)
        except OSError as exc:
            message = f'❌ Ошибка: {exc}'
            self._show_message(message)
            self.state.say(message, 3000)
            return
        self._show_message('✅ Табель выгружен', timeout_ms=3000)
        self.state.say(f'✅ Табель выгружен: {saved}', 3000)

    def _export_failed(self, message: str) -> None:
        self._set_export_busy(False)
        text = f'❌ Ошибка: {message}'
        self._show_message(text)
        self.state.say(text, 3000)

    def _set_export_busy(self, busy: bool) -> None:
        self.export_button.setEnabled(not busy)
        self.export_button.setText('⏳...' if busy else EXPORT_TITLE)

    def _stop_worker(self) -> None:
        """Дождаться фоновой выгрузки при выходе: иначе Qt убьёт живой QThread."""
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        worker.wait(5000)
        if worker.isRunning():
            worker.terminate()
            worker.wait(1000)

    # ------------------------------------------------------------------
    # полоса сообщений вкладки
    # ------------------------------------------------------------------
    def _show_message(self, text: str, timeout_ms: int | None = None) -> None:
        self._message_seq += 1
        seq = self._message_seq
        self.message.show_message(text)
        if timeout_ms:
            QTimer.singleShot(timeout_ms, lambda: self._hide_message(seq))

    def _hide_message(self, seq: int | None = None) -> None:
        if seq is not None and seq != self._message_seq:
            return                                   # сообщение уже сменилось
        self._message_seq += 1
        self.message.clear_message()


def _parse_iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ['TimesheetTab', 'TimesheetExportWorker', 'format_hours', 'get_code',
           'get_hours_display', 'has_attendance']
