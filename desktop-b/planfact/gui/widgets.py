"""Виджеты каркаса: строка сообщения, вкладки, выбор месяца, легенда.

Всё повторяет веб-версию: вкладки в ней — не Material-вкладки, а обычные
кнопки с цветным фоном активной, поэтому здесь тоже кнопки, а не QTabWidget
(QTabWidget не умеет красить каждую вкладку своим цветом).
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import theme

MONTH_NAMES = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
               'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']


class MessageBar(QLabel):
    """Цветная строка-уведомление: ✅ успех, ❌ ошибка, иначе предупреждение."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setVisible(False)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def show_message(self, text: str) -> None:
        if not text:
            self.clear()
            self.setVisible(False)
            return
        background, color = theme.MESSAGE_COLORS[theme.message_kind(text)]
        self.setStyleSheet(
            f'background: {background}; color: {color}; font-size: {theme.FONT["message"]}px;'
            f' border-radius: 3px; padding: 2px 8px; font-family: "{theme.FONT_FAMILY}";'
        )
        self.setText(text)
        self.setVisible(True)

    def clear_message(self) -> None:
        self.clear()
        self.setVisible(False)


class PageTabs(QWidget):
    """Ряд вкладок-кнопок веб-версии: 📊 План-Факт · 📋 Табель · 🍽️ Питание · 📅 График."""

    changed = Signal(str)          # id вкладки: planfact / timesheet / meal / schedule

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f'background: {theme.TAB_BAR_BG}; border-radius: 4px;')
        self._buttons: dict[str, QPushButton] = {}
        self._current = theme.TABS[0][0]

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)

        for tab_id, title, color in theme.TABS:
            button = QPushButton(title, self)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                'QPushButton {'
                f' background: transparent; color: {theme.TAB_INACTIVE_TEXT};'
                f' font-size: {theme.FONT["tab"]}px; font-weight: normal;'
                ' border: none; border-radius: 3px; padding: 4px 12px; }'
                f'QPushButton:checked {{ background: {color}; color: white; font-weight: bold; }}'
            )
            button.clicked.connect(lambda _=False, key=tab_id: self.set_current(key))
            row.addWidget(button)
            self._buttons[tab_id] = button

        self._buttons[self._current].setChecked(True)

    def set_current(self, tab_id: str) -> None:
        if tab_id not in self._buttons:
            return
        for key, button in self._buttons.items():
            button.setChecked(key == tab_id)
        if tab_id != self._current:
            self._current = tab_id
            self.changed.emit(tab_id)

    def current(self) -> str:
        return self._current

    def order(self) -> list[str]:
        return [tab_id for tab_id, _, _ in theme.TABS]


