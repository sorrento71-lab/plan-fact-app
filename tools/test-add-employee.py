"""Проверка: новый сотрудник встаёт в свой участок; график и план-факт синхронны."""
import os
import shutil
import sys
from datetime import date

sys.path.insert(0, r'C:\plan-fact-app\backend')

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import planfact_service as pf
import schedule_grid as sg

YEAR, MONTH = 2026, 11
TMP = r'C:\plan-fact-app\.tmp\add-test'
os.makedirs(TMP, exist_ok=True)
TEST_XLSX = os.path.join(TMP, 'schedule.xlsx')
shutil.copy2(sg.SCHEDULE_FILE, TEST_XLSX)
sg.SCHEDULE_FILE = TEST_XLSX
sg.BACKUP_FILE = os.path.join(TMP, 'schedule.backup.xlsx')

engine = create_engine('sqlite:///:memory:')
models.Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

ok, fail = [], []


def check(name, condition, detail=''):
    (ok if condition else fail).append(name)
    print(f'  [{"OK" if condition else "ОШИБКА"}] {name}' + (f' — {detail}' if detail else ''))


def rows_snapshot(path):
    """Карта: координаты -> значение, чтобы сравнить до и после вставки."""
    wb = load_workbook(path)
    ws = sg._sheet_for(wb, YEAR, MONTH)
    header_row, day_cols, kept_cols, max_row = sg._visible_layout(ws, YEAR, MONTH)
    data = {}
    for r in range(header_row + 2, max_row + 1):
        for c in range(1, ws.max_column + 1):
            value = ws.cell(r, c).value
            if value is not None and str(value).strip():
                data[(r, c)] = str(value).strip()
    return data, header_row, day_cols, kept_cols, max_row


def section_rows(path):
    """Строки сотрудников и их участки."""
    wb = load_workbook(path)
    ws = sg._sheet_for(wb, YEAR, MONTH)
    header_row, _day, _kept, max_row = sg._visible_layout(ws, YEAR, MONTH)
    result = []
    current = ''
    for r in range(header_row + 2, max_row + 1):
        for col in (2, 1):
            value = ws.cell(r, col).value
            text = str(value).strip() if value is not None else ''
            if text and text.lower() != 'nan':
                current = text
                break
        name = ws.cell(r, 3).value
        if name and str(name).strip():
            result.append((r, str(name).strip(), current))
    return result


before, header_row, day_cols, kept_cols, max_row = rows_snapshot(TEST_XLSX)
sections = section_rows(TEST_XLSX)

# участок, в котором больше двух сотрудников (чтобы вставка была в середине листа)
counts = {}
for _r, _n, sec in sections:
    counts[sec] = counts.get(sec, 0) + 1
target_section = max((s for s in counts if counts[s] >= 3), key=lambda s: counts[s])
section_block = [(r, n) for r, n, sec in sections if sec == target_section]
print(f'=== участок «{target_section}»: строки {section_block[0][0]}..{section_block[-1][0]} '
      f'({len(section_block)} человек) ===')

print('=== добавление сотрудника ===')
result = sg.add_schedule_employee('Тестовый Новый', 'Слесарь', target_section, db, YEAR, MONTH)
print('  ', result['message'])
new_row = result.get('row')

first_row, last_row = section_block[0][0], section_block[-1][0]
check('сотрудник встал внутри своего участка', first_row < new_row <= last_row + 1,
      f'строка {new_row}, участок {first_row}..{last_row}')
check('в справочнике базы он появился',
      db.query(models.Employee).filter(models.Employee.name == 'Тестовый Новый').first() is not None)

wb = load_workbook(TEST_XLSX)
ws = sg._sheet_for(wb, YEAR, MONTH)
check('ФИО записано в строку', str(ws.cell(new_row, 3).value).strip() == 'Тестовый Новый',
      repr(ws.cell(new_row, 3).value))
