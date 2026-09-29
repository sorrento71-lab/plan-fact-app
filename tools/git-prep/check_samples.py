"""Сравнение формы в samples/ с оригиналом: структура не должна пострадать."""
import os

from openpyxl import load_workbook

PAIRS = [
    (r'C:\plan-fact-app\ГРАФИК_ФОРМА A3.xlsx', r'C:\plan-fact-app\samples\ГРАФИК_ФОРМА A3.xlsx'),
    (r'C:\plan-fact-app\backend\табель.xlsx', r'C:\plan-fact-app\samples\табель.xlsx'),
    (r'C:\plan-fact-app\план-факт август2026.xlsx', r'C:\plan-fact-app\samples\план-факт август2026.xlsx'),
]

for src, dst in PAIRS:
    a = load_workbook(src)
    b = load_workbook(dst)
    print(f'=== {os.path.basename(dst)} ===')
    print(f'  листы совпадают: {a.sheetnames == b.sheetnames} ({len(b.sheetnames)} шт.)')
    for name in a.sheetnames:
        if name not in b.sheetnames:
            continue
        wa, wb = a[name], b[name]
        same = (wa.max_row == wb.max_row and wa.max_column == wb.max_column
                and len(wa.merged_cells.ranges) == len(wb.merged_cells.ranges)
                and wa.print_area == wb.print_area)
        print(f'  {name}: {wa.max_row}x{wa.max_column} -> {wb.max_row}x{wb.max_column}, '
              f'объединений {len(wa.merged_cells.ranges)} -> {len(wb.merged_cells.ranges)}, '
              f'печать {"та же" if wa.print_area == wb.print_area else "ДРУГАЯ"} '
              f'{"OK" if same else "ПРОВЕРИТЬ"}')
    # шапка графика: строка с днями месяца должна остаться
    if 'ГРАФИК' in os.path.basename(dst).upper():
        for name in b.sheetnames:
            ws = b[name]
            days = [ws.cell(r, c).value for r in range(1, 12) for c in range(1, ws.max_column + 1)
                    if isinstance(ws.cell(r, c).value, int) and 1 <= ws.cell(r, c).value <= 31]
            print(f'    {name}: номеров дней в шапке — {len(days)}')