class MonthSelector(QWidget):
    """Переключатель месяца: ◀ [список] ▶ — как MonthSelector.js."""

    periodChanged = Signal(int, int)

    def __init__(self, compact: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        today = date.today()
        self._year = today.year
        self._month = today.month
        self._loading = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6 if compact else 8)

        if not compact:
            label = QLabel('📅 Месяц:')
            label.setStyleSheet(theme.label_qss('#333', theme.FONT['month_label'], bold=True))
            row.addWidget(label)

        arrow_qss = (
            'QPushButton { background: #fff; border: 1px solid #c6cdd6; border-radius: 3px;'
            f' font-size: {theme.FONT["month"]}px; padding: {"2px 9px" if compact else "2px 10px"}; }}'
            'QPushButton:hover { background: #f0f2f5; }'
        )
        self.prev_button = QPushButton('◀')
        self.prev_button.setStyleSheet(arrow_qss)
        self.prev_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_button.clicked.connect(lambda: self.step(-1))
        row.addWidget(self.prev_button)

        self.combo = QComboBox()
        self.combo.setStyleSheet(
            'QComboBox {'
            f' background: #f5f7fa; border: 1px solid #c6cdd6; border-radius: 3px;'
            f' padding: {"2px 6px" if compact else "3px 8px"}; font-size: {theme.FONT["month"]}px;'
            ' font-weight: bold; color: #1565c0; }'
            'QComboBox QAbstractItemView { font-size: 13px; }'
        )
        self.combo.currentIndexChanged.connect(self._on_combo)
        row.addWidget(self.combo)

        self.next_button = QPushButton('▶')
        self.next_button.setStyleSheet(arrow_qss)
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.clicked.connect(lambda: self.step(1))
        row.addWidget(self.next_button)

        self.counter = QLabel('')
        if not compact:
            self.counter.setStyleSheet(theme.label_qss(theme.TEXT_MUTED,
                                                       theme.FONT['month_counter']))
            row.addWidget(self.counter)

        self._build_items()

    # ------------------------------------------------------------------
    def _months_around_today(self) -> list[tuple[int, int]]:
        """Последние 3 и следующие 3 месяца относительно сегодня (constants.js:23-46)."""
        today = date.today()
        months: list[tuple[int, int]] = []
        for shift in range(-3, 4):
            month = today.month - 1 + shift
            year = today.year
            while month < 0:
                month += 12
                year -= 1
            while month > 11:
                month -= 12
                year += 1
            months.append((year, month + 1))
        return months

    def _build_items(self) -> None:
        self._loading = True
        months = self._months_around_today()
        if (self._year, self._month) not in months:
            months.append((self._year, self._month))
            months.sort()
        self.combo.clear()
        for year, month in months:
            self.combo.addItem(f'{MONTH_NAMES[month - 1]} {year}', (year, month))
        self._sync_combo()
        self._loading = False

    def _sync_combo(self) -> None:
        index = self.combo.findData((self._year, self._month))
        if index >= 0 and index != self.combo.currentIndex():
            self._loading = True
            self.combo.setCurrentIndex(index)
            self._loading = False

    def _on_combo(self, index: int) -> None:
        if self._loading or index < 0:
            return
        data = self.combo.itemData(index)
        if not data:
            return
        self._year, self._month = data
        self.periodChanged.emit(self._year, self._month)

    # ------------------------------------------------------------------
    def step(self, delta: int) -> None:
        month = self._month + delta
        year = self._year
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self._year, self._month = year, month
        self._build_items()
        self.periodChanged.emit(year, month)

    def set_period(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        self._build_items()

    def period(self) -> tuple[int, int]:
        return self._year, self._month

    def set_record_count(self, count: int) -> None:
        if not self.counter.isVisible() and not self.counter.text():
            self.counter.setVisible(True)
        self.counter.setText(f'({count} записей)' if count > 0 else '(нет данных)')


class Legend(QWidget):
    """Легенда статусов под таблицей план-факта (Legend.js)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(6)

        title = QLabel('📌 Легенда:')
        title.setStyleSheet(theme.label_qss('#333', theme.FONT['legend'], bold=True))
        row.addWidget(title)

        for status, color in theme.STATUS_COLORS.items():
            chip = QLabel(status)
            chip.setStyleSheet(
                f'background: {color}; border: 1px solid #ccc; border-radius: 2px;'
                f' padding: 1px 4px; font-size: {theme.FONT["legend_chip"]}px;'
                f' color: {theme.status_fg(status)};'
            )
            row.addWidget(chip)

        hint = QLabel('🖱️ Клик по времени или этапам для редактирования')
        hint.setStyleSheet(theme.label_qss(theme.TEXT_MUTED, theme.FONT['legend_chip']))
        row.addWidget(hint)

        filled = QLabel('🟡 Заполнено')
        filled.setStyleSheet(
            'background: #fff9c4; border: 1px solid #ccc; border-radius: 2px;'
            f' padding: 1px 4px; font-size: {theme.FONT["legend_chip"]}px;'
        )
        row.addWidget(filled)

        selected = QLabel('🔵 Выделена')
        selected.setStyleSheet(
            'background: #e3f2fd; border: 2px solid #1565c0; border-radius: 2px;'
            f' padding: 1px 4px; font-size: {theme.FONT["legend_chip"]}px; color: #1565c0;'
        )
        row.addWidget(selected)
        row.addStretch(1)


class Panel(QFrame):
    """Панель в стиле веб-версии: светлый фон, тонкая рамка, скругление 6px."""

    def __init__(self, parent: QWidget | None = None, *, background: str | None = None,
                 border: str | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(theme.panel_qss(background or theme.ACTION_ROW_BG,
                                           border or theme.ACTION_ROW_BORDER))
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(10, 4, 10, 4)
        self.row.setSpacing(6)


def separator(parent: QWidget | None = None) -> QFrame:
    """Вертикальный разделитель в панели действий."""
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFixedSize(1, 20)
    line.setStyleSheet(f'background: {theme.SEPARATOR}; border: none;')
    return line


def empty_state(parent: QWidget | None = None, text: str = '') -> QLabel:
    label = QLabel(text, parent)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(theme.label_qss(theme.TEXT_FAINT, theme.FONT['base']))
    return label


class Column(QWidget):
    """Простая вертикальная раскладка с настройкой отступов."""

    def __init__(self, parent: QWidget | None = None, *, margins: tuple = (0, 0, 0, 0),
                 spacing: int = 4) -> None:
        super().__init__(parent)
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(*margins)
        self.col.setSpacing(spacing)
