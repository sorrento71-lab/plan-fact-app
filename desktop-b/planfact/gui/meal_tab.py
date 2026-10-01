"""Вкладка «Питание» — перенос `frontend/src/MealExport.jsx` на PySide6.

Состав блока сверху вниз повторяет веб-версию (`MealExport.jsx:185-358`):

    заголовок 🍽️ Выгрузка питания
    строка сообщения (свои цвета питания: рамки #c3e6cb / #f5c6cb / #ffc107)
    📅 Дата: [поле с календарём] [🔍 Показать сотрудников]
    [🌅 Кафе утро (165 руб.)] [🍽️ Кафе обед (460 руб.)] 👥 N чел.
    карточка со списком в две колонки (или плейсхолдер, пока список не показан)

Данные берутся только из `planfact.core` (`meal_preview`, `export_meal`) — там живут
те же правила отбора, что и в выгрузке: отпуск «О» и «б/с» не попадают,
«Корнеева Елена» исключена, подмены имён нет. FastAPI и HTTP не используются.

Цвета и размеры — из `ДИЗАЙН_СПЕЦ.md` (разделы 1.6, 1.10, 1.11, 2, 7) через `theme`.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics,
                           QPainter, QPalette, QPen)
from PySide6.QtWidgets import (QDateEdit, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from .. import core
from . import theme, widgets
from .common import AppState

# --------------------------------------------------------------------------
# Тексты и размеры (MealExport.jsx)
# --------------------------------------------------------------------------
TITLE_TEXT = '🍽️ Выгрузка питания'
DATE_LABEL_TEXT = '📅 Дата:'
SHOW_BUTTON_TEXT = '🔍 Показать сотрудников'
SHOW_BUTTON_LOADING_TEXT = '⏳ Загрузка...'
PLACEHOLDER_TEXT = 'Нажмите "Показать сотрудников" для отображения списка'
DATE_FORMAT = 'dd.MM.yyyy'

#: Кнопки выгрузки: (ключ для core.export_meal, подпись, ключ цвета в theme.BUTTON_COLORS)
MEAL_BUTTONS = (
    ('morning', '🌅 Кафе утро (165 руб.)', 'meal_morning'),
    ('lunch', '🍽️ Кафе обед (460 руб.)', 'meal_lunch'),
)

#: Дословные подписи для диалогов (MealExport.jsx:131)
MEAL_TITLES = {
    'morning': 'Кафе утро (165 руб.)',
    'lunch': 'Кафе обед (460 руб.)',
}

#: Рамки строки сообщений — только у «Питания» (MealExport.jsx:178-180)
MESSAGE_BORDERS = {
    'success': '#c3e6cb',
    'error': '#f5c6cb',
    'warning': '#ffc107',
}
MESSAGE_FONT = 14                 # MealExport.jsx:200
MESSAGE_TIMEOUT_MS = 3000         # как договаривались для вкладки; в вебе 5000

#: Геометрия строки списка: padding 5px 0 + строка 16px + нижняя граница 1px
ROW_HEIGHT = 32
ROW_GAP = 6                       # gap: 6px 30px (MealExport.jsx:319)
COLUMN_GAP = 30
INDEX_WIDTH = 35                  # min-width номера (MealExport.jsx:334)
INDEX_GAP = 10                    # gap между номером и ФИО (MealExport.jsx:329)
NAME_COLOR = '#333'               # цвет ФИО в вебе — базовый цвет текста
CARD_PADDING_H = 18               # padding: 12px 18px у карточки списка


@contextmanager
def tolerant_stdout():
    """Не терять запрос из-за отладочных `print`-ов ядра.

    `backend/planfact_service.py` печатает эмодзи в stdout. Когда stdout — канал
    или файл с кодировкой не UTF-8 (например cp1251), `print` падает с
    `UnicodeEncodeError` и уносит с собой весь запрос: список остаётся пустым,
    хотя данные есть. На время вызова ядра разрешаем заменять непереводимые
    символы, затем возвращаем прежнее поведение. В обычном окне (`pythonw.exe`)
    печатать некуда и проблемы нет — обёртка тогда ничего не меняет.
    """
    patched: list[tuple[object, str]] = []
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:               # None под pythonw.exe или не TextIO
            continue
        errors = getattr(stream, 'errors', 'strict')
        try:
            reconfigure(errors='replace')
        except (ValueError, OSError):
            continue
        patched.append((stream, errors))
    try:
        yield
    finally:
        for stream, errors in patched:
            try:
                stream.reconfigure(errors=errors)
            except (ValueError, OSError):
                pass


class MealMessageBar(widgets.MessageBar):
    """Строка сообщений вкладки «Питание».

    В вебе у этой вкладки свои рамки у баннера и шрифт 14px вместо общих 11px
    (`MealExport.jsx:176-204`), поэтому базовый `MessageBar` переопределён.
    """

    def show_message(self, text: str, kind: str | None = None) -> None:   # noqa: D102
        if not text:
            self.clear_message()
            return
        kind = kind or theme.message_kind(text)
        background, color = theme.MESSAGE_COLORS[kind]
        border = MESSAGE_BORDERS.get(kind, MESSAGE_BORDERS['warning'])
        self.setStyleSheet(
            f'background: {background}; color: {color};'
            f' border: 1px solid {border}; border-radius: 4px; padding: 8px 15px;'
            f' font-size: {MESSAGE_FONT}px; font-family: "{theme.FONT_FAMILY}";'
        )
        self.setText(text)
        self.setVisible(True)


class MealRowDelegate(QStyledItemDelegate):
    """Строка списка «{номер}. {ФИО}» как в вебе (`MealExport.jsx:322-339`).

    Номер — `#999`, 14px, вес 500, ширина 35px; ФИО — 16px; под строкой
    разделитель `1px #f0f0f0`. Штатная отрисовка QListWidget так не умеет,
    поэтому строка рисуется вручную.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index_font = QFont(theme.FONT_FAMILY)
        self._index_font.setPixelSize(14)
        self._index_font.setWeight(QFont.Weight.Medium)
        self._name_font = QFont(theme.FONT_FAMILY)
        self._name_font.setPixelSize(theme.FONT['meal_row'])

    def sizeHint(self, option, index) -> QSize:           # noqa: N802, D102
        # В режиме значков QListView ужимает прямоугольник элемента до sizeHint
        # и центрирует его, поэтому строке нужно отдавать размер клетки сетки:
        # иначе линия-разделитель уезжает, а длинные ФИО обрезаются.
        view = self.parent()
        grid = view.gridSize() if hasattr(view, 'gridSize') else QSize()
        if not grid.isEmpty():
            return grid
        return QSize(300, ROW_HEIGHT + ROW_GAP)

    def paint(self, painter, option, index) -> None:      # noqa: D102, N802
        painter.save()
        # Клетка сетки шире колонки на COLUMN_GAP: в вебе зазор `gap` находится
        # между колонками, а у QListView шаг сетки задаёт клетку целиком.
        content = QRect(option.rect.left(), option.rect.top(),
                        max(1, option.rect.width() - COLUMN_GAP), ROW_HEIGHT - 1)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        painter.setFont(self._index_font)
        painter.setPen(QPen(QColor(theme.MEAL_INDEX_TEXT)))
        painter.drawText(content, flags, f'{index.row() + 1}.')

        painter.setFont(self._name_font)
        painter.setPen(QPen(QColor(NAME_COLOR)))
        name_rect = content.adjusted(INDEX_WIDTH + INDEX_GAP, 0, 0, 0)
        name = str(index.data(Qt.ItemDataRole.UserRole) or '')
        text = QFontMetrics(self._name_font).elidedText(
            name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, flags, text)

        painter.setPen(QPen(QColor(theme.MEAL_ROW_SEPARATOR)))
        line_y = content.top() + ROW_HEIGHT - 1
        painter.drawLine(content.left(), line_y, content.right(), line_y)
        painter.restore()


