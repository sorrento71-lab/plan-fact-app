"""Пути к данным в собранном exe.

Ядро ищет свои файлы рядом с собой:

    database.py       → <каталог database.py>/plan_fact.db
    export_timesheet  → <каталог модуля>/табель.xlsx
    schedule_grid.py  → <на уровень выше каталога модуля>/ГРАФИК_ФОРМА A3.xlsx

В исходниках это ровно то, что нужно: `backend/plan_fact.db` и файл графика в
корне проекта. Но в собранном приложении модули лежат внутри exe, и все три
пути начинают указывать в служебную папку `_internal` — база и график
оказались бы недоступны для правки (и незаметны для пользователя).

Поэтому в frozen-режиме пути явно переводятся на папку рядом с exe:

    dist/План-Факт/
        План-Факт.exe
        _internal/...              ← код, библиотеки, seed/ с исходными данными
        backend/plan_fact.db       ← рабочая база (прав редактируется)
        backend/табель.xlsx
        ГРАФИК_ФОРМА A3.xlsx       ← рабочая книга графика
        ГРАФИК_ФОРМА A3.backup.xlsx

При первом запуске данные копируются из `_internal/seed` (это исходные файлы
проекта на момент сборки). Дальше приложение работает только с копиями рядом
с exe — пересборка их не затирает.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine

# Что копируем рядом с exe при первом запуске (путь внутри seed → место рядом с exe)
SEED_FILES = [
    ('backend/plan_fact.db', 'backend/plan_fact.db'),
    ('backend/табель.xlsx', 'backend/табель.xlsx'),
    ('ГРАФИК_ФОРМА A3.xlsx', 'ГРАФИК_ФОРМА A3.xlsx'),
    ('ГРАФИК_ФОРМА A3.backup.xlsx', 'ГРАФИК_ФОРМА A3.backup.xlsx'),
]


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def data_root() -> Path:
    """Папка с данными: рядом с exe либо корень проекта при запуске из исходников."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def seed_root() -> Path | None:
    """Каталог с исходными данными внутри сборки (None при запуске из исходников)."""
    if not is_frozen():
        return None
    internal = getattr(sys, '_MEIPASS', None)
    return Path(internal) / 'seed' if internal else None


def unpack_seed(verbose: bool = True) -> list[Path]:
    """Копирует исходные данные рядом с exe, если их там ещё нет."""
    seed = seed_root()
    if seed is None or not seed.is_dir():
        return []

    root = data_root()
    copied: list[Path] = []
    for source_rel, target_rel in SEED_FILES:
        source = seed / source_rel
        target = root / target_rel
        if not source.exists():
            continue
        if target.exists() and target.stat().st_size > 0:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
        if verbose:
            print(f'[первый запуск] подготовлен файл: {target}')
    return copied


def configure(database, schedule_grid) -> dict:
    """Переводит пути ядра на папку рядом с exe. Возвращает словарь путей.

    Вызывать один раз, сразу после импорта модулей ядра и ДО первого обращения
    к базе. При запуске из исходников ничего не делает.
    """
    if not is_frozen():
        return {
            'frozen': False,
            'root': data_root(),
            'db': Path(database.DB_PATH),
            'schedule': Path(schedule_grid.SCHEDULE_FILE),
            # None — модуль выгрузки сам возьмёт шаблон рядом с собой
            'template': None,
        }

    unpack_seed()
    root = data_root()

    db_path = root / 'backend' / 'plan_fact.db'
    schedule_file = root / 'ГРАФИК_ФОРМА A3.xlsx'
    backup_file = root / 'ГРАФИК_ФОРМА A3.backup.xlsx'
    template = root / 'backend' / 'табель.xlsx'

    db_path.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)

    # база: путь + движок + фабрика сессий (объект SessionLocal общий,
    # поэтому его достаточно перенастроить)
    database.DB_PATH = str(db_path)
    database.engine = create_engine(
        f'sqlite:///{db_path}', connect_args={'check_same_thread': False})
    database.SessionLocal.configure(bind=database.engine)

    # книга графика и её резервная копия
    schedule_grid.ROOT_DIR = str(root)
    schedule_grid.SCHEDULE_FILE = str(schedule_file)
    schedule_grid.BACKUP_FILE = str(backup_file)

    return {
        'frozen': True,
        'root': root,
        'db': db_path,
        'schedule': schedule_file,
        'template': template,
    }


__all__ = ['is_frozen', 'data_root', 'seed_root', 'unpack_seed', 'configure', 'SEED_FILES']
