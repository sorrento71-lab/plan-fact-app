# -*- mode: python ; coding: utf-8 -*-
"""Сборка настольного «План-Факт» (вариант Б) в отдельную папку с exe.

Особенности:
* backend/ подключается как каталог импортов (pathex) — модули ядра написаны
  «плоско» (import models, from database import ...), поэтому их надо явно
  указать и в pathex, и в hiddenimports;
* исходные данные (база, шаблон табеля, книга графика) кладутся в _internal/seed:
  при первом запуске frozen.py скопирует их рядом с exe, чтобы базу и график
  можно было править и чтобы пересборка их не затирала;
* fastapi/starlette/uvicorn/pydantic исключены — настольной версии они не нужны.
"""
from pathlib import Path

HERE = Path(SPECPATH)                 # desktop-b
PROJECT = HERE.parent                 # корень проекта

SEED_FILES = [
    (PROJECT / 'backend' / 'plan_fact.db', 'seed/backend'),
    (PROJECT / 'backend' / 'табель.xlsx', 'seed/backend'),
    (PROJECT / 'ГРАФИК_ФОРМА A3.xlsx', 'seed'),
    (PROJECT / 'ГРАФИК_ФОРМА A3.backup.xlsx', 'seed'),
]

datas = [(str(source), target) for source, target in SEED_FILES if source.exists()]
missing = [str(source) for source, _ in SEED_FILES if not source.exists()]

a = Analysis(
    [str(HERE / 'run.py')],
    pathex=[str(HERE), str(PROJECT / 'backend')],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # модули ядра (плоские импорты из backend/)
        'database', 'models', 'planfact_service', 'schedule_grid',
        'parse_schedule', 'parse_journal', 'export_timesheet', 'plan_fact_export',
        # используются внутри ядра
        'openpyxl', 'openpyxl.styles', 'openpyxl.worksheet.properties',
        'sqlalchemy', 'pandas', 'xlrd',
        # интерфейс
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'fastapi', 'starlette', 'uvicorn', 'pydantic', 'pydantic_core',
        'httpx', 'anyio', 'multipart', 'webview', 'tkinter',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='План-Факт',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # окно консоли не нужно: это настольная программа
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='План-Факт',
)
