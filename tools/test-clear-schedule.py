"""Проверка очистки графика: значения убираются, остаются только цвета выходных."""
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
from openpyxl.cell.cell import MergedCell
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import schedule_grid as sg

YEAR, MONTH = 2026, 11
TMP = r'C:\plan-fact-app\.tmp\clear-test'
os.makedirs(TMP, exist_ok=True)
TEST_XLSX = os.path.join(TMP, 'schedule.xlsx')
shutil.copy2(sg.SCHEDULE_FILE, TEST_XLSX)
sg.SCHEDULE_FILE = TEST_XLSX
sg.BACKUP_FILE = os.path.join(TMP, 'schedule.backup.xlsx')

engine = create_engine('sqlite:///:memory:')
models.Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

# немного планов за ноябрь — очистка должна их удалить
employee = models.Employee(name='Тестовый Сотрудник', position='', department='', order=1)
db.add(employee)
db.commit()
for day in (3, 4, 5):
    db.add(models.Plan(employee_id=employee.id, date=date(YEAR, MONTH, day), plan_type='Я'))
db.commit()

ok, fail = [], []


def check(name, condition, detail=''):
    (ok if condition else fail).append(name)
    print(f'  [{"OK" if condition else "ОШИБКА"}] {name}' + (f' — {detail}' if detail else ''))


def survey(path):
    """Смены, цвета смен и фоновые заливки (выходные/праздники) по дням."""
    wb = load_workbook(path)
    theme = sg._theme_colors(wb)
    shift_values = {str(value).upper() for value in sg.VALUE_COLORS.values()}
    ws = sg._sheet_for(wb, YEAR, MONTH)
    header_row, day_cols, _kept, max_row = sg._visible_layout(ws, YEAR, MONTH)
    data = {'shifts': 0, 'weekend_filled': 0, 'weekday_filled': 0, 'weekend_total': 0,
            'weekday_total': 0, 'names': 0, 'weekend_color': None, 'weekend_colors': {},
            'shift_colored': 0, 'background_filled': 0}
    for r in range(header_row + 2, max_row + 1):
        name = ws.cell(r, 3).value
        if not (name and str(name).strip()):
            continue
        data['names'] += 1
        for c, day in day_cols.items():
            cell = ws.cell(r, c)
            if isinstance(cell, MergedCell):
                continue
            is_weekend = (sg._weekday_short(YEAR, MONTH, day) or '') in ('сб', 'вс')
            color = (sg._fill_hex(cell, theme) or '').upper()
            if not sg._is_empty(cell.value):
                data['shifts'] += 1
            if color in shift_values:
                data['shift_colored'] += 1
            if color:
                if is_weekend:
                    data['weekend_filled'] += 1
                    data['weekend_colors'][color] = data['weekend_colors'].get(color, 0) + 1
                else:
                    data['weekday_filled'] += 1
                    if color not in shift_values:
                        data['background_filled'] += 1
            if is_weekend:
                data['weekend_total'] += 1
            else:
                data['weekday_total'] += 1
    if data['weekend_colors']:
        data['weekend_color'] = max(data['weekend_colors'], key=data['weekend_colors'].get)
    return data


print('=== до очистки ===')
before = survey(TEST_XLSX)
print('   ', before)
check('в ноябре есть смены', before['shifts'] > 0, str(before['shifts']))
check('есть закрашенные рабочие дни (цвета смен)', before['weekday_filled'] > 0,
      str(before['weekday_filled']))

print('=== очистка ноября ===')
result = sg.clear_schedule_data(db, YEAR, MONTH, clear_plan=True, clear_notes=True, clear_shifts=True)
print('   ', result['message'])
check('очистка прошла без предупреждений', not result.get('warnings'), str(result.get('warnings')))
check('план в базе удалён', db.query(models.Plan).count() == 0, str(db.query(models.Plan).count()))

print('=== после очистки ===')
after = survey(TEST_XLSX)
print('   ', after)
check('смены убраны', after['shifts'] == 0, str(after['shifts']))
check('цвета смен убраны (в том числе в пустых клетках)', after['shift_colored'] == 0,
      str(after['shift_colored']))
check('все клетки выходных закрашены', after['weekend_filled'] == after['weekend_total'],
      f"{after['weekend_filled']} из {after['weekend_total']}")
check('фон выходных одного цвета', len(after['weekend_colors']) == 1, str(after['weekend_colors']))
check('фон праздничных дней не потерян',
      after['background_filled'] >= before['background_filled'],
      f"{after['background_filled']} vs {before['background_filled']}")
check('сотрудники на месте', after['names'] == before['names'],
      f"{after['names']} vs {before['names']}")

db.close()
shutil.rmtree(TMP, ignore_errors=True)
print()
print(f'ИТОГ: успешно {len(ok)}, ошибок {len(fail)}')
for name in fail:
    print('  ОШИБКА:', name)
sys.exit(1 if fail else 0)
