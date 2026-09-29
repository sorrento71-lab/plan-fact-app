"""Проверка данных и сервисов после перехода на «Я»/«В»."""
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, r'C:\plan-fact-app\backend')

from openpyxl import load_workbook

import medcheck_export as me
import models
import planfact_service as pf
import schedule_grid as sg
import shift_codes
from database import SessionLocal

db = SessionLocal()
try:
    print('=== лист 11.2026: значения ячеек дней ===')
    wb = load_workbook(sg.SCHEDULE_FILE)
    for title in ('10.2026', '11.2026'):
        ws = wb[title]
        year, month = int(title[3:]), int(title[:2])
        header_row, day_cols, kept, max_row = sg._visible_layout(ws, year, month)
        counter = Counter()
        fills = Counter()
        for r in range(header_row + 2, max_row + 1):
            name = ws.cell(r, 3).value
            if not (name and str(name).strip()):
                continue
            for c in day_cols:
                v = ws.cell(r, c).value
                if v is None or str(v).strip() == '':
                    continue
                counter[str(v).strip()] += 1
                fill = sg._fill_hex(ws.cell(r, c), sg._theme_colors(wb))
                fills[(str(v).strip(), fill)] += 1
        print(f'  {title}: {dict(counter)}')
        print(f'    заливки: {dict(fills)}')

    print('=== сравнение графика с планом (load_schedule_grid) ===')
    for month in (10, 11):
        grid = sg.load_schedule_grid(db, 2026, month)
        print(f'  {month:02d}.2026: {grid["stats"]}')

    print('=== план в базе ===')
    for month in (8, 10, 11):
        start = date(2026, month, 1)
        end = date(2026, month, 28)
        rows = db.query(models.Plan).filter(models.Plan.date >= start, models.Plan.date <= end).all()
        print(f'  2026-{month:02d}: {dict(Counter((r.plan_type or "") for r in rows))}')

    print('=== план-факт ===')
    rows = pf.get_plan_fact(db, date_from=date(2026, 11, 1), date_to=date(2026, 11, 2))
    print('  11.2026 (2 дня): строк', len(rows))
    for row in rows[:4]:
        print('   ', row['date'], row['employee_name'], 'план=', row['plan_type'],
              'часы плана=', row['plan_hours'], 'статус=', row['status'])
    rows = pf.get_plan_fact(db, date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
    sample = [r for r in rows if r['plan_type']][:3]
    print('  10.2026 (1 день): план/часы —', [(r['plan_type'], r['plan_hours']) for r in sample])

    print('=== медосмотр ===')
    for month in (10, 11):
        summary = me.medcheck_summary(db, 2026, month)
        print(f'  {month:02d}.2026:', {k: v for k, v in summary.items()
                                       if k in ('status', 'employees', 'by_shift', 'message')})

    print('=== табель (ноябрь) ===')
    ts = pf.get_timesheet(db, date_from=date(2026, 11, 1), date_to=date(2026, 11, 3))
    marks = Counter()
    for emp in ts['employees']:
        for day in emp['days']:
            marks[(day['plan_type'], day['mark'])] += 1
    print('  пары (план, отметка):', dict(marks))
finally:
    db.close()
print('VERIFY OK')
