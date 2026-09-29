# plan_fact_export.py — выгрузка план-факта в Excel «как на экране».
# Таблица повторяет интерфейс: № | ФИО | Должность и по 5 колонок на день
# (План, Приход, Уход, Факт, Этапы) с цветами статусов.
from datetime import datetime
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Цвета статусов — как в интерфейсе план-факта (STATUS_COLORS во фронтенде)
STATUS_COLORS = {
    'Совпадает': '92D050',
    'Неполный день': 'FFFF00',
    'Отсутствует': 'FF6B6B',
    'Неучтенная работа': 'FFA94D',
    'Явка в выходной': 'FFA94D',
    'Выходной': 'ADD8E6',
    'Нет данных': 'FFFFFF',
}

DAY_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

THIN_SIDE = Side(style='thin', color='DDDDDD')
BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)

HEADER_FILL = PatternFill('solid', fgColor='1565C0')
SUBHEADER_FILL = PatternFill('solid', fgColor='E3F2FD')
WHITE_FILL = PatternFill('solid', fgColor='FFFFFF')
LIGHT_GREEN_FILL = PatternFill('solid', fgColor='E8F5E9')   # приход заполнен
LIGHT_ORANGE_FILL = PatternFill('solid', fgColor='FFF3E0')  # уход заполнен
LIGHT_BLUE_FILL = PatternFill('solid', fgColor='E3F2FD')    # факт есть
LIGHT_YELLOW_FILL = PatternFill('solid', fgColor='FFF9C4')  # этап заполнен
GRAY_FILL = PatternFill('solid', fgColor='F5F5F5')          # факта нет


def _solid(color_hex):
    return PatternFill('solid', fgColor=color_hex)


def _fact_text(fact_hours):
    """'11ч' как в интерфейсе (без дробной части у целых часов)."""
    if not fact_hours:
        return ''
    try:
        f = float(fact_hours)
        return f"{int(f)}ч" if f.is_integer() else f"{f}ч"
    except (TypeError, ValueError):
        return f"{fact_hours}ч"


def create_plan_fact_matrix_report(data: list, title: str = 'План-Факт') -> io.BytesIO:
    """Строит Excel-матрицу план-факт по данным get_plan_fact.

    data — список записей {employee_name, department, position, date, plan_type,
    start_time, end_time, fact_hours, production_stage, status, ...}.
    Сотрудники сортируются по имени (как в интерфейсе по умолчанию).
    """
    emp_map = {}
    dates = set()

    for row in data:
        dates.add(row['date'])
        name = row['employee_name']
        if name not in emp_map:
            emp_map[name] = {
                'name': name,
                'department': row.get('department', ''),
                'position': row.get('position', ''),
                'days': {},
            }
        emp_map[name]['days'][row['date']] = row

    employees = sorted(emp_map.values(), key=lambda e: str(e['name']).lower())
    dates = sorted(dates)

    wb = Workbook()
    ws = wb.active
    ws.title = 'План-Факт'

    n_days = len(dates)
    n_cols = 3 + n_days * 5

    # Ширины колонок
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 28
    ws.column_dimensions['C'].width = 18
    for i in range(n_days):
        for j in range(5):
            ws.column_dimensions[get_column_letter(4 + i * 5 + j)].width = 7

    # --- Строка 1: шапка (№, ФИО, Должность + день и день недели) ---
    ws.cell(1, 1, '№')
    ws.cell(1, 2, 'ФИО')
    ws.cell(1, 3, 'Должность')
    for i, d in enumerate(dates):
        c0 = 4 + i * 5
        ws.merge_cells(start_row=1, start_column=c0, end_row=1, end_column=c0 + 4)
        dt = datetime.strptime(d, '%Y-%m-%d')
        ws.cell(1, c0, f"{dt.day} {DAY_NAMES[dt.weekday()]}")

    # --- Строка 2: подзаголовки ---
    subs = ['План', 'Приход', 'Уход', 'Факт', 'Этапы']
    for i in range(n_days):
        for j, label in enumerate(subs):
            ws.cell(2, 4 + i * 5 + j, label)

    for c in range(1, n_cols + 1):
        cell1 = ws.cell(1, c)
        cell1.fill = HEADER_FILL
        cell1.font = Font(bold=True, color='FFFFFF', size=10)
        cell1.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell1.border = BORDER

        cell2 = ws.cell(2, c)
        cell2.fill = SUBHEADER_FILL
        cell2.font = Font(bold=True, size=9, color='0D47A1')
        cell2.alignment = Alignment(horizontal='center', vertical='center')
        cell2.border = BORDER

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 16

    # --- Данные ---
    for r, emp in enumerate(employees, start=3):
        c_num = ws.cell(r, 1, r - 2)
        c_name = ws.cell(r, 2, emp['name'])
        c_pos = ws.cell(r, 3, emp['position'])
        for cell in (c_num, c_name, c_pos):
            cell.border = BORDER
            cell.font = Font(size=10)
        c_num.alignment = Alignment(horizontal='center', vertical='center')
        c_name.alignment = Alignment(horizontal='left', vertical='center')

        for i, d in enumerate(dates):
            row_data = emp['days'].get(d)
            plan = row_data['plan_type'] if row_data else ''
            status = row_data['status'] if row_data else 'Нет данных'
            start_time = row_data['start_time'] if row_data else ''
            end_time = row_data['end_time'] if row_data else ''
            fact = row_data['fact_hours'] if row_data else 0
            stage = row_data['production_stage'] if row_data else ''
            c0 = 4 + i * 5

            # План — цвет по статусу (как на экране)
            pc = ws.cell(r, c0, plan)
            pc.fill = _solid(STATUS_COLORS.get(status, 'FFFFFF'))
            pc.font = Font(size=10, bold=bool(plan),
                           color='FFFFFF' if status == 'Отсутствует' else '333333')
            pc.alignment = Alignment(horizontal='center', vertical='center')
            pc.border = BORDER

            # Приход
            sc = ws.cell(r, c0 + 1, start_time)
            sc.fill = LIGHT_GREEN_FILL if start_time else WHITE_FILL
            sc.font = Font(size=9)
            sc.alignment = Alignment(horizontal='center', vertical='center')
            sc.border = BORDER

            # Уход
            ec = ws.cell(r, c0 + 2, end_time)
            ec.fill = LIGHT_ORANGE_FILL if end_time else WHITE_FILL
            ec.font = Font(size=9)
            ec.alignment = Alignment(horizontal='center', vertical='center')
            ec.border = BORDER

            # Факт
            fc = ws.cell(r, c0 + 3, _fact_text(fact))
            fc.fill = LIGHT_BLUE_FILL if fact else GRAY_FILL
            fc.font = Font(size=10, bold=bool(fact))
            fc.alignment = Alignment(horizontal='center', vertical='center')
            fc.border = BORDER

            # Этапы
            stc = ws.cell(r, c0 + 4, stage or '—')
            stc.fill = LIGHT_YELLOW_FILL if stage else WHITE_FILL
            stc.font = Font(size=9, color='333333' if stage else '999999')
            stc.alignment = Alignment(horizontal='center', vertical='center')
            stc.border = BORDER

    # Закрепляем шапку и колонки №/ФИО/Должность (как «липкие» в интерфейсе)
    ws.freeze_panes = 'D3'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
