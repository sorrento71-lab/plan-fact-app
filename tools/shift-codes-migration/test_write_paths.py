"""Проверка изменённых путей записи на КОПИЯХ файла графика и базы.

Что проверяем:
- правка ячейки в ноябре: введённые 11/9/8 -> «Я», «Д» -> «В» (и в листе, и в плане);
- правка ячейки в октябре: старые коды остаются как есть;
- выгрузка «только ритмы» за ноябрь отдаёт «Я», за октябрь — 11/9/8;
- расстановка смен за ноябрь пишет «Я», за октябрь — старые коды.
"""
import os
import shutil
import sys
from collections import Counter
from datetime import date
from io import BytesIO

sys.path.insert(0, r'C:\plan-fact-app\backend')

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import schedule_grid as sg
import shift_codes

TMP = r'C:\plan-fact-app\.tmp\shift-test'
os.makedirs(TMP, exist_ok=True)
TEST_XLSX = os.path.join(TMP, 'schedule.xlsx')
TEST_BAK = os.path.join(TMP, 'schedule.backup.xlsx')
shutil.copy2(sg.SCHEDULE_FILE, TEST_XLSX)
sg.SCHEDULE_FILE = TEST_XLSX
sg.BACKUP_FILE = TEST_BAK

engine = create_engine('sqlite:///:memory:')
models.Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

sheet = load_workbook(TEST_XLSX)['11.2026']
header_row, day_cols, kept, max_row = sg._visible_layout(sheet, 2026, 11)
emp_row = next(r for r in range(header_row + 2, max_row + 1)
               if sheet.cell(r, 3).value and str(sheet.cell(r, 3).value).strip())
emp_name = str(sheet.cell(emp_row, 3).value).strip()
db.add(models.Employee(name=emp_name, position='', department='', order=1))
db.commit()
print('тестовый сотрудник:', emp_name, 'строка', emp_row)

# колонка-день: берём 5-е число ноября
day_col = next(c for c, d in day_cols.items() if d == 5)
ui_col = kept.index(day_col) + 1


ui_row = emp_row - header_row + 1     # координаты интерфейса: файл = интерфейс + header_row - 1


def cell_and_plan():
    wb = load_workbook(TEST_XLSX)
    ws = wb['11.2026']
    value = ws.cell(emp_row, day_col).value
    row = db.query(models.Plan).filter(models.Plan.date == date(2026, 11, 5)).first()
    return value, (row.plan_type if row else None)


print('=== ноябрь: правка ячейки ===')
for entered in ('11', '9', '8', 'Д', 'О', 'Я', 'В'):
    result = sg.set_schedule_cell(ui_row, ui_col, entered, db=db, year=2026, month=11)
    value, plan = cell_and_plan()
    ok = shift_codes.canonical(entered, date(2026, 11, 5)) == (value or '')
    print(f'  введено {entered!r:>4} -> в листе {value!r:>5}, в плане {plan!r:>5} '
          f'{"OK" if ok else "ОШИБКА"}')

print('=== октябрь: правка ячейки (схема не меняется) ===')
sheet10 = load_workbook(TEST_XLSX)['10.2026']
h10, d10, kept10, max10 = sg._visible_layout(sheet10, 2026, 10)
r10 = next(r for r in range(h10 + 2, max10 + 1)
           if sheet10.cell(r, 3).value and str(sheet10.cell(r, 3).value).strip())
name10 = str(sheet10.cell(r10, 3).value).strip()
if not db.query(models.Employee).filter(models.Employee.name == name10).first():
    db.add(models.Employee(name=name10, position='', department='', order=2))
    db.commit()
col10 = next(c for c, d in d10.items() if d == 5)
ui10 = kept10.index(col10) + 1
sg.set_schedule_cell(3, ui10, '11', db=db, year=2026, month=10)
row = db.query(models.Plan).filter(models.Plan.date == date(2026, 10, 5)).first()
wb = load_workbook(TEST_XLSX)
print('  введено 11 -> в листе', repr(wb['10.2026'].cell(r10, col10).value),
      ', в плане', repr(row.plan_type if row else None))

print('=== выгрузка «только ритмы» ===')
for month in (10, 11):
    stream, name = sg.export_schedule_xlsx(2026, month, mode='rhythm')
    if stream is None:
        print(f'  {month:02d}.2026: ошибка {name}')
        continue
    wb2 = load_workbook(BytesIO(stream.getvalue()))
    ws2 = wb2[wb2.sheetnames[0]]
    counter = Counter()
    for row_cells in ws2.iter_rows():
        for cell in row_cells:
            if cell.value is not None and str(cell.value).strip():
                counter[str(cell.value).strip()] += 1
    kinds = {k: v for k, v in counter.items() if k in ('11', '9', '8', 'Д', 'Я', 'В')}
    print(f'  {month:02d}.2026 ({name}): {kinds}')

print('=== расстановка смен ===')
for month in (11, 10):
    # очищаем смены месяца в тестовой копии, чтобы было что расставлять
    wb3 = load_workbook(TEST_XLSX)
    title = f'{month:02d}.2026'
    ws3 = wb3[title]
    h, days, _k, mx = sg._visible_layout(ws3, 2026, month)
    for r in range(h + 2, mx + 1):
        if ws3.cell(r, 3).value and str(ws3.cell(r, 3).value).strip():
            for c in days:
                if r != emp_row or c != day_col:
                    ws3.cell(r, c).value = None
    wb3.save(TEST_XLSX)
    result = sg.fill_schedule_shifts(db=db, year=2026, month=month)
    print(f'  {title}: {result.get("message", result)}')
    print('    by_value:', result.get('by_value'))
db.close()
print('TEST DONE')