check('подпись участка не дублируется в новой строке',
      not (ws.cell(new_row, 2).value and str(ws.cell(new_row, 2).value).strip()),
      repr(ws.cell(new_row, 2).value))
covered = [str(m) for m in ws.merged_cells.ranges
           if m.min_col <= 2 and m.min_row < m.max_row and m.min_row <= new_row <= m.max_row]
check('подпись участка растянута на новую строку', bool(covered), str(covered))
check('должность записана', str(ws.cell(new_row, 4).value).strip() == 'Слесарь',
      repr(ws.cell(new_row, 4).value))

after, _h, _d, _k, _m = rows_snapshot(TEST_XLSX)
moved = 0
broken = []
for (r, c), value in before.items():
    if r < new_row:
        if after.get((r, c)) != value:
            broken.append((r, c, value, after.get((r, c))))
    else:
        moved += 1
        if after.get((r + 1, c)) != value:
            broken.append((r, c, value, after.get((r + 1, c))))
check('данные листа не потерялись при вставке', not broken, str(broken[:4]))
print(f'   сдвинуто строк ниже вставки: {moved}')
check('сотрудник попал в свой участок по разбору листа',
      any(r == new_row and sec == target_section for r, _n, sec in section_rows(TEST_XLSX)),
      str([item for item in section_rows(TEST_XLSX) if item[0] == new_row]))

print('=== синхронизация: правка в графике -> план в базе ===')
day_col = next(c for c, d in day_cols.items() if d == 5)
ui_col = kept_cols.index(day_col) + 1
ui_row = new_row - header_row + 1
sg.set_schedule_cell(ui_row, ui_col, 'Я', db=db, year=YEAR, month=MONTH)
employee = db.query(models.Employee).filter(models.Employee.name == 'Тестовый Новый').first()
plan = db.query(models.Plan).filter(models.Plan.employee_id == employee.id,
                                    models.Plan.date == date(YEAR, MONTH, 5)).first()
check('смена «Я» из графика попала в план', plan is not None and plan.plan_type == 'Я',
      repr(plan.plan_type if plan else None))

sg.set_schedule_cell(ui_row, ui_col, 'О', db=db, year=YEAR, month=MONTH)
db.refresh(plan) if plan else None
plan = db.query(models.Plan).filter(models.Plan.employee_id == employee.id,
                                    models.Plan.date == date(YEAR, MONTH, 5)).first()
check('правка на «О» тоже попала в план', plan is not None and plan.plan_type == 'О',
      repr(plan.plan_type if plan else None))

print('=== синхронизация: правка плана -> лист графика ===')
pf.update_plan(db, 'Тестовый Новый', f'{YEAR}-{MONTH:02d}-06', 'Я')
day6_col = next(c for c, d in day_cols.items() if d == 6)
wb2 = load_workbook(TEST_XLSX)
ws2 = sg._sheet_for(wb2, YEAR, MONTH)
value6 = str(ws2.cell(new_row, day6_col).value).strip() if ws2.cell(new_row, day6_col).value else ''
check('план «Я» на 6-е попал в лист графика', value6 == 'Я', repr(value6))

print('=== выгрузка плана в план-факт (сводка) ===')
rows = pf.get_plan_fact(db, date_from=date(YEAR, MONTH, 1), date_to=date(YEAR, MONTH, 30))
mine = [row for row in rows if row['employee_name'] == 'Тестовый Новый']
check('новый сотрудник виден в план-факте', bool(mine), f'строк {len(mine)}')
values = sorted({str(row['plan_type']) for row in mine})
check('в план-факте видны обе правки', values == ['О', 'Я'], str(values))

db.close()
shutil.rmtree(TMP, ignore_errors=True)
print()
print(f'ИТОГ: успешно {len(ok)}, ошибок {len(fail)}')
for name in fail:
    print('  ОШИБКА:', name)
sys.exit(1 if fail else 0)
