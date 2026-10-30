"""Перенос смен из строк «Вн. совм. …» в план-факт.

В ноябрьском графике у каждого сотрудника две строки: его собственная
и вторая — «Вн. совм. <должность>» (внешнее совместительство), где ФИО
не пишется, но дни со сменами заполнены. Эти смены относятся к тому же
сотруднику и должны попадать в план-факт.
"""
from datetime import date

import models
import schedule_grid as sg
import shift_codes


def apply(db, year, month):
    """Дописывает в план смены из строк «Вн. совм.» за указанный месяц."""
    year, month = int(year), int(month)
    if not sg.os.path.exists(sg.SCHEDULE_FILE):
        return {'added': 0, 'updated': 0, 'message': 'Файл графика не найден'}

    from openpyxl import load_workbook
    wb = load_workbook(sg.SCHEDULE_FILE)
    ws = sg._sheet_for(wb, year, month)
    if ws is None:
        return {'added': 0, 'updated': 0, 'message': 'Лист за этот месяц не найден'}

    header_row, day_cols, _kept, max_row = sg._visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return {'added': 0, 'updated': 0, 'message': 'Не найдены дни месяца'}

    col_days = sorted(day_cols.items())
    last_day = date(year, month, sg._days_in_month(year, month))

    employees = {e.name.strip().lower(): e for e in db.query(models.Employee).all()}
    existing = {}
    for plan in db.query(models.Plan).filter(models.Plan.date >= date(year, month, 1),
                                             models.Plan.date <= last_day).all():
        existing[(plan.employee_id, plan.date.day)] = plan

    added = updated = 0
    for r in range(header_row + 2, ws.max_row):
        name = ws.cell(r, 3).value
        mark = ws.cell(r + 1, 4).value
        if not name or not str(name).strip():
            continue
        if not mark or 'совм' not in str(mark).lower():
            continue
        employee = employees.get(str(name).strip().lower())
        if employee is None:
            continue
        for c, day in col_days:
            value = ws.cell(r + 1, c).value
            if value is None:
                continue
            text = str(value).strip()
            if not text or text in ('0', 'nan'):
                continue
            text = shift_codes.canonical(text, date(year, month, day))
            plan = existing.get((employee.id, day))
            if plan is None:
                db.add(models.Plan(employee_id=employee.id,
                                   date=date(year, month, day), plan_type=text))
                existing[(employee.id, day)] = True
                added += 1
            elif (plan.plan_type or '').strip().upper() != text.strip().upper():
                plan.plan_type = text
                updated += 1
    db.commit()
    return {'added': added, 'updated': updated,
            'message': f'Смены из строк «Вн. совм.»: добавлено {added}, обновлено {updated}'}
