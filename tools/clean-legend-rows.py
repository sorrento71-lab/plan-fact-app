"""Убирает из файла графика и базы служебные строки-легенды.

Строки вида «Я-(основная смена )» и «В- (Доп.смена )» — это пояснения к графика,
а не сотрудники. Скрипт удаляет их из всех листов и из справочника (с бэкапом).
"""
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, r'C:\plan-fact-app\backend')

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

import models
import schedule_grid as sg
from database import SessionLocal

ROOT = r'C:\plan-fact-app'
BACKUP_DIR = os.path.join(ROOT, 'backup')
STAMP = datetime.now().strftime('%Y-%m-%d_%H%M')

# ---------- 1. файл графика ----------
backup_xlsx = os.path.join(BACKUP_DIR, f'ГРАФИК_ФОРМА A3 (перед уборкой легенды {STAMP}).xlsx')
os.makedirs(BACKUP_DIR, exist_ok=True)
shutil.copy2(sg.SCHEDULE_FILE, backup_xlsx)
print('бэкап файла:', os.path.basename(backup_xlsx))

wb = load_workbook(sg.SCHEDULE_FILE)
removed_sheet_rows = []
for name in list(wb.sheetnames):
    ws = wb[name]
    rows_to_delete = []
    for r in range(1, ws.max_row + 1):
        value = ws.cell(r, 3).value
        if value is None:
            continue
        text = str(value).strip()
        if text and sg._is_placeholder_name(text) and '(' in text:
            rows_to_delete.append(r)
    for r in reversed(rows_to_delete):
        wb[name].delete_rows(r, 1)
        removed_sheet_rows.append((name, r, str(ws.cell(r, 3).value)))

if removed_sheet_rows:
    try:
        wb.save(sg.SCHEDULE_FILE)
    except PermissionError:
        print('❌ файл графика открыт в Excel — закройте его и повторите')
        sys.exit(1)
    print('удалены строки из листов:')
    for sheet, row, text in removed_sheet_rows:
        print(f'   лист {sheet!r}, строка {row}: {text!r}')
else:
    print('в листах служебных строк не найдено')

# ---------- 2. база ----------
backup_db = os.path.join(BACKUP_DIR, f'plan_fact (перед уборкой легенды {STAMP}).db')
shutil.copy2(os.path.join(ROOT, 'backend', 'plan_fact.db'), backup_db)
print('бэкап базы:', os.path.basename(backup_db))

db = SessionLocal()
try:
    suspects = [emp for emp in db.query(models.Employee).all()
                if sg._is_placeholder_name(emp.name or '') and '(' in (emp.name or '')]
    for emp in suspects:
        plans = db.query(models.Plan).filter(models.Plan.employee_id == emp.id).delete()
        facts = db.query(models.Fact).filter(models.Fact.employee_id == emp.id).delete()
        db.delete(emp)
        print(f'   удалён сотрудник id={emp.id} {emp.name!r} (планов {plans}, фактов {facts})')
    db.commit()
    if not suspects:
        print('   в справочнике таких сотрудников нет')
finally:
    db.close()

print('готово')
