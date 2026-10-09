# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-spec: прототип «План-Факт» (вариант А), режим one-dir.

Логика упаковки продиктована тем, как backend/ ищет свои файлы
(менять backend/ нельзя, поэтому раскладка данных повторяет исходную):

  backend/database.py      → БД рядом с собой:   <data_root>/backend/plan_fact.db
  backend/export_timesheet → шаблон рядом с собой: <data_root>/backend/табель.xlsx
  backend/schedule_grid.py → ROOT_DIR = родитель backend/:
                             <data_root>/ГРАФИК_ФОРМА A3.xlsx (+ .backup.xlsx)

В one-dir сборке PyInstaller 6 данные кладутся в <папка exe>/_internal,
и sys._MEIPASS указывает именно туда — launcher.py берёт этот путь как
data_root, поэтому раскладка совпадает с исходной.

launcher.py подхватывает backend/ через sys.path (исходные .py лежат как
данные), поэтому байт-код backend в архив не компилируется и relative-пути
внутри backend работают без правок.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH)              # C:\plan-fact-app\desktop-a
PROJECT_ROOT = SPEC_DIR.parent         # C:\plan-fact-app

BACKEND_DIR = PROJECT_ROOT / 'backend'
WEBAPP_DIR = SPEC_DIR / 'webapp'
SCHEDULE_XLSX = PROJECT_ROOT / 'ГРАФИК_ФОРМА A3.xlsx'
SCHEDULE_BACKUP = PROJECT_ROOT / 'ГРАФИК_ФОРМА A3.backup.xlsx'

EXE_NAME = 'План-Факт'

# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------
def backend_data():
    """Весь backend/, кроме кэша байт-кода и логов (в сборке они не нужны)."""
    items = []
    for path in sorted(BACKEND_DIR.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(BACKEND_DIR)
        if '__pycache__' in rel.parts or path.suffix == '.pyc':
            continue
        if path.name in ('uvicorn.log',):
            continue
        items.append((str(path), str(Path('backend') / rel.parent)))
    return items


datas = [(str(WEBAPP_DIR), 'webapp')]
datas += backend_data()
if SCHEDULE_XLSX.is_file():
    datas.append((str(SCHEDULE_XLSX), '.'))
if SCHEDULE_BACKUP.is_file():
    datas.append((str(SCHEDULE_BACKUP), '.'))

# ---------------------------------------------------------------------------
# Скрытые импорты: backend/ подключается в рантайме через sys.path (модули
# лежат на диске как данные), поэтому PyInstaller по коду их не видит, а значит
# не видит и их зависимости. Явно перечисляем всё, что нужно backend-у.
#
# Важно: сами модули backend (app, database, models, schedule_grid, ...) в сборку
# как байт-код НЕ включаются — иначе поменялись бы их __file__, а вместе с ними
# пути к plan_fact.db, табель.xlsx и ГРАФИК_ФОРМА A3.xlsx.
# ---------------------------------------------------------------------------
hiddenimports = [
    # бэкенд (подхватывается с диска; перечислено для наглядности)
    'app',
    'database',
    'models',
    'parse_schedule',
    'parse_journal',
    'plan_fact_export',
    'planfact_service',
    'schedule_grid',
    'shift_codes',
    'export_timesheet',
    'medcheck_export',
    # чтение/запись таблиц и документов
    'pandas',
    'openpyxl',
    'et_xmlfile',
    'xlrd',
    'docx',
    'lxml',
    # окно
    'webview',
    'clr_loader',
]


def _submodules(*packages: str, skip: tuple[str, ...] = ()) -> list[str]:
    """Все подмодули пакетов: у fastapi/starlette нет хуков PyInstaller, и без
    этого часть подмодулей (например fastapi.middleware.cors) в сборку не попадает.
    """
    names: list[str] = []
    for package in packages:
        for name in collect_submodules(package):
            if not name.startswith(skip):
                names.append(name)
    return names


hiddenimports += _submodules(
    'fastapi', 'starlette', 'uvicorn', 'anyio', 'pydantic', 'pydantic_core',
    'sqlalchemy', 'openpyxl', 'multipart', 'h11', 'click', 'webview',
    skip=('sqlalchemy.testing', 'openpyxl.tests'),
)
# pandas: read_excel тянет pandas.io.excel динамически, поэтому нужен весь пакет
hiddenimports += _submodules('pandas', skip=('pandas.tests',))
hiddenimports += ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
                  'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
                  'uvicorn.lifespan.off', 'webview.platforms.edgechromium',
                  'webview.platforms.winforms']

hiddenimports = sorted(set(hiddenimports))

excludes = [
    'tkinter', 'matplotlib', 'scipy', 'IPython', 'jupyter', 'notebook',
    'pytest', 'PyInstaller', 'setuptools._distutils',
    'pandas.tests', 'numpy.tests', 'sqlalchemy.testing',
]

a = Analysis(
    [str(SPEC_DIR / 'launcher.py')],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # отдельная программа без консольного окна;
                            # ошибки показываются MessageBox и пишутся в launcher.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=EXE_NAME,
)
