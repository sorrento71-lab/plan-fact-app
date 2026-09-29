"""Главное окно прототипа Б: шапка, вкладки и общая строка сообщений.

Раскладка повторяет веб-версию (App.js / Header.js):
    [ ◀ месяц ▶ ]  [ вкладки-кнопки ]            [📤 Журнал][📤 График][🔄 Обновить]
    [ цветная строка сообщения ]
    [ содержимое выбранной вкладки ]
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import core
from . import theme
from .common import AppState
from .meal_tab import MealTab
from .planfact_tab import PlanFactTab
from .schedule_tab import ScheduleTab
from .timesheet_tab import TimesheetTab
from .widgets import MessageBar, MonthSelector, PageTabs, Panel

# Порядок вкладок дословно как в веб-версии (PageTabs.js:3-8)
PAGES = [
    ('planfact', '📊 План-Факт'),
    ('timesheet', '📋 Табель'),
    ('meal', '🍽️ Питание'),
    ('schedule', '📅 График'),
]


class CallWorker(QThread):
    """Долгая операция (разбор файла, выгрузка) вне потока интерфейса."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, func, parent=None) -> None:
        super().__init__(parent)
        self._func = func

    def run(self) -> None:                    # noqa: D102
        try:
            self.done.emit(self._func())
        except Exception as exc:              # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self._loaded: set[str] = set()
        self._workers: list[CallWorker] = []
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_message)

        self.setWindowTitle('План-Факт')
        self.resize(1600, 950)
        self.setMinimumSize(1100, 640)
        self.setStyleSheet(
            f'QMainWindow {{ background: {theme.PAGE_BG}; }}'
            f'QWidget {{ font-family: "{theme.FONT_FAMILY}";'
            f' font-size: {theme.FONT["base"]}px; }}'
        )

        self.pages: dict[str, QWidget] = {}
        self.stack = QStackedWidget()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)
        layout.addWidget(self._build_header())
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._build_pages()

        self.state.status.connect(self._show_message)
        self.state.periodChanged.connect(self._on_period_changed)
        self.state.refreshRequested.connect(self._on_refresh)
        self.state.tabRequested.connect(self.tabs.set_current)

        self.tabs.set_current('planfact')          # вкладка по умолчанию — план-факт
        self.stack.setCurrentWidget(self.pages['planfact'])
        self._ensure_loaded('planfact')

    # ------------------------------------------------------------------
    # построение интерфейса
    # ------------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = Panel(background=theme.HEADER_BG, border=theme.HEADER_BORDER)
        header.row.setContentsMargins(10, 5, 10, 5)
        header.row.setSpacing(14)

        self.month_selector = MonthSelector(compact=True)
        self.month_selector.periodChanged.connect(self.state.set_period)
        header.row.addWidget(self.month_selector)

        self.tabs = PageTabs()
        self.tabs.changed.connect(self._on_tab_changed)
        header.row.addWidget(self.tabs)

        header.row.addStretch(1)

        self.journal_button = self._upload_button('📤 Журнал', 'upload_journal')
        self.journal_button.setToolTip('Загрузить журнал из СКУД (выгрузка tc-tmp*.xls)')
        self.journal_button.clicked.connect(self._upload_journal)
        header.row.addWidget(self.journal_button)

        self.schedule_button = self._upload_button('📤 График', 'upload_schedule')
        self.schedule_button.setToolTip('Загрузить график смен (ГРАФИК_ФОРМА A3.xlsx)')
        self.schedule_button.clicked.connect(self._upload_schedule)
        header.row.addWidget(self.schedule_button)

        self.refresh_button = theme.make_button(
            self, '🔄 Обновить', theme.BUTTON_COLORS['refresh'])
        self.refresh_button.clicked.connect(self.state.refreshRequested.emit)
        header.row.addWidget(self.refresh_button)

        wrapper = QWidget()
        column = QVBoxLayout(wrapper)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(header)

        # Две строки сообщений, как в Header.js:75-76
        self.upload_message = MessageBar()
        self.status_message = MessageBar()
        column.addWidget(self.upload_message)
        column.addWidget(self.status_message)
        return wrapper

    def _upload_button(self, title: str, kind: str):
        return theme.make_button(self, title, theme.BUTTON_COLORS[kind])

    def _build_pages(self) -> None:
        self.planfact_page = PlanFactTab(self.state)
        self.timesheet_page = TimesheetTab(self.state)
        self.meal_page = MealTab(self.state)
        self.schedule_page = ScheduleTab(self.state)

        for tab_id, _title in PAGES:
            page = getattr(self, f'{tab_id}_page')
            self.pages[tab_id] = page
            self.stack.addWidget(page)

    # ------------------------------------------------------------------
    # переключение вкладок и загрузка данных
    # ------------------------------------------------------------------
    def _on_tab_changed(self, tab_id: str) -> None:
        page = self.pages.get(tab_id)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self._ensure_loaded(tab_id)

    def _ensure_loaded(self, tab_id: str) -> None:
        if tab_id in self._loaded:
            return
        page = self.pages[tab_id]
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page.load()
            self._loaded.add(tab_id)
        finally:
            QGuiApplication.restoreOverrideCursor()

    def _on_period_changed(self, year: int, month: int) -> None:
        self._loaded.clear()
        self._ensure_loaded(self.tabs.current())

    def _on_refresh(self) -> None:
        current = self.tabs.current()
        self._loaded.clear()
        self._ensure_loaded(current)

    def reload_all(self) -> None:
        """Перезагрузить все вкладки (после загрузки файлов или правки данных)."""
        self._loaded.clear()
        self._ensure_loaded(self.tabs.current())

    # ------------------------------------------------------------------
    # сообщения
    # ------------------------------------------------------------------
    def _show_message(self, payload: str) -> None:
        text, _, timeout = payload.partition('\x00')
        self.status_message.show_message(text)
        try:
            delay = int(timeout)
        except ValueError:
            delay = 3000
        self._message_timer.start(delay)

    def _clear_message(self) -> None:
        self.status_message.clear_message()

    # ------------------------------------------------------------------
    # загрузка файлов
    # ------------------------------------------------------------------
    def _upload_journal(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Журнал из СКУД', str(core.PROJECT_ROOT), 'Excel (*.xls *.xlsx)')
        if not path:
            return
        self.upload_message.show_message('⏳ Загрузка журнала...')
        self._run_background(lambda: core.import_journal(path), self._journal_loaded)

    def _journal_loaded(self, result: dict) -> None:
        message = (f"✅ Добавлено: {result.get('added', 0)}, "
                   f"обновлено: {result.get('updated', 0)}")
        self.upload_message.show_message(message)
        self.state.say(message, 5000)
        self.reload_all()

    def _upload_schedule(self) -> None:
        default = str(Path(core.PROJECT_ROOT) / 'ГРАФИК_ФОРМА A3.xlsx')
        path, _ = QFileDialog.getOpenFileName(
            self, 'Файл графика (форма А3)', default, 'Excel (*.xlsx *.xls)')
        if not path:
            return
        self.upload_message.show_message('⏳ Загрузка графика...')
        self._run_background(lambda: core.import_schedule(path), self._schedule_loaded)

    def _schedule_loaded(self, result: dict) -> None:
        message = (f"✅ Загружено: {result.get('employees', 0)} сотрудников, "
                   f"{result.get('records', 0)} записей плана")
        synced = result.get('schedule') or {}
        if synced.get('message'):
            message += f". {synced['message']}"
        self.upload_message.show_message(message)
        self.state.say(message, 5000)
        self.reload_all()

    # ------------------------------------------------------------------
    # фон
    # ------------------------------------------------------------------
    def _run_background(self, func, on_done) -> None:
        worker = CallWorker(func, self)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(lambda: self._worker_finished(worker))
        self._workers.append(worker)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        worker.start()

    def _worker_finished(self, worker: CallWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        QGuiApplication.restoreOverrideCursor()

    def _on_worker_failed(self, message: str) -> None:
        self.upload_message.show_message(f'❌ Ошибка: {message}')
        self.state.say(f'❌ Ошибка: {message}')

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:        # noqa: N802 — имя из Qt
        for worker in list(self._workers):
            worker.wait(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def selftest(self) -> int:
        """Проверка без участия человека: грузим все вкладки и выходим."""
        problems: list[str] = []
        for tab_id, title in PAGES:
            page = self.pages[tab_id]
            try:
                page.load()
                print(f'[selftest] вкладка «{title}»: загружена')
            except Exception as exc:              # noqa: BLE001
                traceback.print_exc()
                problems.append(f'{title}: {exc}')

        try:
            checks = {
                'план-факт': self.planfact_page.table.rowCount(),
                'табель': self.timesheet_page.table.rowCount(),
                'график': self.schedule_page.table.rowCount(),
                'питание': self.meal_page.list_widget.count(),
            }
            for name, count in checks.items():
                print(f'[selftest] {name}: {count} строк')
                if not count:
                    problems.append(f'{name}: пусто')
        except Exception as exc:                  # noqa: BLE001
            problems.append(f'проверка таблиц: {exc}')

        if problems:
            print('[selftest] ПРОБЛЕМЫ: ' + '; '.join(problems))
            return 1
        print('[selftest] OK: все вкладки работают с реальным ядром')
        return 0


__all__ = ['MainWindow']
