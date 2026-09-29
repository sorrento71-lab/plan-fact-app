"""Вкладка «План-Факт» — матрица план/факт по неделям, как в веб-версии.

Раскладка повторяет `frontend/src/App.js:420-514` и `PlanFactTable.js`:

    [ панель действий: сортировка · недели · выгрузки · удаление · правка ]
    [ № / ФИО / Должность | двухъярусная шапка дней | ячейки дней         ]
    [ легенда статусов                                                    ]

Закрепление колонок. В Qt нет `position: sticky`, поэтому таблица собрана из
четырёх виджетов: угловой блок с заголовками «№ / ФИО / Должность», две
однострочные таблицы-шапки над правой частью (день + подзаголовки
План/Приход/Уход/Факт/Этапы) и две таблицы тела — левая с тремя закреплёнными
колонками и правая (`self.table`) с ячейками дней. Вертикальные прокрутки
левой и правой синхронизированы (у левой полоса скрыта), горизонтальная
прокрутка шапок синхронизирована с правой таблицей.

Отличие от веб-версии — осознанное: правка ячеек включается только
переключателем «✏️ Правка», потому что запись уходит в реальную базу проекта
и в файл графика.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from PySide6.QtCore import QEventLoop, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog,
                               QFrame, QGridLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QStyle,
                               QTableWidget, QVBoxLayout, QWidget)

from .. import core
from . import theme, widgets
from .common import AppState, TIME_PATTERN, item, setup_table

# --------------------------------------------------------------------------
# Константы вида (ДИЗАЙН_СПЕЦ.md, разделы 1.2-1.6, 4.2-4.4)
# --------------------------------------------------------------------------
# Недели месяца считаются по числу месяца — как getWeekNumber в App.js:149-157
WEEK_RANGES = ((1, 7), (8, 14), (15, 21), (22, 28), (29, 31))

# Пять подколонок каждого дня (PlanFactTable.js:122-180)
DAY_FIELDS = ('plan_type', 'start_time', 'end_time', None, 'production_stage')
DAY_SUBTITLES = ('План', 'Приход', 'Уход', 'Факт', 'Этапы')

# Ширины закреплённых колонок (PlanFactTable.js:51-90)
LEFT_WIDTHS = (24, 120, 90)
LEFT_TOTAL = sum(LEFT_WIDTHS)
FRAME = 1                                  # рамка 1px у таблиц

ROW_HEIGHT = 20                            # высота строки тела
HEAD_TOP_H = 32                            # число дня + день недели (34px в вебе)
HEAD_SUB_H = 15                            # строка План/Приход/Уход/Факт/Этапы
TOP_TOTAL = HEAD_TOP_H + 2 * FRAME         # внешняя высота шапки дня
SUB_TOTAL = HEAD_SUB_H + 2 * FRAME

ROW_TIP = 'Кликните, чтобы выбрать сотрудника'
CELL_TIPS = {
    'plan_type': 'Кликните для редактирования плана (график)',
    'start_time': 'Кликните для редактирования прихода',
    'end_time': 'Кликните для редактирования ухода',
    'production_stage': 'Кликните для редактирования этапов производства',
}
FIELD_PLACEHOLDER = {
    'plan_type': '—',
    'start_time': '__:__',
    'end_time': '__:__',
    'production_stage': '...',
}
TIME_FIELDS = ('start_time', 'end_time')
SORT_TITLES = {'name': 'ФИО', 'position': 'Должность'}


def _hex(color: str | None) -> str | None:
    """Приводит цвет к HEX: common.qcolor понимает только #RRGGBB, не 'white'."""
    if color is None:
        return None
    name = str(color).strip()
    if name.startswith('#'):
        return name
    value = QColor(name)
    return value.name() if value.isValid() else name


def _hours_text(value) -> str:
    """Число часов как в вебе: 11 → «11», 10.5 → «10.5»."""
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return ''
    if hours <= 0:
        return ''
    if hours == int(hours):
        return str(int(hours))
    return f'{hours:.2f}'.rstrip('0').rstrip('.')


