"""Вкладка «График» (форма А3) — перенос веб-версии на PySide6.

Источник вида и поведения: `frontend/src/components/ScheduleView.jsx`
(разбор — `ДИЗАЙН_СПЕЦ.md`, раздел 5). Раскладка сверху вниз повторяет веб:

    [ 🗂 панель инструментов: лист, счётчики сверки, действия ]
    [ ➕ Новый сотрудник: ФИО / Должность / Участок ]
    [ цветная строка сообщений вкладки ]
    [ легенда: цвета графика + рамки сверки + выделение ]
    [ таблица формы А3 (растягивается на остаток высоты) ]

Данные — только через `planfact.core` (тот же `backend/schedule_grid.py`,
что и у FastAPI), никакого HTTP. В отличие от веб-версии правка ячеек
по умолчанию выключена: переключатель «✏️ Разрешить правку» защищает
реальный файл `ГРАФИК_ФОРМА A3.xlsx` и план в базе от случайной записи.
"""
from __future__ import annotations

import os
from pathlib import Path

from openpyxl.utils import get_column_letter
from PySide6.QtCore import QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QGuiApplication, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget,
                               QVBoxLayout, QWidget)

from .. import core
from . import theme
from .common import BORDER_ROLE, BorderDelegate, AppState, item, qcolor, setup_table
from .widgets import MessageBar, Panel, separator

# --- константы раскладки (ScheduleView.jsx:15-18, 654-655) -----------------
FIXED_WIDTHS = {1: 104, 2: 164, 3: 116}      # участок, ФИО, должность
NOTES_WIDTH = 150                            # служебные текстовые колонки
DAY_MIN_WIDTH = 30                           # минимум для колонки-дня
ROW_HEIGHT = 19                              # высота строки (веб: 18px)
HEADER_ROWS = 2                              # строки шапки листа (1 и 2)

# Роль ячейки: признак «жирной» рамки из Excel (1px #9aa3ad)
BD_ROLE = Qt.ItemDataRole.UserRole + 2

# Подсказки редактируемых полей сотрудника (ScheduleView.jsx:21-25)
EF_TITLE = {
    'name': 'Кликните, чтобы изменить ФИО (Enter — сохранить, Esc — отмена)',
    'position': 'Кликните, чтобы изменить должность',
    'section': 'Кликните, чтобы изменить участок (для всей группы строк)',
}

# Длинные подсказки плашек «Рамки сверки» (ScheduleView.jsx:822-833)
CMP_TITLE = {
    'diff': 'В графике и в плане базы стоят разные значения',
    'db_missing': 'В графике смена есть, а плана в базе нет',
    'graf_missing': 'План в базе есть, а в графике день пустой',
    'no_employee': 'Сотрудника нет в справочнике базы — план сверить не с чем',
}

MESSAGE_MS = 4000        # сообщение вкладки живёт 4 с (ScheduleView.jsx:112)
STATUS_MS = 3000         # сообщение в общей строке приложения


