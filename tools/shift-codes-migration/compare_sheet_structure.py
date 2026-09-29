"""Сравнение структуры файла графика до и после миграции кодов."""
import sys
from openpyxl import load_workbook

sys.path.insert(0, r'C:\plan-fact-app\backend')

BEFORE = r'C:\plan-fact-app\backup\ГРАФИК_ФОРМА A3 (перед кодами Я-В 2026-09-28).xlsx'
AFTER = r'C:\plan-fact-app\ГРАФИК_ФОРМА A3.xlsx'

wb_b = load_workbook(BEFORE)
wb_a = load_workbook(AFTER)
print('листы до :', wb_b.sheetnames)
print('листы после:', wb_a.sheetnames)
print()
for name in wb_b.sheetnames:
    if name not in wb_a.sheetnames:
        print(f'{name}: ЛИСТ ПРОПАЛ')
        continue
    b, a = wb_b[name], wb_a[name]
    names_b = [str(b.cell(r, 3).value).strip() for r in range(1, b.max_row + 1)
               if b.cell(r, 3).value and str(b.cell(r, 3).value).strip()]
    names_a = [str(a.cell(r, 3).value).strip() for r in range(1, a.max_row + 1)
               if a.cell(r, 3).value and str(a.cell(r, 3).value).strip()]
    widths_b = sum(1 for d in b.column_dimensions.values() if d.width)
    widths_a = sum(1 for d in a.column_dimensions.values() if d.width)
    days_b = [b.cell(7, c).value for c in range(1, b.max_column + 1)]
    days_a = [a.cell(7, c).value for c in range(1, a.max_column + 1)]
    print(f'--- {name} ---')
    print(f'  строк/колонок:        {b.max_row}x{b.max_column} -> {a.max_row}x{a.max_column}')
    print(f'  объединённых ячеек:   {len(b.merged_cells.ranges)} -> {len(a.merged_cells.ranges)}')
    print(f'  колонок с шириной:    {widths_b} -> {widths_a}')
    print(f'  область печати:       {b.print_area} -> {a.print_area}')
    print(f'  закрепление:          {b.freeze_panes} -> {a.freeze_panes}')
    print(f'  сотрудников (кол. 3): {len(names_b)} -> {len(names_a)} '
          f'{"(совпадают)" if names_b == names_a else "(ОТЛИЧАЮТСЯ!)"}')
    print(f'  шапка дней:           {"совпадает" if days_b == days_a else "ОТЛИЧАЕТСЯ"}')
    print(f'  ориентация/формат:    {b.page_setup.orientation}/{b.page_setup.paperSize}'
          f' -> {a.page_setup.orientation}/{a.page_setup.paperSize}')