def _week_of(iso_date: str | None) -> int:
    """Индекс недели по числу месяца (App.js:149-157); -1 — дата непонятна."""
    try:
        day = int(str(iso_date)[8:10])
    except (TypeError, ValueError):
        return -1
    for index, (start, end) in enumerate(WEEK_RANGES):
        if start <= day <= end:
            return index
    return -1


class _FrozenTable(QTableWidget):
    """Левая (закреплённая) таблица: колесо прокрутки отдаёт правой таблице."""

    def __init__(self, partner: QTableWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._partner = partner

    def wheelEvent(self, event) -> None:                  # noqa: N802 — имя из Qt
        event.accept()
        self._partner.wheelEvent(event)


class CellEditor(QLineEdit):
    """Поле ввода внутри ячейки: Enter — сохранить, Esc — отмена, blur — сохранить."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._done = False

    def finish(self, commit: bool) -> None:
        if self._done:
            return
        self._done = True
        if commit:
            self.committed.emit(self.text())
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event) -> None:               # noqa: N802 — имя из Qt
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            self.finish(True)
            return
        if key == Qt.Key.Key_Escape:
            event.accept()
            self.finish(False)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:               # noqa: N802 — имя из Qt
        super().focusOutEvent(event)
        self.finish(True)


class PlanFactTab(QWidget):
    """Вкладка «План-Факт»: панель действий, таблица недели и легенда."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state

        self._rows: list[dict] = []            # записи месяца (плоский список ядра)
        self._period: tuple[int, int] | None = None
        self._week_rows: list[dict] = []       # записи выбранной недели
        self._employees: list[dict] = []       # строки матрицы
        self._dates: list[str] = []            # колонки-дни выбранной недели
        self._selected: str | None = None      # выделенный сотрудник — по ФИО
        self._sort_field = 'name'
        self._sort_dir = 'asc'
        self._editor: CellEditor | None = None
        self._editor_ctx: dict | None = None
        self._syncing = False
        self._font_px: int | None = None
        self._columns = -1

        self._build_tables()
        self._build_actions()
        self._build_layout()
        self._connect_state()

    # ==================================================================
    # построение интерфейса
    # ==================================================================
    def _setup_body_table(self, table: QTableWidget, font_px: int) -> None:
        """Общий вид таблицы тела + высота строки.

        Минимальная высота строки у QHeaderView берётся от шрифта (24 px) и
        молча поднимает заданные 20 px, поэтому минимум обнуляем и только
        после этого задаём высоту строки.
        """
        setup_table(table, font_size=font_px, row_height=ROW_HEIGHT)
        header = table.verticalHeader()
        header.setMinimumSectionSize(0)
        header.setDefaultSectionSize(ROW_HEIGHT)
        table.horizontalHeader().setMinimumSectionSize(0)
        table.horizontalHeader().setVisible(False)         # шапка — отдельная таблица

    def _build_tables(self) -> None:
        self.table = QTableWidget(self)
        self._setup_body_table(self.table, theme.FONT['planfact_narrow'])
        self._font_px = theme.FONT['planfact_narrow']
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.cellClicked.connect(self._on_day_cell_clicked)

        self.fixed_table = _FrozenTable(self.table, self)
        self._setup_body_table(self.fixed_table, theme.FONT['planfact_narrow'])
        self.fixed_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.fixed_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fixed_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.fixed_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fixed_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fixed_table.cellClicked.connect(self._on_row_cell_clicked)
        self.fixed_table.setColumnCount(len(LEFT_WIDTHS))
        for column, width in enumerate(LEFT_WIDTHS):
            self.fixed_table.setColumnWidth(column, width)
        self.fixed_table.setFixedWidth(LEFT_TOTAL + 2 * FRAME)

        self.corner = self._make_header_table(2, 3, theme.PF_HEADER_BORDER, theme.PF_HEADER_BG)
        self.corner.setFixedWidth(LEFT_TOTAL + 2 * FRAME)
        self.corner.setFixedHeight(TOP_TOTAL + SUB_TOTAL)
        self.corner.setRowHeight(0, TOP_TOTAL - FRAME)
        self.corner.setRowHeight(1, SUB_TOTAL - FRAME)
        for column, width in enumerate(LEFT_WIDTHS):
            self.corner.setColumnWidth(column, width)
        for column, title in enumerate(('№', 'ФИО', 'Должность')):
            self.corner.setSpan(0, column, 2, 1)
            self.corner.setItem(0, column, item(
                title, bg=theme.PF_HEADER_BG, fg=_hex(theme.PF_HEADER_TEXT),
                font_size=theme.FONT['table_header'],
                center=(column == 0)))

        self.header_top = self._make_header_table(1, 0, theme.PF_HEADER_BORDER,
                                                  theme.PF_HEADER_BG)
        self.header_top.setWordWrap(True)
        self.header_top.setRowHeight(0, HEAD_TOP_H)
        self.header_top.setFixedHeight(TOP_TOTAL)

        self.header_sub = self._make_header_table(1, 0, theme.PF_SUBHEADER_BORDER,
                                                  theme.PF_SUBHEADER_BG)
        self.header_sub.setRowHeight(0, HEAD_SUB_H)
        self.header_sub.setFixedHeight(SUB_TOTAL)

        # Шапки шире правой таблицы на ширину её вертикальной полосы прокрутки —
        # гасим разницу, чтобы колонки дней совпадали при прокрутке.
        scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self)
        header_wrap = QWidget()
        header_layout = QVBoxLayout(header_wrap)
        header_layout.setContentsMargins(0, 0, scrollbar, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(self.header_top)
        header_layout.addWidget(self.header_sub)
        self.header_wrap = header_wrap

    def _make_header_table(self, rows: int, columns: int, grid: str, background: str):
        """Таблица шапки: без заголовков, без выделения, только заливка и сетка."""
        table = QTableWidget(rows, columns, self)
        table.setShowGrid(True)
        table.setWordWrap(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(HEAD_SUB_H)
        table.verticalHeader().setMinimumSectionSize(0)   # иначе шапка ниже 24px не влезает
        table.horizontalHeader().setMinimumSectionSize(0)  # колонка «№» — 24px
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # Полосы прокрутки у шапок только мешают: прокрутка задаётся программно,
        # а показанная полоса съедала бы часть ширины и обрезала колонки.
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setStyleSheet(
            f'QTableWidget {{ background: {background}; gridline-color: {grid};'
            f' border: {FRAME}px solid {grid};'
            f' font-family: "{theme.FONT_FAMILY}"; }}'
        )
        return table

    def _build_actions(self) -> None:
        self.actions = widgets.Panel()
        row = self.actions.row
        row.setSpacing(12)                                 # gap 6px 12px (App.js:429)

        row.addWidget(self._hint_label('Сортировка:', theme.TEXT_MUTED))

        self.sort_buttons: dict[str, QPushButton] = {}
        for field in ('name', 'position'):
            button = theme.make_neutral_button(self.actions, f'{SORT_TITLES[field]} ↕')
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, key=field: self._on_sort(key))
            self.sort_buttons[field] = button
            row.addWidget(button)

        row.addWidget(widgets.separator())

        self.week_buttons: list[QPushButton] = []
        for index, label in enumerate(core.WEEK_LABELS_SHORT):
            button = theme.make_neutral_button(self.actions, f'{label} (0)')
            button.setToolTip(core.WEEK_LABELS[index])
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, key=index: self._on_week(key))
            self.week_buttons.append(button)
            row.addWidget(button)

        row.addWidget(widgets.separator())

        self.export_week_button = theme.make_button(
            self.actions, '📥 Неделя', theme.BUTTON_COLORS['export_week'])
        self.export_week_button.setToolTip('Выгрузить текущую неделю в Excel')
        self.export_week_button.clicked.connect(self._export_week)
        row.addWidget(self.export_week_button)

        self.export_month_button = theme.make_button(
            self.actions, '📥 Месяц', theme.BUTTON_COLORS['export_month'])
        self.export_month_button.setToolTip('Выгрузить весь месяц в Excel')
        self.export_month_button.clicked.connect(self._export_month)
        row.addWidget(self.export_month_button)

        row.addWidget(widgets.separator())

        self.delete_button = theme.make_button(
            self.actions, '🗑️ Удалить (1–7)', theme.BUTTON_COLORS['delete'])
        self.delete_button.setToolTip(
            'Удалить планы и факты сотрудника с текущей недели до конца месяца')
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_employee)
        row.addWidget(self.delete_button)

        self.edit_button = theme.make_neutral_button(self.actions, '✏️ Правка')
        self.edit_button.setCheckable(True)
        self.edit_button.setChecked(False)                 # по умолчанию правка выключена
        self.edit_button.setToolTip('Правка пишет в базу проекта и в файл графика')
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.toggled.connect(self._on_edit_toggled)
        row.addWidget(self.edit_button)

        self.selection_label = self._hint_label('Выберите строку для удаления',
                                                theme.TEXT_HINT)
        row.addWidget(self.selection_label)

        row.addStretch(1)

        self.total_label = self._hint_label('Всего: <b>0</b>', theme.TEXT_HINT)
        row.addWidget(self.total_label)

    @staticmethod
    def _hint_label(text: str, color: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(theme.label_qss(color, theme.FONT['hint']))
        return label

    def _build_layout(self) -> None:
        area = QWidget(self)
        grid = QGridLayout(area)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.corner, 0, 0, 2, 1)
        grid.addWidget(self.header_wrap, 0, 1, 2, 1)
        grid.addWidget(self.fixed_table, 2, 0)
        grid.addWidget(self.table, 2, 1)
        grid.setRowMinimumHeight(0, TOP_TOTAL)
        grid.setRowMinimumHeight(1, SUB_TOTAL)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)                               # margin-bottom: 4px
        layout.addWidget(self.actions)
        layout.addWidget(area, 1)
        layout.addWidget(widgets.Legend())

    def _connect_state(self) -> None:
        self.state.weekChanged.connect(self._on_week_changed)
        self.state.periodChanged.connect(self._on_period_changed)
        self.state.refreshRequested.connect(self._on_refresh_requested)

        # Прокрутки: левая и правая таблицы ходят вместе, шапка — за правой.
        self.table.verticalScrollBar().valueChanged.connect(self._sync_vertical_from_main)
        self.fixed_table.verticalScrollBar().valueChanged.connect(self._sync_vertical_from_left)
        self.table.horizontalScrollBar().valueChanged.connect(self._sync_horizontal)

    # ==================================================================
    # данные
    # ==================================================================
    def load(self) -> None:
        """Загрузить план-факт месяца из ядра и перерисовать таблицу."""
        try:
            rows = core.load_plan_fact(self.state.year, self.state.month)
        except core.CoreError as exc:
            self._rows = []
            self._period = (self.state.year, self.state.month)
            self._render()
            self.state.say(f'❌ Ошибка: {exc}')
            return
        self._rows = rows
        self._period = (self.state.year, self.state.month)
        self._render()

    def _week(self) -> int:
        week = int(self.state.week_id or 0)
        return week if 0 <= week < len(WEEK_RANGES) else 0

    def _week_counts(self) -> list[int]:
        counts = [0] * len(WEEK_RANGES)
        for record in self._rows:
            index = _week_of(record.get('date'))
            if index >= 0:
                counts[index] += 1
        return counts

    # ==================================================================
    # отрисовка
    # ==================================================================
    def _render(self) -> None:
        self._close_editor()

        week = self._week()
        self._week_rows = [r for r in self._rows if _week_of(r.get('date')) == week]

        employees: dict[str, dict] = {}
        for record in self._week_rows:
            name = record.get('employee_name') or ''
            entry = employees.get(name)
            if entry is None:
                entry = {'name': name, 'position': record.get('position') or '', 'days': {}}
                employees[name] = entry
            if not entry['position']:
                entry['position'] = record.get('position') or ''
            entry['days'][record.get('date')] = record

        key = (lambda e: (e['name'] if self._sort_field == 'name'
                          else e['position']).lower())
        self._employees = sorted(employees.values(), key=key,
                                 reverse=self._sort_dir == 'desc')
        self._dates = sorted({r.get('date') for r in self._week_rows if r.get('date')})

        days = len(self._dates)
        font_px = theme.table_font_size(days)              # App.js:318
        col_width = 45 if days <= 7 else (32 if days <= 14 else 24)   # App.js:317

        if font_px != self._font_px:
            self._font_px = font_px
            self._setup_body_table(self.table, font_px)
            self._setup_body_table(self.fixed_table, font_px)

        self._fill_header(font_px, col_width)
        self._fill_body(font_px)
        self._update_actions()

    def _fill_header(self, font_px: int, col_width: int) -> None:
        columns = len(self._dates) * 5
        if self._columns != columns:
            self._columns = columns
            for table in (self.header_top, self.header_sub, self.table):
                table.clearSpans()
                table.setColumnCount(columns)
                for column in range(columns):
                    table.setColumnWidth(column, col_width)

        day_font = max(8, font_px)
        sub_font = theme.FONT['subheader']                 # 7px, PlanFactTable.js:119
        backgrounds = (None, theme.PF_SUBHEADER_IN, theme.PF_SUBHEADER_IN,
                       theme.PF_SUBHEADER_FACT, theme.PF_SUBHEADER_STAGE)

        for index, iso in enumerate(self._dates):
            first = index * 5
            self.header_top.setSpan(0, first, 1, 5)
            day = int(iso[8:10])
            weekday = core.WEEKDAY_SHORT[date.fromisoformat(iso).weekday()]
            self.header_top.setItem(0, first, item(
                f'{day}\n{weekday}', bg=theme.PF_HEADER_BG, fg=_hex(theme.PF_HEADER_TEXT),
                font_size=day_font, center=True))
            for offset, title in enumerate(DAY_SUBTITLES):
                background = backgrounds[offset] or theme.PF_SUBHEADER_BG
                fg = (theme.PF_SUBHEADER_STAGE_TEXT if title == 'Этапы'
                      else theme.PF_SUBHEADER_TEXT)
                self.header_sub.setItem(0, first + offset, item(
                    title, bg=background, fg=_hex(fg), bold=True,
                    font_size=sub_font, center=True))

    def _fill_body(self, font_px: int) -> None:
        rows = len(self._employees)
        self.table.setRowCount(rows)
        self.fixed_table.setRowCount(rows)

        number_font = max(8, font_px)
        position_font = max(7, font_px - 1)
        plan_font = max(7, font_px - 1)
        time_font = max(6, font_px - 2)
        fact_font = max(7, font_px - 1)

        for row, employee in enumerate(self._employees):
            selected = employee['name'] == self._selected
            border = theme.PF_SELECTED_BORDER if selected else None
            row_bg = theme.PF_SELECTED_BG if selected else '#ffffff'

            self.fixed_table.setItem(row, 0, item(
                row + 1, center=True, bg=row_bg, font_size=number_font,
                border=border, tooltip=ROW_TIP))
            self.fixed_table.setItem(row, 1, item(
                employee['name'], bold=True, bg=row_bg, font_size=number_font,
                border=border, tooltip=ROW_TIP))
            self.fixed_table.setItem(row, 2, item(
                employee['position'], bg=row_bg, font_size=position_font,
                border=border, tooltip=ROW_TIP))

            for index, iso in enumerate(self._dates):
                record = employee['days'].get(iso) or {}
                first = index * 5
                status = record.get('status') or 'Нет данных'
                plan_type = record.get('plan_type') or ''
                start_time = record.get('start_time') or ''
                end_time = record.get('end_time') or ''
                stage = record.get('production_stage') or ''
                fact = _hours_text(record.get('fact_hours'))

                # План: фон — цвет статуса дня (PlanFactTable.js:289)
                self.table.setItem(row, first, item(
                    plan_type, center=True, bold=bool(plan_type),
                    bg=theme.status_bg(status), fg=_hex(theme.status_fg(status)),
                    font_size=plan_font, border=border, tooltip=CELL_TIPS['plan_type']))
                # Приход / Уход: заливка только со значением (PlanFactTable.js:333,372)
                self.table.setItem(row, first + 1, item(
                    start_time, center=True, font_size=time_font,
                    bg=theme.PF_IN_BG if start_time else (row_bg if selected else None),
                    fg=_hex(theme.PF_TIME_TEXT) if start_time else None,
                    border=border, tooltip=CELL_TIPS['start_time']))
                self.table.setItem(row, first + 2, item(
                    end_time, center=True, font_size=time_font,
                    bg=theme.PF_OUT_BG if end_time else (row_bg if selected else None),
                    fg=_hex(theme.PF_TIME_TEXT) if end_time else None,
                    border=border, tooltip=CELL_TIPS['end_time']))
                # Факт: «11ч», не редактируется (PlanFactTable.js:405-416)
                self.table.setItem(row, first + 3, item(
                    f'{fact}ч' if fact else '', center=True, bold=bool(fact),
                    bg=theme.PF_FACT_BG if fact else theme.PF_FACT_EMPTY_BG,
                    font_size=fact_font, border=border))
                # Этапы: пусто → «—» серым (PlanFactTable.js:423-427)
                self.table.setItem(row, first + 4, item(
                    stage or '—', center=True, font_size=time_font,
                    bg=theme.PF_STAGE_BG if stage else (row_bg if selected else None),
                    fg=None if stage else theme.TEXT_FAINT,
                    border=border, tooltip=CELL_TIPS['production_stage']))

    def _update_actions(self) -> None:
        week = self._week()
        counts = self._week_counts()
        for index, button in enumerate(self.week_buttons):
            button.setText(f'{core.WEEK_LABELS_SHORT[index]} ({counts[index]})')
            self._style_toggle(button, index == week)

        for field, button in self.sort_buttons.items():
            icon = ('↕' if field != self._sort_field
                    else ('↑' if self._sort_dir == 'asc' else '↓'))
            button.setText(f'{SORT_TITLES[field]} {icon}')
            self._style_toggle(button, field == self._sort_field)

        self.delete_button.setText(f'🗑️ Удалить ({core.WEEK_LABELS_SHORT[week]})')
        self.delete_button.setEnabled(self._selected is not None)
        self.selection_label.setText(f'Выбран: {self._selected}' if self._selected
                                     else 'Выберите строку для удаления')
        self.total_label.setText(f'Всего: <b>{len(self._rows)}</b>')

    @staticmethod
    def _style_toggle(button: QPushButton, active: bool) -> None:
        """Активная кнопка недели/сортировки — синяя с жирным текстом."""
        if active:
            theme.style_button(button, theme.BUTTON_ACTIVE_BG)
        else:
            theme.style_button(button, theme.BUTTON_NEUTRAL_BG,
                               text=theme.BUTTON_NEUTRAL_TEXT, bold=False)

    # ==================================================================
    # прокрутка
    # ==================================================================
    def _sync_vertical_from_main(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.fixed_table.verticalScrollBar().setValue(value)
        self._syncing = False
        self._reposition_editor()

    def _sync_vertical_from_left(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.table.verticalScrollBar().setValue(value)
        self._syncing = False

    def _sync_horizontal(self, value: int) -> None:
        self.header_top.horizontalScrollBar().setValue(value)
        self.header_sub.horizontalScrollBar().setValue(value)
        self._reposition_editor()

    # ==================================================================
    # действия панели
    # ==================================================================
    def _on_sort(self, field: str) -> None:
        if self._sort_field == field:
            self._sort_dir = 'desc' if self._sort_dir == 'asc' else 'asc'
        else:
            self._sort_field = field
            self._sort_dir = 'asc'
        self._render()

    def _on_week(self, week: int) -> None:
        if week == self._week():
            return
        self.state.set_week(week)              # -> weekChanged -> _on_week_changed

    def _on_week_changed(self, _week: int) -> None:
        self._render()

    def _on_period_changed(self, _year: int, _month: int) -> None:
        # Главное окно само вызовет load() для активной вкладки, поэтому
        # перезагружаемся только если данные остались от другого периода.
        QTimer.singleShot(0, self._reload_if_stale)

    def _on_refresh_requested(self) -> None:
        QTimer.singleShot(0, self._reload_if_stale)

    def _reload_if_stale(self) -> None:
        if self._period == (self.state.year, self.state.month):
            self._render()
        elif self.isVisible():
            # Скрытую вкладку загрузит главное окно, когда её покажет.
            self.load()

    def _on_edit_toggled(self, checked: bool) -> None:
        self._style_toggle(self.edit_button, checked)
        if not checked and self._editor is not None:
            self._commit_editor()
        if checked:
            self.state.say('✏️ Правка включена: изменения пишутся в базу проекта '
                           'и в файл графика', 4000)
        else:
            self.state.say('✏️ Правка выключена', 3000)

    # ------------------------------------------------------------------
    # выгрузки
    # ------------------------------------------------------------------
    def _export_week(self) -> None:
        week = self._week()
        label = core.WEEK_LABELS[week]
        self._export(lambda: core.export_week(self.state.year, self.state.month, week),
                     f'⏳ Выгрузка недели {label}...',
                     f'✅ Выгружена неделя {label}')

    def _export_month(self) -> None:
        self._export(lambda: core.export_month(self.state.year, self.state.month),
                     '⏳ Выгрузка месячного отчета...',
                     '✅ Месячный отчет выгружен')

    def _export(self, builder, busy_message: str, done_message: str) -> None:
        self.state.say(busy_message)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = builder()
        except (core.CoreError, OSError) as exc:
            self.state.say(f'❌ Ошибка: {exc}')
            return
        finally:
            QGuiApplication.restoreOverrideCursor()

        path = self._ask_save_path(result.filename)
        if not path:
            self.state.say('')                     # пользователь отменил выбор файла
            return
        try:
            result.save(path)
        except OSError as exc:
            self.state.say(f'❌ Ошибка: {exc}')
            return
        self.state.say(done_message)

    def _ask_save_path(self, filename: str) -> str:
        folder = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation) or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, 'Сохранить выгрузку', str(Path(folder) / filename), 'Excel (*.xlsx)')
        if not path:
            return ''
        return path if Path(path).suffix else f'{path}.xlsx'

    # ------------------------------------------------------------------
    # удаление
    # ------------------------------------------------------------------
    def _delete_employee(self) -> None:
        name = self._selected
        if not name:
            self.state.say('⚠️ Сначала выберите сотрудника — кликните по его строке '
                           'в таблице')
            return

        week = self._week()
        days_in_month = core.days_in_month(self.state.year, self.state.month)
        first_day = min(1 + week * 7, days_in_month)       # App.js:221
        date_from = f'{self.state.year}-{self.state.month:02d}-{first_day:02d}'
        date_to = f'{self.state.year}-{self.state.month:02d}-{days_in_month:02d}'

        question = QMessageBox.question(
            self, 'Удаление данных',
            f'Удалить данные сотрудника «{name}»?\n\n'
            f'Период: с {date_from} (неделя «{core.WEEK_LABELS[week]}») '
            f'по {date_to} (конец месяца).\n'
            f'Будут удалены все планы и факты за этот период. Отменить нельзя.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if question != QMessageBox.StandardButton.Yes:
            return

        try:
            result = core.delete_employee_from(name, date_from, date_to)
        except core.CoreError as exc:
            self.state.say(f'❌ Ошибка: {exc}')
            return

        self.state.say(f"✅ {result.get('message', 'Данные удалены')}", 5000)
        self.state.plan_changed()
        self._selected = None
        self.load()

    # ==================================================================
    # выделение и правка ячеек
    # ==================================================================
    def _on_row_cell_clicked(self, row: int, _column: int) -> None:
        if self._editor is not None:
            self._commit_editor()
        self._select_row(row)

    def _on_day_cell_clicked(self, row: int, column: int) -> None:
        if self._editor is not None:
            self._commit_editor()              # уход фокуса сохраняет (blur в вебе)
        self._select_row(row)
        field = DAY_FIELDS[column % 5]
        if field is None or not self.edit_button.isChecked():
            return
        self._open_editor(row, column, field)

    def _select_row(self, row: int) -> None:
        employee = self._employee_at(row)
        if employee is not None:
            self._select(employee['name'])

    def _select(self, name: str) -> None:
        if self._selected == name:
            return
        self._selected = name
        self._render()

    def _employee_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._employees):
            return self._employees[row]
        return None

    def _open_editor(self, row: int, column: int, field: str) -> None:
        employee = self._employee_at(row)
        if employee is None:
            return
        day_index, _offset = divmod(column, 5)
        if day_index >= len(self._dates):
            return
        iso = self._dates[day_index]
        record = employee['days'].get(iso) or {}

        self._close_editor()
        editor = CellEditor(self.table.viewport())
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setPlaceholderText(FIELD_PLACEHOLDER[field])
        editor.setMaxLength(5 if field in TIME_FIELDS else 40)
        font_px = max(6, self._font_px - 2)
        color = theme.PF_TIME_TEXT if field in TIME_FIELDS else '#333'
        editor.setStyleSheet(
            f'QLineEdit {{ background: {theme.PF_PLAN_EDITING}; border: none;'
            f' color: {color}; font-size: {font_px}px; font-weight: bold;'
            f' font-family: "{theme.FONT_FAMILY}"; padding: 0px; }}'
        )
        if field in TIME_FIELDS:
            editor.textChanged.connect(
                lambda text, widget=editor: self._mask_time(widget, text))
        editor.setText(str(record.get(field) or ''))
        editor.committed.connect(self._on_editor_committed)
        editor.cancelled.connect(self._on_editor_cancelled)
        editor.setGeometry(self.table.visualRect(self.table.model().index(row, column)))
        self._editor = editor
        self._editor_ctx = {'row': row, 'column': column, 'field': field,
                            'employee': employee['name'], 'date': iso}
        editor.show()
        editor.setFocus()
        editor.selectAll()

    @staticmethod
    def _mask_time(editor: QLineEdit, text: str) -> None:
        """Маска ЧЧ:ММ — двоеточие подставляется само (useCellEditing.js:110-125)."""
        cleaned = ''.join(ch for ch in text if ch.isdigit() or ch == ':')
        if cleaned != text:
            editor.setText(cleaned)
            return
        if len(cleaned) == 2 and ':' not in cleaned:
            cleaned = f'{cleaned}:'
        elif len(cleaned) == 5 and cleaned[2] != ':':
            cleaned = f'{cleaned[:2]}:{cleaned[2:]}'
        if cleaned != text:
            editor.setText(cleaned)

    def _close_editor(self) -> None:
        editor = self._editor
        self._editor = None
        self._editor_ctx = None
        if editor is not None:
            editor.blockSignals(True)
            editor.hide()
            editor.deleteLater()

    def _commit_editor(self) -> None:
        editor = self._editor
        if editor is not None:
            editor.finish(True)

    def _reposition_editor(self) -> None:
        if self._editor is None or self._editor_ctx is None:
            return
        context = self._editor_ctx
        index = self.table.model().index(context['row'], context['column'])
        self._editor.setGeometry(self.table.visualRect(index))

    def _on_editor_cancelled(self) -> None:
        # Escape в вебе = resetEditing: отмена правки и снятие выделения
        self._close_editor()
        self._selected = None
        self._render()

    def _on_editor_committed(self, text: str) -> None:
        context = self._editor_ctx
        self._close_editor()
        if context is None:
            return

        field = context['field']
        employee = context['employee']
        iso = context['date']
        value = text.strip() if field in TIME_FIELDS else text

        if field in TIME_FIELDS and value and not re.match(TIME_PATTERN, value):
            self.state.say('❌ Неверный формат времени. '
                           'Используйте HH:MM (например, 08:00)')
            return

        try:
            if field == 'plan_type':
                result = core.update_plan(employee, iso, value)
                message = (result.get('message')
                           or f'Обновлен план: {employee} | {iso} = {value or "(пусто)"}')
            elif field == 'production_stage':
                core.update_production_stage(employee, iso, value)
                message = f'Обновлен этап: {employee} | {iso} = {value or "(пусто)"}'
            else:
                core.update_time(employee, iso, field, value)
                title = 'Приход' if field == 'start_time' else 'Уход'
                message = f'Обновлено: {employee} | {iso} | {title} = {value}'
        except core.CoreError as exc:
            self.state.say(f'❌ Ошибка: {exc}')
            return

        self.state.say(f'✅ {message}')
        self.state.plan_changed()
        self._selected = employee               # выделение хранится по ФИО
        self.load()


__all__ = ['PlanFactTab']