class ScheduleDelegate(BorderDelegate):
    """Сетка ячеек: рамка сверки (2px, из `common.BorderDelegate`) + рамка Excel.

    Веб рисует у ячейки `1px solid #9aa3ad`, когда в файле стоит жирная
    граница, и поверх — `inset 0 0 0 2px` для рамок сверки. В Qt рамка
    сверки уже рисуется базовым делегатом, поэтому здесь добавляется
    только тонкая «жирная» граница из файла.
    """

    def paint(self, painter, option, index) -> None:      # noqa: D102
        super().paint(painter, option, index)
        if not index.data(BD_ROLE):
            return
        color = qcolor(theme.SCHEDULE_CELL_BORDER_BOLD)
        if color is None:
            return
        pen = QPen(color)
        pen.setWidth(1)
        painter.save()
        painter.setPen(pen)
        rect = option.rect
        painter.drawLine(rect.topLeft(), rect.topRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.restore()


class _Worker(QThread):
    """Выгрузка формы А3 (сборка xlsx) вне потока интерфейса."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, func, parent=None) -> None:
        super().__init__(parent)
        self._func = func

    def run(self) -> None:                                # noqa: D102
        try:
            self.done.emit(self._func())
        except Exception as exc:                          # noqa: BLE001
            self.failed.emit(str(exc))


class _AskDialog(QDialog):
    """Уточняющий вопрос вкладки — карточка в стиле модальных окон веба.

    Веб рисует свои диалоги сам (оверлей + рамка 2px цветом действия,
    заголовок 15px bold, тело 12px). Здесь то же содержимое показано
    обычным диалогом Qt: рамку рисует карточка внутри окна, а системная
    рамка оставлена, чтобы окно можно было сдвинуть и закрыть.
    """

    def __init__(self, parent: QWidget | None, *, title: str, color: str,
                 lines: list[tuple[str, str]], confirm_text: str,
                 confirm_color: str, confirm_enabled: bool = True,
                 window_title: str = 'Подтверждение', width: int = 520,
                 countdown: int | None = None,
                 checks: list[tuple[str, bool]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self._left = int(countdown or 0)

        card = QFrame(self)
        card.setObjectName('askCard')
        card.setStyleSheet(
            f'#askCard {{ background: white; border: 2px solid {color};'
            f' border-radius: 8px; }}'
        )
        column = QVBoxLayout(card)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(6)

        head = QLabel(title, card)
        head.setWordWrap(True)
        head.setStyleSheet(theme.label_qss(color, 15, bold=True))
        column.addWidget(head)

        for text, kind in lines:
            label = QLabel(text, card)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            if kind == 'muted':
                label.setStyleSheet(
                    f'color: {theme.TEXT_MUTED}; font-size: 12px;'
                    f' font-family: "{theme.FONT_FAMILY}";')
            elif kind == 'danger':
                label.setStyleSheet(
                    f'color: {theme.BUTTON_COLORS["clear"]}; font-size: 12px;'
                    f' font-weight: bold; font-family: "{theme.FONT_FAMILY}";')
            elif kind == 'warn':
                label.setStyleSheet(
                    f'color: #ef6c00; font-size: 12px;'
                    f' font-family: "{theme.FONT_FAMILY}";')
            else:
                label.setStyleSheet(theme.label_qss('#333', 12))
            column.addWidget(label)

        self._checks: list[QCheckBox] = []
        for text, checked in checks or []:
            box = QCheckBox(text, card)
            box.setChecked(checked)
            box.setStyleSheet(f'font-size: 12px; color: #333;'
                              f' font-family: "{theme.FONT_FAMILY}";')
            column.addWidget(box)
            self._checks.append(box)

        line = QFrame(card)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet('background: #eee; border: none;')
        column.addWidget(line)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.confirm_button = theme.make_button(
            card, confirm_text, confirm_color, font_size=12, padding='7px 16px')
        self.confirm_button.setEnabled(confirm_enabled)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.confirm_button)

        cancel = theme.make_button(
            card, 'Отмена', theme.BUTTON_NEUTRAL_BG, text=theme.BUTTON_NEUTRAL_TEXT,
            bold=False, border=f'1px solid {theme.BUTTON_BORDER}',
            font_size=12, padding='7px 16px')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self.countdown_label = QLabel('', card)
        self.countdown_label.setTextFormat(Qt.TextFormat.RichText)
        self.countdown_label.setStyleSheet(
            theme.label_qss(theme.TEXT_HINT, 11))
        buttons.addStretch(1)
        buttons.addWidget(self.countdown_label)
        column.addLayout(buttons)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        if self._checks:
            for box in self._checks:
                box.toggled.connect(self._update_confirm)
            self._update_confirm()

        if countdown:
            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
            self._update_countdown()

    # ------------------------------------------------------------------
    def checked(self) -> list[bool]:
        return [box.isChecked() for box in self._checks]

    def _update_confirm(self) -> None:
        enabled = any(box.isChecked() for box in self._checks)
        self.confirm_button.setEnabled(enabled)

    def _tick(self) -> None:
        """Обратный отсчёт: без ответа окно закрывается само (5 с в вебе)."""
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.reject()
            return
        self._update_countdown()

    def _update_countdown(self) -> None:
        self.countdown_label.setText(
            f'ответьте в течение <b style="color:{theme.BUTTON_COLORS["clear"]}">'
            f'{self._left}</b> с, иначе окно закроется'
        )


class ScheduleTab(QWidget):
    """Вкладка «График» за период `state.year` / `state.month`."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state

        self._data: dict | None = None
        self._cells: dict[tuple[int, int], dict] = {}
        self._days: dict[int, dict] = {}
        self._weekend_fill = '#' + theme.SCHEDULE_WEEKEND_DEFAULT.lstrip('#')
        self._selected: dict | None = None        # {'row': int, 'name': str}
        self._painted_row: int | None = None
        self._loading = False
        self._saving = False
        self._sizing = False
        self._busy_depth = 0
        self._exporting: str | None = None
        self._workers: list[_Worker] = []

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_message)

        self.message_bar = MessageBar()

        self._build_toolbar()
        self._build_add_panel()
        self._build_legend()
        self._build_table()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.add_panel)
        layout.addWidget(self.message_bar)
        layout.addWidget(self.legend)
        layout.addWidget(self.table, 1)

        self.state.periodChanged.connect(self._on_period_changed)
        self.state.refreshRequested.connect(self.load)

        self._update_toolbar(None)
        self._update_legend()

    # ==================================================================
    # построение интерфейса
    # ==================================================================
    def _build_toolbar(self) -> None:
        """Панель инструментов: лист, сверка, действия (ScheduleView.jsx:422-528).

        В вебе это строка с `flex-wrap: wrap`; в Qt переноса нет, поэтому
        панель разложена на две строки — сведения о листе и сверке сверху,
        кнопки действий снизу в том же порядке, что и в веб-версии.
        """
        self.toolbar = Panel()
        self.toolbar.row.setSpacing(0)
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        self.toolbar.row.addLayout(rows)

        row = QHBoxLayout()                # верхняя строка: лист, сверка, счётчики
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        rows.addLayout(row)
        actions = QHBoxLayout()            # нижняя строка: кнопки действий
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        rows.addLayout(actions)

        self.sheet_label = QLabel('📅 График: —')
        self.sheet_label.setTextFormat(Qt.TextFormat.RichText)
        self.sheet_label.setStyleSheet(theme.label_qss('#555', theme.FONT['button']))
        row.addWidget(self.sheet_label)

        # Предупреждение о рассинхроне листа (красное, жирное)
        self.sheet_warn = QLabel('')
        self.sheet_warn.setStyleSheet(
            theme.label_qss(theme.BUTTON_COLORS['clear'], theme.FONT['button'], bold=True))
        self.sheet_warn.setVisible(False)
        row.addWidget(self.sheet_warn)

        # Предупреждение о числе дней (оранжевое)
        self.days_warn = QLabel('')
        self.days_warn.setStyleSheet(
            theme.label_qss('#ef6c00', theme.FONT['button']))
        self.days_warn.setVisible(False)
        row.addWidget(self.days_warn)

        row.addWidget(separator())

        self.diff_label = self._counter_label()
        self.db_missing_label = self._counter_label()
        self.ok_label = self._counter_label()
        row.addWidget(self.diff_label)
        row.addWidget(self.db_missing_label)
        row.addWidget(self.ok_label)

        self.loading_label = QLabel('⏳ обновление…')
        self.loading_label.setStyleSheet(
            theme.label_qss(theme.BUTTON_COLORS['refresh'], theme.FONT['button']))
        self.loading_label.setVisible(False)
        row.addWidget(self.loading_label)

        row.addStretch(1)

        # Осознанное отличие от веб-версии: правка реального файла и плана
        # включается только явным переключателем (по умолчанию выключен).
        self.edit_button = theme.make_neutral_button(
            self, '✏️ Разрешить правку', active=False)
        self.edit_button.setCheckable(True)
        self.edit_button.setChecked(False)
        self.edit_button.setToolTip(
            'Правка пишет в реальный файл ГРАФИК_ФОРМА A3.xlsx и в план БД')
        self.edit_button.toggled.connect(self._on_edit_toggled)
        row.addWidget(self.edit_button)

        self.create_button = theme.make_button(
            self, '📄 Создать лист', theme.BUTTON_COLORS['sheet'],
            font_size=theme.FONT['button'], padding='2px 10px')
        self.create_button.clicked.connect(self._create_sheet)
        actions.addWidget(self.create_button)

        self.delete_button = theme.make_button(
            self, '🗑️ Удалить из графика',
            theme.BUTTON_COLORS['remove_from_schedule'],
            font_size=theme.FONT['button'], padding='2px 10px')
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_employee)
        actions.addWidget(self.delete_button)

        self.export_actual_button = theme.make_button(
            self, '📥 Как есть', theme.BUTTON_COLORS['export_actual'],
            font_size=theme.FONT['button'], padding='2px 10px')
        self.export_actual_button.setToolTip(
            'Выгрузить форму А3 с данными как есть (шапка утверждения, '
            'без колонки «Изменения в графике»)')
        self.export_actual_button.clicked.connect(lambda: self._export('actual'))
        actions.addWidget(self.export_actual_button)

        self.export_rhythm_button = theme.make_button(
            self, '📥 Только ритмы', theme.BUTTON_COLORS['export_rhythm'],
            font_size=theme.FONT['button'], padding='2px 10px')
        self.export_rhythm_button.setToolTip(
            'Выгрузить форму А3 только со сменами 11, 9, 8 по ритму (2 через 2 и 5 через 2)')
        self.export_rhythm_button.clicked.connect(lambda: self._export('rhythm'))
        actions.addWidget(self.export_rhythm_button)

        self.shifts_button = theme.make_button(
            self, '⚙️ Расставить смены', theme.BUTTON_COLORS['shifts'],
            font_size=theme.FONT['button'], padding='2px 10px')
        self.shifts_button.setToolTip(
            'Расставить смены за выбранный месяц по ритму из графика: 11 — 2 через 2, '
            '9 и 8 — 5 через 2 (заполняются только пустые дни)')
        self.shifts_button.clicked.connect(self._ask_shifts)
        actions.addWidget(self.shifts_button)

        self.clear_button = theme.make_button(
            self, '🧹 Очистить', theme.BUTTON_COLORS['clear'],
            font_size=theme.FONT['button'], padding='2px 10px')
        self.clear_button.setToolTip(
            'Очистить смены за выбранный месяц, план в базе и примечания '
            '(сотрудники и оформление останутся)')
        self.clear_button.clicked.connect(self._ask_clear)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)

    def _counter_label(self) -> QLabel:
        label = QLabel('')
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet(theme.label_qss('#555', theme.FONT['button']))
        return label

    def _build_add_panel(self) -> None:
        """Панель «➕ Новый сотрудник» (ScheduleView.jsx:531-566)."""
        self.add_panel = Panel(background='#f2f7ff', border='#cfe0f5')
        row = self.add_panel.row

        caption = QLabel('➕ Новый сотрудник:')
        caption.setStyleSheet(
            theme.label_qss(theme.BUTTON_COLORS['refresh'], theme.FONT['button'], bold=True))
        row.addWidget(caption)

        self.name_edit = self._new_field('ФИО', 180)
        self.position_edit = self._new_field('Должность', 140)
        self.section_edit = self._new_field('Участок', 150)
        self.name_edit.returnPressed.connect(self._add_employee)
        row.addWidget(self.name_edit)
        row.addWidget(self.position_edit)
        row.addWidget(self.section_edit)

        self.add_button = theme.make_button(
            self, '➕ Добавить в график и базу', theme.BUTTON_COLORS['add_employee'],
            font_size=theme.FONT['button'], padding='3px 12px')
        self.add_button.clicked.connect(self._add_employee)
        row.addWidget(self.add_button)
        row.addStretch(1)

    @staticmethod
    def _new_field(placeholder: str, width: int) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setFixedWidth(width)
        edit.setStyleSheet(
            'QLineEdit { background: #f2f7ff; border: 1px solid #cfe0f5;'
            ' border-radius: 3px; padding: 3px 6px; font-size: 11px; }'
        )
        return edit

    def _build_legend(self) -> None:
        """Легенда: цвета графика, рамки сверки и выделение (раздел 5.5).

        В вебе это одна строка с переносом; здесь две строки — цвета графика
        и рамки сверки, — иначе при ширине окна 1580px содержимое обрезалось бы.
        """
        self.legend = QWidget()
        self.legend.setToolTip(
            '🖱️ клик по ячейке — редактирование: смены, ФИО, должность, участок '
            '(Enter — сохранить, Esc — отмена)')
        column = QVBoxLayout(self.legend)
        column.setContentsMargins(10, 2, 10, 2)
        column.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        column.addLayout(row)

        borders = QHBoxLayout()
        borders.setContentsMargins(0, 0, 0, 0)
        borders.setSpacing(6)
        column.addLayout(borders)

        title = QLabel('Цвета графика:')
        title.setStyleSheet(theme.label_qss('#555', theme.FONT['schedule'], bold=True))
        row.addWidget(title)

        for value, caption, background, foreground in theme.SCHEDULE_LEGEND:
            chip = QLabel(value)
            chip.setStyleSheet(
                f'background: {background}; border: 1px solid #bbb;'
                f' border-radius: 2px; padding: 1px 8px;'
                f' font-size: {theme.FONT["schedule"]}px;'
                f' color: {foreground or theme.SCHEDULE_TEXT};'
            )
            row.addWidget(chip)
            label = QLabel(caption)
            label.setStyleSheet(theme.label_qss('#555', theme.FONT['schedule']))
            row.addWidget(label)

        row.addStretch(1)

        border_title = QLabel('Рамки сверки:')
        border_title.setStyleSheet(
            theme.label_qss('#555', theme.FONT['schedule'], bold=True))
        borders.addWidget(border_title)

        for key, color in theme.CMP_BORDER.items():
            chip = QLabel(theme.CMP_HINT[key])
            chip.setToolTip(CMP_TITLE.get(key, theme.CMP_HINT[key]))
            chip.setStyleSheet(
                f'border: 2px solid {color}; border-radius: 2px; padding: 1px 6px;'
                f' font-size: {theme.FONT["schedule"]}px; color: #555;'
            )
            borders.addWidget(chip)

        borders.addStretch(1)

        self.selection_label = QLabel('')
        self.selection_label.setStyleSheet(
            theme.label_qss(theme.TEXT_HINT, theme.FONT['schedule']))
        borders.addWidget(self.selection_label)

        self.unselect_button = theme.make_button(
            self, '✖ снять', theme.BUTTON_NEUTRAL_BG, text=theme.BUTTON_NEUTRAL_TEXT,
            bold=False, border=f'1px solid {theme.BUTTON_BORDER}',
            font_size=theme.FONT['schedule'], padding='1px 8px')
        self.unselect_button.setToolTip('Снять выделение')
        self.unselect_button.clicked.connect(self._unselect)
        borders.addWidget(self.unselect_button)

    def _build_table(self) -> None:
        """Таблица формы А3 (ScheduleView.jsx:854-943)."""
        self.table = QTableWidget()
        setup_table(self.table, font_size=theme.FONT['schedule'],
                    row_height=ROW_HEIGHT, grid_color=theme.SCHEDULE_CELL_BORDER)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        # Выделение рисуем сами (фон #e3f2fd + рамка), чтобы не спорить
        # с заливками ячеек из файла
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            f'QTableWidget {{ background: white;'
            f' gridline-color: {theme.SCHEDULE_CELL_BORDER};'
            f' border: 1px solid #ccc; border-radius: 4px;'
            f' font-family: "{theme.FONT_FAMILY}";'
            f' font-size: {theme.FONT["schedule"]}px; }}'
            f'QHeaderView::section {{ background: {theme.SCHEDULE_HEADER_BG};'
            f' border: none; border-right: 1px solid {theme.SCHEDULE_CELL_BORDER};'
            f' border-bottom: 1px solid {theme.SCHEDULE_CELL_BORDER};'
            f' padding: 1px 2px; font-weight: normal;'
            f' font-size: {theme.FONT["hint"]}px; }}'
        )
        self.table.setItemDelegate(ScheduleDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)

        # Стиль поднимает минимальную высоту секции шапки до 24px, поэтому
        # «низкие» строки веб-версии (18-19px) задаём уже после него.
        vertical = self.table.verticalHeader()
        vertical.setMinimumSectionSize(12)
        vertical.setDefaultSectionSize(ROW_HEIGHT)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

    # ==================================================================
    # загрузка и отрисовка
    # ==================================================================
    def load(self) -> None:
        """Перечитывает сетку графика за текущий период `state`."""
        if self._loading:
            return
        self._loading = True
        self._busy(True)
        try:
            data = core.load_schedule(self.state.year, self.state.month)
            self._data = data
            self._sync_selection(data)
            self._render()
            self._update_toolbar(data)
        except core.CoreError as exc:
            self._data = None
            self._cells = {}
            self._reset_table()
            self._update_toolbar(None)
            self._message(f'❌ {exc}')
        finally:
            self._busy(False)
            self._loading = False
        self._update_legend()

    def _reset_table(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.clearSpans()
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
        finally:
            self.table.blockSignals(False)
        self._painted_row = None

    def _sync_selection(self, data: dict) -> None:
        """Выделение храним как {строка, ФИО} — как в вебе (ScheduleView.jsx:79-84)."""
        if not self._selected:
            return
        employee = (data.get('employee_rows') or {}).get(str(self._selected['row']))
        if not employee:
            self._selected = None
        elif employee.get('name') != self._selected['name']:
            self._selected = {'row': self._selected['row'], 'name': employee['name']}

    def _render(self) -> None:
        data = self._data or {}
        rows = int(data.get('max_row') or 0)
        cols = int(data.get('max_col') or 0)
        if rows <= 0 or cols <= 0:
            self._reset_table()
            return

        origin_col = int(data.get('origin_col') or 1)
        self._cells = {(int(c['r']), int(c['c'])): c
                       for c in data.get('cells') or []}
        self._days = {int(d['col']): d for d in data.get('days') or []}
        self._weekend_fill = (
            '#' + str(data.get('weekend_fill') or theme.SCHEDULE_WEEKEND_DEFAULT).lstrip('#'))
        employees = data.get('employee_rows') or {}
        selected_row = self._selected['row'] if self._selected else None

        merges = []
        covered: set[tuple[int, int]] = set()
        for merge in data.get('merges') or []:
            r, c = int(merge['r']), int(merge['c'])
            span_rows = max(1, int(merge['rows']))
            span_cols = max(1, int(merge['cols']))
            if span_rows > 1 or span_cols > 1:
                merges.append((r, c, span_rows, span_cols))
            for rr in range(r, r + span_rows):
                for cc in range(c, c + span_cols):
                    if (rr, cc) != (r, c):
                        covered.add((rr, cc))

        vbar = self.table.verticalScrollBar().value()
        hbar = self.table.horizontalScrollBar().value()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearSpans()
            self.table.clear()
            self.table.setRowCount(rows)
            self.table.setColumnCount(cols)
            self.table.setHorizontalHeaderLabels(
                [get_column_letter(origin_col + i - 1) for i in range(1, cols + 1)])

            for r in range(1, rows + 1):
                employee = employees.get(str(r))
                is_selected = bool(employee and selected_row == r)
                for c in range(1, cols + 1):
                    if (r, c) in covered:
                        continue
                    cell = self._cells.get((r, c), {})
                    day = self._days.get(c)
                    bg, fg, border, bold = self._cell_style(cell, day, r, is_selected)
                    widget_item = item(
                        cell.get('v', ''), bold=bold, bg=bg, fg=fg,
                        tooltip=self._tooltip(cell, employee), editable=bool(cell.get('editable')),
                        center=True, border=border, font_size=theme.FONT['schedule'])
                    if cell.get('bd'):
                        widget_item.setData(BD_ROLE, True)
                    self.table.setItem(r - 1, c - 1, widget_item)

            for r, c, span_rows, span_cols in merges:
                if r + span_rows - 1 <= rows and c + span_cols - 1 <= cols:
                    self.table.setSpan(r - 1, c - 1, span_rows, span_cols)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)

        self._painted_row = selected_row
        self._apply_widths()
        self.table.verticalScrollBar().setValue(vbar)
        self.table.horizontalScrollBar().setValue(hbar)

    def _cell_style(self, cell: dict, day: dict | None, r: int,
                    is_selected: bool) -> tuple[str | None, str, str | None, bool]:
        """Фон, цвет текста, цвет рамки и жирность ячейки (ScheduleView.jsx:373-396)."""
        fill = cell.get('fill')
        if fill:
            bg = '#' + str(fill).lstrip('#')
        elif day and day.get('weekend'):
            bg = self._weekend_fill
        elif r <= HEADER_ROWS:
            bg = theme.SCHEDULE_HEADER_BG
        elif is_selected:
            bg = theme.PF_SELECTED_BG
        else:
            bg = None

        fg = cell.get('fc')
        fg = '#' + str(fg).lstrip('#') if fg else theme.SCHEDULE_TEXT

        cmp_key = cell.get('cmp')
        border = theme.CMP_BORDER.get(cmp_key) if cmp_key in theme.CMP_BORDER else None
        if border is None and is_selected:
            border = theme.PF_SELECTED_BORDER

        # в вебе значение непустой ячейки показывается жирным (ScheduleView.jsx:389)
        bold = bool(cell.get('b')) or bool(cell.get('v'))
        return bg, fg, border, bold

    def _tooltip(self, cell: dict, employee: dict | None) -> str | None:
        """Подсказка ячейки: правка + сверка с планом (ScheduleView.jsx:398-407)."""
        hints: list[str] = []
        field = cell.get('ef')
        if field:
            hints.append(EF_TITLE.get(field, 'Кликните, чтобы изменить'))
        elif cell.get('editable'):
            hints.append('Кликните для редактирования')

        cmp_key = cell.get('cmp')
        value = cell.get('v') or '—'
        db_value = cell.get('db') or '—'
        if cmp_key == 'diff':
            hints.append(f'График «{value}» ≠ база «{db_value}»')
        elif cmp_key == 'db_missing':
            hints.append(f'В графике «{value}», в базе плана нет')
        elif cmp_key == 'graf_missing':
            hints.append(f'В базе «{db_value}», в графике пусто')
        elif cmp_key == 'no_employee':
            hints.append('Сотрудника нет в базе')

        extra: list[str] = []
        if cell.get('db'):
            extra.append(f"План в БД: {cell['db']}")
        if cmp_key in theme.CMP_HINT:
            extra.append(f'Сверка: {theme.CMP_HINT[cmp_key]}')

        if not hints and employee:
            hints.append('Кликните, чтобы выбрать сотрудника')
        parts = [' · '.join(hints)] if hints else []
        if extra:
            parts.append(' · '.join(extra))
        return '\n'.join(parts) or None

    def _apply_widths(self) -> None:
        """Ширины колонок: три закреплённых и служебная — фиксированные, дни тянутся."""
        if self._sizing or not self._data:
            return
        cols = self.table.columnCount()
        if cols <= 0:
            return
        self._sizing = True
        try:
            day_cols = [c for c in range(1, cols + 1) if c in self._days]
            fixed = 0
            for c in range(1, cols + 1):
                if c in FIXED_WIDTHS:
                    fixed += FIXED_WIDTHS[c]
                elif c not in self._days:
                    fixed += NOTES_WIDTH

            viewport = self.table.viewport().width()
            if day_cols and viewport > 0:
                each = max(DAY_MIN_WIDTH, int((viewport - fixed) / len(day_cols)))
            else:
                each = DAY_MIN_WIDTH

            for c in range(1, cols + 1):
                if c in FIXED_WIDTHS:
                    width = FIXED_WIDTHS[c]
                elif c in self._days:
                    width = each
                else:
                    width = NOTES_WIDTH
                if self.table.columnWidth(c - 1) != width:
                    self.table.setColumnWidth(c - 1, width)
        finally:
            self._sizing = False

    def resizeEvent(self, event) -> None:                 # noqa: N802 — имя из Qt
        super().resizeEvent(event)
        self._apply_widths()

    # ==================================================================
    # панель инструментов и легенда
    # ==================================================================
    def _update_toolbar(self, data: dict | None) -> None:
        wanted = f'{int(self.state.month):02d}.{int(self.state.year)}'
        self.create_button.setText(f'📄 Создать лист за {wanted}')

        if not data:
            self.sheet_label.setText('📅 График: —')
            self.sheet_warn.setVisible(False)
            self.days_warn.setVisible(False)
            self.diff_label.setText('Расхождений: <b>0</b>')
            self.db_missing_label.setText('Нет плана в БД: <b>0</b>')
            self.ok_label.setText('Совпадает: <b>0</b>')
            return

        sheet = str(data.get('sheet') or '')
        matches = sheet.strip() == wanted
        self.sheet_label.setText(f'📅 График: <b>«{sheet}»</b>')

        self.sheet_warn.setText(f'⚠️ листа за {wanted} нет — показан «{sheet}»')
        self.sheet_warn.setToolTip(
            f'В файле графика нет листа за {wanted}, поэтому показан лист «{sheet}» — '
            f'данные в ячейках относятся к другому месяцу.')
        self.sheet_warn.setVisible(not matches)

        self.create_button.setToolTip(
            f'Создать в файле графика пустой лист за {wanted}: та же форма, сотрудники '
            f'и участки, дни {data.get("month_days")}, смены пустые')

        month_days = int(data.get('month_days') or 0)
        days_in_file = int(data.get('days_in_file') or 0)
        show_days_warn = month_days > 0 and days_in_file != month_days
        if show_days_warn:
            self.days_warn.setText(f'⚠️ дней в файле {days_in_file} из {month_days}')
            self.days_warn.setToolTip(
                f'В файле {days_in_file} колонок-дней, в выбранном месяце {month_days}. '
                f'Колонки для последних дней нужно добавить в файл графика.')
        self.days_warn.setVisible(show_days_warn)

        stats = data.get('stats') or {}
        diff = int(stats.get('diff') or 0)
        diff_color = theme.BUTTON_COLORS['clear'] if diff else theme.BUTTON_COLORS['sheet']
        self.diff_label.setText(
            f'Расхождений: <b style="color:{diff_color}">{diff}</b>')
        self.db_missing_label.setText(
            f'Нет плана в БД: <b style="color:#ef6c00">{int(stats.get("db_missing") or 0)}</b>')
        self.ok_label.setText(
            f'Совпадает: <b style="color:#2e7d32">{int(stats.get("ok") or 0)}</b>')

    def _update_legend(self) -> None:
        if self._selected:
            self.selection_label.setText(f"Выбран: {self._selected['name']}")
            self.selection_label.setStyleSheet(
                theme.label_qss(theme.BUTTON_ACTIVE_BG, theme.FONT['schedule'], bold=True))
            self.unselect_button.setVisible(True)
            self.delete_button.setEnabled(True)
            self.delete_button.setToolTip(
                f"Удалить строку «{self._selected['name']}» из листа графика "
                f'(план и факты в базе останутся)')
        else:
            self.selection_label.setText('клик по строке — выделить сотрудника')
            self.selection_label.setStyleSheet(
                theme.label_qss(theme.TEXT_HINT, theme.FONT['schedule']))
            self.unselect_button.setVisible(False)
            self.delete_button.setEnabled(False)
            self.delete_button.setToolTip(
                'Сначала выберите строку сотрудника — кликните по ней в таблице')

    # ==================================================================
    # выделение и правка
    # ==================================================================
    def _on_cell_clicked(self, row: int, col: int) -> None:
        r = row + 1
        employee = (self._data or {}).get('employee_rows', {}).get(str(r))
        if not employee:
            return
        self._set_selected(r, employee.get('name') or '')

    def _set_selected(self, row: int | None, name: str = '') -> None:
        if row is None:
            self._selected = None
        elif self._selected and self._selected['row'] == row:
            self._selected['name'] = name or self._selected['name']
        else:
            self._selected = {'row': row, 'name': name}
        self._paint_selection()
        self._update_legend()

    def _unselect(self) -> None:
        self._set_selected(None)

    def _paint_selection(self) -> None:
        """Перекрашивает строки выделения без пересборки таблицы.

        Полная перерисовка закрыла бы открытый редактор ячейки, поэтому
        меняются только фон и рамка у ячеек двух строк — прежней и новой.
        """
        if not self._data:
            return
        current = self._selected['row'] if self._selected else None
        if current == self._painted_row:
            return
        rows = [r for r in (self._painted_row, current) if r]
        cols = self.table.columnCount()
        self.table.blockSignals(True)
        try:
            for r in rows:
                is_selected = (r == current)
                for c in range(1, cols + 1):
                    widget_item = self.table.item(r - 1, c - 1)
                    if widget_item is None:
                        continue
                    cell = self._cells.get((r, c), {})
                    bg, _fg, border, _bold = self._cell_style(
                        cell, self._days.get(c), r, is_selected)
                    if bg:
                        widget_item.setBackground(QBrush(qcolor(bg)))
                    else:
                        widget_item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    widget_item.setData(BORDER_ROLE, border)
        finally:
            self.table.blockSignals(False)
        self._painted_row = current

    def _on_edit_toggled(self, checked: bool) -> None:
        theme.style_button(
            self.edit_button,
            theme.BUTTON_ACTIVE_BG if checked else theme.BUTTON_NEUTRAL_BG,
            text=theme.BUTTON_TEXT if checked else theme.BUTTON_NEUTRAL_TEXT,
            bold=checked)
        self._apply_edit_mode()
        if checked:
            self._message('⚠️ Правка включена: изменения пишутся в файл ГРАФИК_ФОРМА A3.xlsx '
                          'и в план БД')
        else:
            self._message('Правка выключена — вкладка работает только на чтение')

    def _apply_edit_mode(self) -> None:
        if self.edit_button.isChecked():
            self.table.setEditTriggers(
                QTableWidget.EditTrigger.CurrentChanged
                | QTableWidget.EditTrigger.DoubleClicked
                | QTableWidget.EditTrigger.EditKeyPressed)
        else:
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def _on_item_changed(self, changed) -> None:
        """Правка ячейки разрешена только при включённом переключателе."""
        if self._loading or self._saving or not self.edit_button.isChecked():
            return
        row, col = changed.row() + 1, changed.column() + 1
        value = changed.text().strip()
        field = (self._cells.get((row, col)) or {}).get('ef')
        # сохранение откладываем: сейчас Qt ещё закрывает редактор ячейки
        QTimer.singleShot(0, lambda: self._save_cell(row, col, value, field))

    def _save_cell(self, row: int, col: int, value: str, field: str | None) -> None:
        self._saving = True
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._busy(True)
        try:
            if field:
                result = core.save_schedule_employee_field(
                    row, field, value, self.state.year, self.state.month)
            else:
                result = core.save_schedule_cell(
                    row, col, value, self.state.year, self.state.month)
            if result.get('status') == 'error':
                self._message(f"❌ {result.get('message')}")
            else:
                self._message(f"✅ {result.get('message')}")
                self.state.plan_changed()          # как onPlanChanged в вебе
        except core.CoreError as exc:
            self._message(f'❌ {exc}')
        finally:
            self._busy(False)
            self._saving = False
            self._apply_edit_mode()
        self.load()

    # ==================================================================
    # действия вкладки
    # ==================================================================
    def _create_sheet(self) -> None:
        """📄 Создать лист за MM.YYYY (ядро само отвечает, если лист уже есть)."""
        year, month = self.state.year, self.state.month
        wanted = f'{int(month):02d}.{int(year)}'
        self._busy(True)
        try:
            result = core.create_schedule_sheet(year, month)
        except core.CoreError as exc:
            result = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if result.get('status') == 'error':
            message = str(result.get('message') or 'не удалось создать лист')
            self._message(f'❌ {message}')
            box = QMessageBox(self)
            box.setWindowTitle('Лист графика')
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f'Лист за {wanted} создать не удалось')
            box.setInformativeText(message)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.button(QMessageBox.StandardButton.Ok).setText('Понятно')
            box.exec()
            return

        self._message(f"✅ {result.get('message')}")
        self.load()

    def _delete_employee(self) -> None:
        """🗑️ Удалить из графика — только для выбранной строки."""
        if not self._selected:
            self._message('⚠️ Сначала выберите сотрудника — кликните по его строке в таблице')
            return
        year, month = self.state.year, self.state.month
        row = int(self._selected['row'])
        name = self._selected['name']
        sheet = str((self._data or {}).get('sheet') or '')

        dialog = _AskDialog(
            self,
            title=f'🗑️ Удалить «{name}» из графика {sheet}?',
            window_title='Удалить из графика',
            color=theme.BUTTON_COLORS['remove_from_schedule'],
            lines=[
                (f'• строка сотрудника будет удалена из листа <b>«{sheet}»</b>, '
                 f'остальные строки сдвинутся вверх', 'text'),
                ('• если он был в группе участка, объединение сохранится и название '
                 'участка не потеряется', 'text'),
                (f'Сотрудник и его план в базе <b>останутся</b> — в План-Факте ничего '
                 f'не изменится. Если нужно убрать и план, воспользуйтесь кнопкой '
                 f'«🗑️ Удалить (неделя)» на странице План-Факт.', 'muted'),
            ],
            confirm_text='Да, удалить из графика',
            confirm_color=theme.BUTTON_COLORS['remove_from_schedule'],
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._busy(True)
        try:
            result = core.delete_schedule_employee(row, year, month)
        except core.CoreError as exc:
            result = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if result.get('status') == 'error':
            self._message(f"❌ {result.get('message')}")
            return
        self._selected = None
        self._message(f"✅ {result.get('message')}")
        self.state.plan_changed()
        self.load()

    def _ask_shifts(self) -> None:
        """⚙️ Расставить смены: сначала сводка, потом запись."""
        year, month = self.state.year, self.state.month
        self._busy(True)
        try:
            summary = core.schedule_shifts_summary(year, month)
        except core.CoreError as exc:
            summary = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if summary.get('status') == 'error':
            self._message(f"❌ {summary.get('message')}")
            return

        by_value = summary.get('by_value') or {}

        def count(key: str) -> int:
            """Сколько дней выбранной смены будет заполнено (ключи бывают int и str)."""
            return int(by_value.get(key) or by_value.get(int(key)) or 0)

        filled = int(summary.get('filled') or 0)
        lines = [
            (f'• ритм взят из листа <b>«{summary.get("source")}»</b>: <b>11</b> — 2 через 2, '
             f'<b>9</b> и <b>8</b> — 5 через 2 (у каждого свой сдвиг)', 'text'),
            (f'• будет заполнено <b>{filled}</b> дней у <b>{summary.get("employees")}</b> '
             f'сотрудников: 11 — {count("11")}, 9 — {count("9")}, 8 — {count("8")}', 'text'),
            ('• заполняются <b>только пустые дни</b>: уже проставленные смены, отпуска '
             'и больничные не меняются', 'text'),
            ('• смены сразу попадут в план базы и появятся в План-Факте', 'text'),
        ]
        skipped = summary.get('skipped') or []
        if skipped:
            lines.append(('Пропущены (нет смен в «{0}»): {1}'
                          .format(summary.get('source'), ', '.join(map(str, skipped))), 'warn'))

        dialog = _AskDialog(
            self,
            title=f'⚙️ Расставить смены за {summary.get("target")}?',
            window_title='Расстановка смен',
            color=theme.BUTTON_COLORS['shifts'],
            lines=lines,
            confirm_text='Да, расставить',
            confirm_color=theme.BUTTON_COLORS['shifts'],
            confirm_enabled=filled > 0,
            width=560,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._busy(True)
        try:
            result = core.fill_schedule_shifts(year, month)
        except core.CoreError as exc:
            result = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if result.get('status') == 'error':
            self._message(f"❌ {result.get('message')}")
            return
        self._message(f"✅ {result.get('message')}")
        self.state.plan_changed()
        self.load()

    def _ask_clear(self) -> None:
        """🧹 Очистить: вопросы про смены / план / заметки + автоотмена через 5 с."""
        year, month = self.state.year, self.state.month
        self._busy(True)
        try:
            summary = core.schedule_clear_summary(year, month)
        except core.CoreError as exc:
            summary = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if summary.get('status') == 'error':
            self._message(f"❌ {summary.get('message')}")
            return

        month_text = str(summary.get('month'))
        sheet = str(summary.get('sheet') or '')
        shifts = int(summary.get('shifts') or 0)
        plans = int(summary.get('plans') or 0)
        employees = int(summary.get('employees') or 0)
        notes = int(summary.get('notes') or 0)
        sheet_part = (f'• Смены в листе <b>«{sheet or month_text}»</b>: будет очищено '
                      f'<b>{shifts}</b> дней'
                      + ('' if sheet else ' (листа за этот месяц в файле нет)'))
        plan_part = (f'• План в базе: будет удалено записей <b>{plans}</b>'
                     + (f' (по {employees} сотрудникам)' if employees else ''))
        note_part = f'• Колонка «Изменения в графике»: значений <b>{notes}</b>'

        dialog = _AskDialog(
            self,
            title=f'🧹 Очистить данные за {month_text}?',
            window_title='Очистка данных графика',
            color=theme.BUTTON_COLORS['clear'],
            lines=[
                (sheet_part, 'text'),
                (plan_part, 'text'),
                (note_part, 'text'),
                ('Сотрудники, оформление и выходные остаются на месте — таблица станет '
                 'пустой, как новая форма.', 'muted'),
                ('Отменить это действие нельзя.', 'danger'),
            ],
            confirm_text='Да, очистить',
            confirm_color=theme.BUTTON_COLORS['clear'],
            checks=[
                (f'Очистить смены в листе ({shifts} дней)', True),
                (f'Удалить план в базе ({plans} записей)', True),
                (f'Очистить примечания ({notes} значений)', True),
            ],
            countdown=5,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._message('Очистка отменена — данные не изменялись')
            return

        clear_shifts, clear_plan, clear_notes = dialog.checked()
        self._busy(True)
        try:
            result = core.clear_schedule(year, month, clear_plan=clear_plan,
                                         clear_notes=clear_notes, clear_shifts=clear_shifts)
        except core.CoreError as exc:
            result = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if result.get('status') == 'error':
            self._message(f"❌ {result.get('message')}")
            return
        self._message(f"✅ {result.get('message')}")
        self.state.plan_changed()
        self.load()

    def _add_employee(self) -> None:
        """➕ Добавить в график и базу."""
        name = self.name_edit.text().strip()
        if not name:
            self._message('❌ Укажите ФИО сотрудника')
            return
        position = self.position_edit.text().strip()
        section = self.section_edit.text().strip()

        self._busy(True)
        try:
            result = core.add_schedule_employee(
                name, position, section, self.state.year, self.state.month)
        except core.CoreError as exc:
            result = {'status': 'error', 'message': str(exc)}
        finally:
            self._busy(False)

        if result.get('status') == 'error':
            self._message(f"❌ {result.get('message')}")
            return
        self.name_edit.clear()
        self.position_edit.clear()
        self.section_edit.clear()
        self._message(f"✅ {result.get('message')}")
        self.state.plan_changed()
        self.load()

    # ==================================================================
    # выгрузки
    # ==================================================================
    def _export(self, mode: str) -> None:
        """📥 Как есть / 📥 Только ритмы — сборка xlsx в отдельном потоке."""
        if self._exporting:
            return
        year, month = self.state.year, self.state.month
        self._exporting = mode
        self._busy(True)
        self._set_export_enabled(False)

        worker = _Worker(lambda: core.export_schedule(year, month, mode), self)
        worker.done.connect(lambda result: self._export_done(mode, result))
        worker.failed.connect(self._export_failed)
        worker.finished.connect(lambda: self._worker_finished(worker))
        self._workers.append(worker)
        worker.start()

    def _export_done(self, mode: str, result) -> None:
        self._exporting = None
        self._busy(False)
        self._set_export_enabled(True)

        path, _ = QFileDialog.getSaveFileName(
            self, 'Сохранить выгрузку графика',
            os.path.join(self._download_folder(), result.filename),
            'Excel (*.xlsx)')
        if not path:
            self._message('⚠️ Выгрузка отменена — файл не сохранён')
            return
        try:
            result.save(path)
        except OSError as exc:
            self._message(f'❌ Не удалось выгрузить: {exc}')
            return
        self._message('✅ Выгружено: ' + ('только ритмы 11/9/8' if mode == 'rhythm'
                                          else 'график как есть'))

    def _export_failed(self, message: str) -> None:
        self._exporting = None
        self._busy(False)
        self._set_export_enabled(True)
        self._message(f'❌ Не удалось выгрузить: {message}')

    def _worker_finished(self, worker: _Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def _set_export_enabled(self, enabled: bool) -> None:
        self.export_actual_button.setEnabled(enabled)
        self.export_rhythm_button.setEnabled(enabled)

    @staticmethod
    def _download_folder() -> str:
        folder = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation)
        if folder and os.path.isdir(folder):
            return folder
        return str(Path.home())

    # ==================================================================
    # служебное
    # ==================================================================
    def _on_period_changed(self, _year: int, _month: int) -> None:
        self.load()

    def _message(self, text: str) -> None:
        """Сообщение вкладки: своя цветная строка + общая строка приложения."""
        self.message_bar.show_message(text)
        self._message_timer.start(MESSAGE_MS)
        self.state.say(text, STATUS_MS)

    def _clear_message(self) -> None:
        self.message_bar.clear_message()

    def _busy(self, active: bool) -> None:
        if active:
            self._busy_depth += 1
            if self._busy_depth == 1:
                QGuiApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
                self.loading_label.setVisible(True)
            return
        self._busy_depth = max(0, self._busy_depth - 1)
        if self._busy_depth == 0:
            QGuiApplication.restoreOverrideCursor()
            self.loading_label.setVisible(False)


__all__ = ['ScheduleTab']
