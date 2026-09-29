"""Перевод данных графика и плана на коды «Я»/«В» (с ноября 2026).

Что делает:
1. копирует файл графика и базу в папку backup/ (перед изменениями);
2. в листах месяцев >= 11.2026 заменяет 11/9/8 -> «Я», «Д» -> «В»
   (заодно правит заливку: «Я» — фон дня, «В» — жёлтый как у «Д»);
3. в плане БД за даты >= 01.11.2026 приводит значения к «Я»/«В»;
4. при --import дополнительно переносит план из листа 11.2026 в базу.

Без --apply ничего не меняет, только показывает, что будет сделано.
"""
import os
import shutil
import sys
from datetime import date, datetime

sys.path.insert(0, r'C:\plan-fact-app\backend')

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import PatternFill

import models
import shift_codes
from database import SessionLocal
from schedule_grid import (BACKUP_FILE, SCHEDULE_FILE, _background_fill, _is_empty,
                           _plan_value_for, _sheet_for, _theme_colors, _visible_layout,
                           import_schedule_to_plan)

ROOT = r'C:\plan-fact-app'
BACKUP_DIR = os.path.join(ROOT, 'backup')
STAMP = datetime.now().strftime('%Y-%m-%d')
APPLY = '--apply' in sys.argv
DO_IMPORT = '--import' in sys.argv
DB_PATH = os.path.join(ROOT, 'backend', 'plan_fact.db')


def sheet_months(months=None):
    """Листы графика, которые относятся к ноябрю 2026 и позже."""
    wb = load_workbook(SCHEDULE_FILE)
    result = []
    for name in wb.sheetnames:
        try:
            month, year = int(name[:2]), int(name[3:])
        except ValueError:
            continue
        if name[2] != '.' or len(name) != 7:
            continue
        if date(year, month, 1) >= shift_codes.NEW_SCHEME_START:
            result.append(name)
    return wb, result


def migrate_sheet(wb, title, verbose=True):
    year, month = int(title[3:]), int(title[:2])
    ws = wb[title]
    header_row, day_cols, _kept, max_row = _visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return 0, {}

    theme_colors = _theme_colors(wb)
    # фон считаем до правок, иначе изменённые заливки повлияют на расчёт
    base_fill = {c: _background_fill(ws, c, header_row + 2, theme_colors) for c in day_cols}

    changes = {}
    for r in range(header_row + 2, max_row + 1):
        name = ws.cell(r, 3).value
        if not (name and str(name).strip()):
            continue
        for c, day in day_cols.items():
            cell = ws.cell(r, c)
            if isinstance(cell, MergedCell) or _is_empty(cell.value):
                continue
            text = str(cell.value).strip()
            new_value = shift_codes.canonical(text, date(year, month, day))
            if new_value == text:
                continue
            changes[(text, new_value)] = changes.get((text, new_value), 0) + 1
            if not APPLY:
                continue
            cell.value = new_value
            color = _plan_value_for(new_value)
            if color:
                cell.fill = PatternFill('solid', fgColor=color)
            elif base_fill.get(c):
                cell.fill = PatternFill('solid', fgColor=base_fill[c])
            else:
                cell.fill = PatternFill(fill_type=None)
    total = sum(changes.values())
    if verbose and total:
        detail = ', '.join(f'{a}->{b}: {n}' for (a, b), n in sorted(changes.items()))
        print(f'  лист {title}: {total} значений ({detail})')
    return total, changes


def migrate_plan(db):
    rows = db.query(models.Plan).filter(models.Plan.date >= shift_codes.NEW_SCHEME_START).all()
    changes = {}
    for plan in rows:
        old = (plan.plan_type or '').strip()
        new = shift_codes.canonical(old, plan.date)
        if new == old:
            continue
        changes[(old, new)] = changes.get((old, new), 0) + 1
        if APPLY:
            plan.plan_type = new
    if APPLY:
        db.commit()
    if changes:
        detail = ', '.join(f'{a}->{b}: {n}' for (a, b), n in sorted(changes.items()))
        print(f'  план в БД (с 01.11.2026): {sum(changes.values())} записей ({detail})')
    else:
        print('  план в БД (с 01.11.2026): изменений нет')
    return sum(changes.values())


def main():
    print(f'режим: {"ПРИМЕНЕНИЕ" if APPLY else "проверка (dry-run)"}')
    print(f'файл графика: {SCHEDULE_FILE} (изменён {datetime.fromtimestamp(os.path.getmtime(SCHEDULE_FILE)):%d.%m.%Y %H:%M})')

    if APPLY:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        xlsx_backup = os.path.join(BACKUP_DIR, f'ГРАФИК_ФОРМА A3 (перед кодами Я-В {STAMP}).xlsx')
        db_backup = os.path.join(BACKUP_DIR, f'plan_fact (перед кодами Я-В {STAMP}).db')
        shutil.copy2(SCHEDULE_FILE, xlsx_backup)
        shutil.copy2(DB_PATH, db_backup)
        print(f'  бэкапы: {os.path.basename(xlsx_backup)}, {os.path.basename(db_backup)}')

    wb, titles = sheet_months()
    print('1) листы графика с ноября 2026:', ', '.join(titles) or 'нет')
    total = 0
    for title in titles:
        changed, _ = migrate_sheet(wb, title)
        total += changed
    if APPLY and total:
        wb.save(SCHEDULE_FILE)
        print(f'  файл графика сохранён (изменено значений: {total})')
    elif not total:
        print('  изменений в листах нет')

    db = SessionLocal()
    try:
        print('2) план в базе')
        migrate_plan(db)

        if DO_IMPORT:
            print('3) перенос плана из листа 11.2026 в базу')
            if APPLY:
                result = import_schedule_to_plan(db, 2026, 11)
                print('  ', result.get('message', result))
            else:
                print('   (dry-run — перенос не выполняется)')
    finally:
        db.close()

    print('готово' if APPLY else 'dry-run завершён: запустите с --apply')


if __name__ == '__main__':
    main()