class MealListWidget(QListWidget):
    """Список питания — карточка `1px solid #ddd`, две колонки `1fr 1fr`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        # В вебе строки не выделяются и не подсвечиваются — это простые div-ы.
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setStyleSheet(
            f'QListWidget {{ background: white;'
            f' border: 1px solid {theme.MEAL_CARD_BORDER}; border-radius: 4px;'
            f' padding: 12px {CARD_PADDING_H}px; outline: none; }}'
        )
        self.setItemDelegate(MealRowDelegate(self))
        self._update_grid()

    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:                 # noqa: N802, D102
        super().resizeEvent(event)
        self._update_grid()

    def viewportEvent(self, event) -> bool:               # noqa: N802, D102
        # Полоса прокрутки меняет ширину поля — сетку пересчитываем и по этому событию
        if event.type() == QEvent.Type.Resize:
            self._update_grid()
        return super().viewportEvent(event)

    def showEvent(self, event) -> None:                   # noqa: N802, D102
        super().showEvent(event)
        self._update_grid()

    def _update_grid(self) -> None:
        """Две колонки `1fr 1fr` с зазором `gap: 30px`.

        Шаг сетки QListView задаёт клетку целиком, поэтому клетка — половина
        поля, а зазор отводится в её правой части (`MealRowDelegate.paint`).
        Ширина считается от самой карточки, а не от поля просмотра: иначе
        появление полосы прокрутки ломает раскладку на одну колонку.
        """
        scrollbar = self.verticalScrollBar().sizeHint().width()
        usable = self.width() - 2 - 2 * CARD_PADDING_H - scrollbar
        cell = max(2 * (200 + COLUMN_GAP), max(usable, 460) // 2)
        size = QSize(cell, ROW_HEIGHT + ROW_GAP)
        if size != self.gridSize():
            self.setGridSize(size)


class MealPlaceholder(QLabel):
    """Плейсхолдер «Нажмите …»: 17px `#999`, рамка `1px dashed #ddd`.

    Рамка рисуется вручную: стилевая `border: dashed` в Qt сглаживается и вместо
    `#ddd` даёт полупрозрачные `#ebebeb`/`#f8f8f8`, то есть не тот цвет, что в вебе.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f'color: {theme.TEXT_FAINT}; background: white;'
            f' font-size: 17px; font-family: "{theme.FONT_FAMILY}";'
        )

    def paintEvent(self, event) -> None:                  # noqa: N802, D102
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor(theme.MEAL_CARD_BORDER))
        pen.setWidth(1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class MealTab(QWidget):
    """Вкладка «Питание»: список сотрудников на дату и выгрузка в Excel."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._preview_shown = False
        self._exporting = False

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_message)

        self._build_ui()
        self._connect_signals()
        self._set_preview_visible(False)

    # ------------------------------------------------------------------
    # интерфейс
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Фон страницы в вебе белый (App.js:21) — как на вкладке «Табель»
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.PAGE_BG))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 8, 0, 4)
        column.setSpacing(12)                 # marginBottom: 12px у каждого блока

        title = QLabel(TITLE_TEXT)
        title.setStyleSheet(theme.label_qss(theme.MEAL_TITLE, theme.FONT['meal_title'],
                                            bold=True))
        column.addWidget(title)

        self.message_bar = MealMessageBar()
        column.addWidget(self.message_bar)

        column.addLayout(self._build_date_row())
        column.addLayout(self._build_export_row())

        self.list_widget = MealListWidget()
        column.addWidget(self.list_widget, 1)

        self.placeholder = MealPlaceholder(PLACEHOLDER_TEXT)
        column.addWidget(self.placeholder, 1)

    def _build_date_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)                    # gap: 10px (MealExport.jsx:208)

        label = QLabel(DATE_LABEL_TEXT)
        label.setStyleSheet(theme.label_qss('#333', theme.FONT['meal_label'], bold=True))
        row.addWidget(label)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)             # поле с календарём
        self.date_edit.setDisplayFormat(DATE_FORMAT)      # ДД.ММ.ГГГГ
        self.date_edit.setStyleSheet(
            f'QDateEdit {{ background: white;'
            f' border: 1px solid {theme.MEAL_INPUT_BORDER}; border-radius: 4px;'
            f' padding: 6px 12px; font-size: {theme.FONT["meal_label"]}px;'
            f' font-family: "{theme.FONT_FAMILY}"; }}'
        )
        row.addWidget(self.date_edit)

        self.show_button = theme.make_button(
            self, SHOW_BUTTON_TEXT, theme.BUTTON_COLORS['meal_show'],
            bold=False, font_size=theme.FONT['meal_label'], padding='6px 20px')
        row.addWidget(self.show_button)
        row.addStretch(1)
        return row

    def _build_export_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.meal_buttons: dict[str, QPushButton] = {}

        for meal_type, caption, color_key in MEAL_BUTTONS:
            button = theme.make_button(self, caption, theme.BUTTON_COLORS[color_key],
                                       font_size=theme.FONT['meal_button'],
                                       padding='8px 28px')
            button.clicked.connect(lambda _=False, kind=meal_type: self._export(kind))
            row.addWidget(button)
            self.meal_buttons[meal_type] = button

        self.counter_label = QLabel('')
        self.counter_label.setStyleSheet(
            theme.label_qss(theme.MEAL_COUNTER_TEXT, theme.FONT['meal_button'], bold=True))
        row.addSpacing(4)                     # marginLeft: 4px (MealExport.jsx:299)
        row.addWidget(self.counter_label)
        row.addStretch(1)
        return row

    def _connect_signals(self) -> None:
        self.show_button.clicked.connect(self._on_show_clicked)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        self.state.periodChanged.connect(self._on_period_changed)
        self.state.refreshRequested.connect(self._on_external_refresh)

    # ------------------------------------------------------------------
    # публичный интерфейс вкладки
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Загрузить вкладку: список на выбранную дату.

        Вызывается главным окном при показе вкладки и в режиме `--selftest`,
        поэтому список заполняется сразу, без нажатия кнопки.
        """
        self._preview(announce=False)

    def current_date(self) -> date:
        """Выбранная дата как `datetime.date`."""
        qdate = self.date_edit.date()
        return date(qdate.year(), qdate.month(), qdate.day())

    # ------------------------------------------------------------------
    # предпросмотр списка
    # ------------------------------------------------------------------
    def _on_show_clicked(self) -> None:
        self._preview(announce=True)

    def _on_date_changed(self, _qdate: QDate) -> None:
        """Дата меняется — список на экране пересчитываем (в вебе нужен клик)."""
        if self._preview_shown:
            self._preview(announce=False)

    def _on_period_changed(self, _year: int, _month: int) -> None:
        if self._preview_shown:
            self._preview(announce=False)

    def _on_external_refresh(self) -> None:
        """Кнопка 🔄 Обновить в шапке (MealExport.jsx:117-122)."""
        if self._preview_shown:
            self._preview(announce=False)

    def _preview(self, *, announce: bool) -> None:
        target = self.current_date()
        self._set_loading(True)
        try:
            with tolerant_stdout():
                names = core.meal_preview(target)
        except Exception as exc:              # noqa: BLE001 — CoreError и прочее
            self._reset_preview()
            self._message(f'❌ Ошибка: {exc}')
            return
        finally:
            self._set_loading(False)

        if not names:
            self._reset_preview()
            self._message(f'⚠️ Нет сотрудников с данными на {target:%d.%m.%Y}')
            return

        self._fill_list(names)
        if announce:
            self._message(f'✅ Найдено {len(names)} сотрудников')

    def _fill_list(self, names: list[str]) -> None:
        self.list_widget.clear()
        for number, name in enumerate(names, start=1):
            item = QListWidgetItem(f'{number}. {name}')
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)
        self.counter_label.setText(f'👥 {len(names)} чел.')
        self._preview_shown = True
        self._set_preview_visible(True)

    def _reset_preview(self) -> None:
        self.list_widget.clear()
        self.counter_label.clear()
        self._preview_shown = False
        self._set_preview_visible(False)

    def _set_preview_visible(self, shown: bool) -> None:
        self.list_widget.setVisible(shown)
        self.placeholder.setVisible(not shown)
        self.counter_label.setVisible(shown)
        for button in self.meal_buttons.values():
            button.setVisible(shown)

    def _set_loading(self, flag: bool) -> None:
        """Кнопка предпросмотра на время запроса: `⏳ Загрузка...` + disabled."""
        self.show_button.setEnabled(not flag)
        self.show_button.setText(SHOW_BUTTON_LOADING_TEXT if flag else SHOW_BUTTON_TEXT)

    # ------------------------------------------------------------------
    # выгрузка
    # ------------------------------------------------------------------
    def _export(self, meal_type: str) -> None:
        if self._exporting:
            return
        title = MEAL_TITLES.get(meal_type, meal_type)
        target = self.current_date()

        self._set_exporting(True)
        try:
            try:
                with tolerant_stdout():
                    result = core.export_meal(target, meal_type)
            except core.CoreError as exc:
                # «Нет сотрудников с данными на …» — предупреждение, не ошибка
                if 'Нет сотрудников' in str(exc):
                    self._message(f'⚠️ Нет сотрудников с данными на {target:%d.%m.%Y}')
                else:
                    self._message(f'❌ Ошибка: {exc}')
                return
            except Exception as exc:          # noqa: BLE001
                self._message(f'❌ Ошибка: {exc}')
                return

            path = self._ask_save_path(result.filename)
            if not path:
                return
            try:
                saved = result.save(path)
            except OSError as exc:
                self._message(f'❌ Ошибка: {exc}')
                return
            self._message(f'✅ Файл сохранён: {saved}')
            self._offer_open(saved, title)
        finally:
            self._set_exporting(False)

    def _ask_save_path(self, filename: str) -> str:
        """Диалог сохранения: предлагаем папку «Загрузки» и имя из ядра."""
        downloads = Path.home() / 'Downloads'
        folder = downloads if downloads.is_dir() else Path.home()
        path, _filter = QFileDialog.getSaveFileName(
            self, 'Сохранить выгрузку питания', str(folder / filename), 'Excel (*.xlsx)')
        if path and not Path(path).suffix:
            path = f'{path}.xlsx'
        return path

    def _offer_open(self, path: Path, title: str) -> None:
        answer = QMessageBox.question(
            self, 'Выгрузка питания',
            f'{title}\n\nФайл сохранён:\n{path}\n\nОткрыть файл?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        """Открыть сохранённый файл системным приложением."""
        target = str(path)
        try:
            opener = getattr(os, 'startfile', None)     # Windows
            if opener is not None:
                opener(target)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        except OSError as exc:
            self._message(f'❌ Ошибка: {exc}')

    def _set_exporting(self, flag: bool) -> None:
        self._exporting = flag
        for button in self.meal_buttons.values():
            button.setEnabled(not flag)

    # ------------------------------------------------------------------
    # сообщения
    # ------------------------------------------------------------------
    def _message(self, text: str, kind: str | None = None) -> None:
        """Сообщение в локальную строку вкладки и в общую строку окна."""
        self.message_bar.show_message(text, kind)
        self.state.say(text, MESSAGE_TIMEOUT_MS)
        self._hide_timer.start(MESSAGE_TIMEOUT_MS)

    def _hide_message(self) -> None:
        self.message_bar.clear_message()


__all__ = ['MealTab', 'MealMessageBar', 'MealListWidget', 'MealRowDelegate',
           'MealPlaceholder']
