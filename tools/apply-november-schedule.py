"""Вносит новый файл графика в рабочий — с ноября.

Что делает:
  1. бэкапит новый файл и текущее состояние базы;
  2. делает новый файл рабочим (ГРАФИК_ФОРМА A3.xlsx), убирая служебный «Лист2»;
  3. импортирует план за ноябрь 2026 (октябрь и ранее не трогает);
  4. показывает результат.
"""
import os
import shutil
import sys
from datetime import date, datetime

sys.path.insert(0, r'C:\plan-fact-app\backend')

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

from openpyxl import load_workbook

import models
import parse_schedule as ps
import planfact_service as pf
import schedule_grid as sg
from database import SessionLocal

ROOT = r'C:\plan-fact-app'
NEW_FILE = os.path.join(ROOT, 'ГРАФИК_ФОРМА ноябрь.xlsx')
WORK_FILE = sg.SCHEDULE_FILE
BACKUP_DIR = os.path.join(ROOT, 'backup')
STAMP = datetime.now().strftime('%Y-%m-%d_%H%M')

os.makedirs(BACKUP_DIR, exist_ok=True)

# ---------- 1. бэкапы ----------
new_backup = os.path.join(BACKUP_DIR, f'ГРАФИК_ФОРМА ноябрь (внесён {STAMP}).xlsx')
shutil.copy2(NEW_FILE, new_backup)
print('бэкап нового файла:', os.path.basename(new_backup))

db_backup = os.path.join(BACKUP_DIR, f'plan_fact (перед графиком ноября {STAMP}).db')
shutil.copy2(os.path.join(ROOT, 'backend', 'plan_fact.db'), db_backup)
print('бэкап базы:', os.path.basename(db_backup))

# ---------- 2. новый файл становится рабочим ----------
if os.path.exists(WORK_FILE):
    shutil.copy2(WORK_FILE, os.path.join(BACKUP_DIR, f'ГРАФИК_ФОРМА A3 (прежний {STAMP}).xlsx'))
shutil.copy2(NEW_FILE, WORK_FILE)
print('рабочий файл создан:', os.path.basename(WORK_FILE))

wb = load_workbook(WORK_FILE)
junk = [name for name in wb.sheetnames if name.strip().lower() in ('лист2', 'sheet2')]
for name in junk:
    del wb[name]
    print(f'убран служебный лист: {name!r}')
if junk:
    wb.save(WORK_FILE)
print('листы рабочего файла:', [n.strip() for n in load_workbook(WORK_FILE).sheetnames])

# ---------- 3. импорт плана за ноябрь ----------
db = SessionLocal()
try:
    before = db.query(models.Plan).filter(
        models.Plan.date >= date(2026, 11, 1), models.Plan.date <= date(2026, 11, 30)).count()
    result = ps.parse_schedule_file(WORK_FILE, db, year=2026, month=11)
    print('импорт ноября:', {k: v for k, v in result.items() if k != 'message'})
    after = db.query(models.Plan).filter(
        models.Plan.date >= date(2026, 11, 1), models.Plan.date <= date(2026, 11, 30)).count()

    sync = sg.apply_plan_to_schedule(db, 2026, 11)
    print('синхронизация листа:', sync.get('message'))

    # ---------- 4. результат ----------
    print('--- результат ---')
    print(f'   план за ноябрь: было {before}, стало {after}')
    rows = pf.get_plan_fact(db, date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    names = {row['employee_name'] for row in rows}
    print('   сотрудников в плане-факте за ноябрь:', len(names))
    october = db.query(models.Plan).filter(
        models.Plan.date >= date(2026, 10, 1), models.Plan.date <= date(2026, 10, 31)).count()
    print('   план за октябрь (не трогали):', october)
finally:
    db.close()
