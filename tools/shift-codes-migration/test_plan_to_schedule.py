"""Проверка путей «план -> график» на КОПИЯХ файла и базы.

- план-факт: правка плана «11» в ноябре сохраняется как «Я» и переносится в лист;
- перенос плана из базы в лист: «11» в базе и «Я» в листе считаются одним значением
  (лишних правок нет), «Д» в базе переносится как «В»;
- октябрь — без изменений.
"""
import os
import shutil
import sys
from datetime import date

sys.path.insert(0, r'C:\plan-fact-app\backend')

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import planfact_service as pf
import schedule_grid as sg

TMP = r'C:\plan-fact-app\.tmp\shift-test2'
os.makedirs(TMP, exist_ok=True)
TEST_XLSX = os.path.join(TMP, 'schedule.xlsx')
shutil.copy2(sg.SCHEDULE_FILE, TEST_XLSX)
sg.SCHEDULE_FILE = TEST_XLSX
sg.BACKUP_FILE = os.path.join(TMP, 'schedule.backup.xlsx')

engine = create_engine('sqlite:///:memory:')
models.Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

wb = load_workbook(TEST_XLSX)
ws = wb['11.2026']
header_row, day_cols, kept, max_row = sg._visible_layout(ws, 2026, 11)
emp_row = next(r for r in range(header_row + 2, max_row + 1)
               if ws.cell(r, 3).value and str(ws.cell(r, 3).value).strip())
emp_name = str(ws.cell(emp_row, 3).value).strip()
db.add(models.Employee(name=emp_name, position='', department='', order=1))
db.commit()
day5_col = next(c for c, d in day_cols.items() if d == 5)
print('сотрудник:', emp_name, '| ячейка 05.11 =', repr(ws.cell(emp_row, day5_col).value))

print('=== update_plan: ввод «11» за 05.11.2026 ===')
result = pf.update_plan(db, emp_name, '2026-11-05', '11')
print('  ', result['message'][:120])
plan = db.query(models.Plan).filter(models.Plan.date == date(2026, 11, 5)).first()
wb2 = load_workbook(TEST_XLSX)
print('   в базе:', repr(plan.plan_type),
      '| в листе:', repr(wb2['11.2026'].cell(emp_row, day5_col).value))

print('=== update_plan: ввод «Д» за 06.11.2026 ===')
result = pf.update_plan(db, emp_name, '2026-11-06', 'Д')
plan = db.query(models.Plan).filter(models.Plan.date == date(2026, 11, 6)).first()
day6_col = next(c for c, d in day_cols.items() if d == 6)
wb3 = load_workbook(TEST_XLSX)
print('   в базе:', repr(plan.plan_type),
      '| в листе:', repr(wb3['11.2026'].cell(emp_row, day6_col).value))

print('=== перенос плана из базы в лист (ноябрь) ===')
# в базе за 5-е стоит «11» (старый код) — лист считаем эталоном
plan.plan_type = '11'
db.query(models.Plan).filter(models.Plan.date == date(2026, 11, 6)).delete()
db.commit()
summary = sg.plan_to_schedule_summary(db, 2026, 11)
print('  ', {k: v for k, v in summary.items() if k != 'cells'}, '(ожидается changed: 0)')

print('=== перенос плана из базы в лист (октябрь, старые коды) ===')
ws10 = load_workbook(TEST_XLSX)['10.2026']
h10, d10, _k10, max10 = sg._visible_layout(ws10, 2026, 10)
r10 = next(r for r in range(h10 + 2, max10 + 1)
           if ws10.cell(r, 3).value and str(ws10.cell(r, 3).value).strip())
name10 = str(ws10.cell(r10, 3).value).strip()
if not db.query(models.Employee).filter(models.Employee.name == name10).first():
    db.add(models.Employee(name=name10, position='', department='', order=2))
    db.commit()
db.add(models.Plan(employee_id=db.query(models.Employee).filter(
    models.Employee.name == name10).first().id,
    date=date(2026, 10, 5), plan_type='9'))
db.commit()
summary10 = sg.plan_to_schedule_summary(db, 2026, 10)
print('  ', {k: v for k, v in summary10.items() if k != 'cells'},
      '(в октябре план «9» должен остаться «9»)')
db.close()
print('TEST2 DONE')
