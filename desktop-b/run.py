"""Точка входа настольного приложения «План-Факт» (вариант Б, PySide6).

Запуск:
    run.bat                 обычный запуск с окном
    run.bat --selftest      проверка без диалогов: грузит все вкладки и выходит
    run.bat --month 9 --year 2026   открыть конкретный период

В собранном exe окна консоли нет, поэтому и ошибки, и отчёт --selftest
дополнительно пишутся в файл planfact-desktop.log рядом с программой.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QMessageBox     # noqa: E402


def log_path() -> Path:
    """Файл журнала: рядом с exe либо в корне проекта при запуске из исходников."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'planfact-desktop.log'
    return Path(__file__).resolve().parent / 'planfact-desktop.log'


def log(message: str) -> None:
    """Пишем и в stdout (если он есть), и в файл — в exe консоли нет."""
    print(message)
    try:
        with log_path().open('a', encoding='utf-8') as handle:
            handle.write(f'{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n')
    except OSError:
        pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='План-Факт: настольная версия')
    parser.add_argument('--selftest', action='store_true',
                        help='загрузить все вкладки без диалогов и выйти (код 0/1)')
    parser.add_argument('--month', type=int, choices=range(1, 13),
                        help='месяц, который открыть при старте')
    parser.add_argument('--year', type=int, help='год, который открыть при старте')
    return parser.parse_args(argv)


def show_fatal(error: BaseException) -> None:
    """Показать ошибку запуска — в exe иначе её просто негде увидеть."""
    text = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    log('КРИТИЧЕСКАЯ ОШИБКА:\n' + text)
    try:
        box = QMessageBox()
        box.setWindowTitle('План-Факт — ошибка запуска')
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText('Не удалось запустить приложение.')
        box.setDetailedText(text)
        box.exec()
    except Exception:                       # noqa: BLE001 — окна может ещё не быть
        pass


def run(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.selftest and sys.stdout is None:
        # В собранном exe консоли нет: все print() превращаются в ничто.
        # На время самопроверки направляем их в файл журнала.
        try:
            sys.stdout = log_path().open('a', encoding='utf-8')
        except OSError:
            pass

    from planfact.gui.main_window import MainWindow
    from planfact import core

    app = QApplication(sys.argv[:1])
    app.setApplicationName('План-Факт')

    log(f'Запуск. Ядро: {core.BACKEND_DIR}')
    log(f'База: {core.PATHS["db"]}')
    log(f'График: {core.PATHS["schedule"]}')

    window = MainWindow()
    if args.year and args.month:
        window.month_selector.set_period(args.year, args.month)
        window.state.set_period(args.year, args.month)

    if args.selftest:
        code = window.selftest()
        log('SELFTEST: ' + ('OK' if code == 0 else 'ЕСТЬ ПРОБЛЕМЫ'))
        window.close()
        return code

    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv if argv is not None else sys.argv[1:])
    except BaseException as error:            # noqa: BLE001 — показываем всё
        show_fatal(error)
        return 1


if __name__ == '__main__':
    sys.exit(main())
