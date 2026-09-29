"""Снимает PNG-скриншоты всех вкладок прототипа Б средствами самого Qt.

Зачем: посмотреть, как выглядит интерфейс, не открывая окно вручную.

Запуск:
    ..\\.venv-desktop\\Scripts\\python.exe make_screenshots.py
Результат: папка screenshots/ рядом с этим файлом.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtWidgets import QApplication                  # noqa: E402

from planfact.gui.main_window import PAGES, MainWindow      # noqa: E402

OUT_DIR = HERE / 'screenshots'


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.resize(1600, 950)
    window.show()
    app.processEvents()

    saved = 0
    for index, (tab_id, title) in enumerate(PAGES, start=1):
        window.tabs.set_current(tab_id)     # переключение само подгружает вкладку
        app.processEvents()
        page = window.pages[tab_id]
        page.load()
        app.processEvents()

        name = f'{index}_{title}.png'.replace(' ', '_')
        path = OUT_DIR / name
        window.grab().save(str(path))
        saved += 1
        print(f'сохранено: {name}')

    window.close()
    print(f'итого файлов: {saved} в {OUT_DIR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
