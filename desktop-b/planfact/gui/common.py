"""Общие помощники вкладок: состояние приложения, ячейки и вид таблиц.

Вид таблиц приведён к веб-версии: тонкие серые границы, отсутствие
чередования строк, маленькие шрифты, цветные шапки — см. `ДИЗАЙН_СПЕЦ.md`.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (QHeaderView, QLineEdit, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem)

from . import theme

# Роль, в которой хранится цвет рамки ячейки (рамки сверки в «Графике»)
BORDER_ROLE = Qt.ItemDataRole.UserRole + 1

TIME_PATTERN = r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$'


def qcolor(value: str | QColor | None) -> QColor | None:
    """Приводит HEX из Excel/настроек к QColor ('RRGGBB' или 'AARRGGBB')."""
    if value is None:
        return None
    if isinstance(value, QColor):
        return value
    text = str(value).strip().lstrip('#')
    if len(text) == 8:                    # ARGB из темы Excel
        text = text[2:]
    if len(text) != 6:
        return None
    color = QColor(f'#{text}')
    return color if color.isValid() else None


class BorderDelegate(QStyledItemDelegate):
    """Рисует рамку вокруг ячейки — аналог `inset 0 0 0 2px` из веб-версии."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        value = index.data(BORDER_ROLE)
        color = qcolor(value)
        if color is None:
            return
        pen = QPen(color)
        pen.setWidth(2)
        painter.save()
        painter.setPen(pen)
        painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()


class TimeEditDelegate(QStyledItemDelegate):
    """Правка времени с маской ЧЧ:ММ — как поле ввода в веб-версии."""

    def createEditor(self, parent, option, index):        # noqa: N802
        editor = QLineEdit(parent)
        editor.setMaxLength(5)
        editor.setValidator(QRegularExpressionValidator(
            QRegularExpression(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$|^$'), editor))
        editor.setStyleSheet(
            f'QLineEdit {{ background: transparent; border: none;'
            f' color: {theme.PF_TIME_TEXT}; font-weight: bold; }}'
        )
        editor.textChanged.connect(lambda text, field=editor: self._mask(field, text))
        return editor

    @staticmethod
    def _mask(editor: QLineEdit, text: str) -> None:
        """Автоматическая подстановка двоеточия (useCellEditing.js:110-125)."""
        cleaned = ''.join(ch for ch in text if ch.isdigit() or ch == ':')
        if cleaned != text:
            editor.setText(cleaned)
            return
        if len(cleaned) == 5 and ':' not in cleaned:
            cleaned = f'{cleaned[:2]}:{cleaned[2:]}'
            editor.setText(cleaned)
        elif len(cleaned) == 3 and cleaned[2] != ':':
            cleaned = f'{cleaned[:2]}:{cleaned[2]}'
            editor.setText(cleaned)


def item(text, *, bold: bool = False, bg: str | QColor | None = None,
         fg: str | QColor | None = None, tooltip: str | None = None,
         editable: bool = False, center: bool = False,
         border: str | None = None, font_size: int | None = None) -> QTableWidgetItem:
    """Ячейка таблицы с оформлением из веб-версии."""
    cell = QTableWidgetItem('' if text is None else str(text))
    if bg is not None:
        color = qcolor(bg)
        if color is not None:
            cell.setBackground(QBrush(color))
    if fg is not None:
        color = qcolor(fg)
        if color is not None:
            cell.setForeground(QBrush(color))
    if bold or font_size:
        font = cell.font()
        if bold:
            font.setBold(True)
        if font_size:
            font.setPointSizeF(font_size * 0.75)   # px → pt (как в вебе px)
        cell.setFont(font)
    if tooltip:
        cell.setToolTip(tooltip)
    if center:
        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if border:
        cell.setData(BORDER_ROLE, border)
    if not editable:
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return cell


def setup_table(table: QTableWidget, *, font_size: int | None = None,
                row_height: int = 22, grid_color: str = theme.CELL_BORDER,
                vertical_header: bool = False) -> None:
    """Вид таблицы как в вебе: без чередования строк, тонкая серая сетка."""
    table.setAlternatingRowColors(False)
    table.setShowGrid(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.verticalHeader().setVisible(vertical_header)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setStretchLastSection(False)
    table.setWordWrap(False)
    table.setStyleSheet(
        f'QTableWidget {{ background: white; gridline-color: {grid_color};'
        f' border: 1px solid {theme.TABLE_BORDER}; border-radius: 4px;'
        f' font-family: "{theme.FONT_FAMILY}";'
        f' font-size: {font_size or theme.FONT["base"]}px; }}'
        f'QHeaderView::section {{ background: {theme.TS_HEADER_BG}; border: none;'
        f' border-right: 1px solid {grid_color}; border-bottom: 1px solid {grid_color};'
        f' padding: 1px 2px; font-weight: normal; }}'
    )
    table.setItemDelegate(BorderDelegate(table))


class AppState(QObject):
    """Выбранный период и общая шина сообщений/обновлений."""

    periodChanged = Signal(int, int)      # year, month
    weekChanged = Signal(int)             # week_id
    status = Signal(str)                  # сообщение для MessageBar
    refreshRequested = Signal()           # кнопка 🔄 Обновить в шапке
    planChanged = Signal()                # данные плана изменились (график → план-факт)
    tabRequested = Signal(str)            # переход на вкладку по id (кнопка «◀ Назад»)

    def __init__(self) -> None:
        super().__init__()
        today = date.today()
        self.year = today.year
        self.month = today.month
        self.week_id = 0

    # ------------------------------------------------------------------
    def set_period(self, year: int, month: int) -> None:
        if (year, month) == (self.year, self.month):
            self.periodChanged.emit(year, month)
            return
        self.year, self.month = year, month
        self.week_id = 0                  # при смене месяца неделя сбрасывается
        self.periodChanged.emit(year, month)

    def set_week(self, week_id: int) -> None:
        if week_id == self.week_id:
            return
        self.week_id = week_id
        self.weekChanged.emit(week_id)

    def say(self, message: str, timeout_ms: int = 3000) -> None:
        """Показать сообщение в цветной строке (в вебе — 3 или 5 секунд)."""
        self.status.emit(f'{message}\x00{timeout_ms}')

    def plan_changed(self) -> None:
        self.planChanged.emit()

    def open_tab(self, tab_id: str) -> None:
        """Перейти на вкладку по id: 'planfact' | 'timesheet' | 'meal' | 'schedule'."""
        self.tabRequested.emit(tab_id)


__all__ = ['AppState', 'BorderDelegate', 'BORDER_ROLE', 'TimeEditDelegate',
           'TIME_PATTERN', 'item', 'qcolor', 'setup_table', 'theme']
