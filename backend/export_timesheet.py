# export_timesheet.py
# Формирование табеля Т-13 (xlsx) на основе шаблона табель.xlsx.
#
# Структура шаблона: каждый сотрудник занимает блок из 4 строк:
#   строка 1 — коды явок за 1-15 число  (колонки D..R)
#   строка 2 — часы за 1-15 число        (колонки D..R)
#   строка 3 — коды явок за 16-31 число  (колонки D..S)
#   строка 4 — часы за 16-31 число       (колонки D..S)
# Итоги считаются формулами в колонках T/W (как в первой строке шаблона).
from copy import copy
from datetime import date, timedelta
import io
import os

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter

from database import SessionLocal
import models

BLOCK_ROWS = 4          # строк на сотрудника
FIRST_DATA_ROW = 24     # первая строка данных в шаблоне
MAX_COL = 60            # последняя колонка шаблона (BH)


def safe_set_cell(ws, row, col, value):
    """Безопасно записывает значение в ячейку, обходя объединённые ячейки."""
    try:
        ws.cell(row=row, column=col).value = value
    except AttributeError:
        for merged_range in ws.merged_cells.ranges:
            if (merged_range.min_row <= row <= merged_range.max_row and
                    merged_range.min_col <= col <= merged_range.max_col):
                ws.cell(row=merged_range.min_row, column=merged_range.min_col).value = value
                return
        ws.cell(row=row, column=col).value = value


def get_timesheet_data(db, date_from, date_to):
    """Получает данные из БД для заполнения табеля."""
    today = date.today()
    if date_to > today:
        date_to = today
    if date_from > date_to:
        return {'employees': [], 'all_dates': [], 'date_from': date_from, 'date_to': date_to}

    employees = db.query(models.Employee).order_by(models.Employee.order, models.Employee.id).all()

    facts = db.query(models.Fact).filter(
        models.Fact.date >= date_from,
        models.Fact.date <= date_to
    ).all()
    facts_by_employee = {(f.employee_id, f.date): f for f in facts}

    all_dates = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]

    result = []
    for emp in employees:
        emp_days = {}
        for d in all_dates:
            fact = facts_by_employee.get((emp.id, d))
            fact_hours = fact.fact_hours if fact else 0
            emp_days[d.day] = {
                'date': d,
                'day': d.day,
                'fact_hours': fact_hours,
                'mark': 'Я' if fact_hours > 0 else ''
            }
        result.append({
            'id': emp.id,
            'name': emp.name,
            'tab_number': emp.tab_number or '',
            'days': emp_days
        })

    return {
        'employees': result,
        'all_dates': all_dates,
        'date_from': date_from,
        'date_to': date_to
    }


def _day_hours(days, day_num):
    """Часы за день (0, если нет данных)."""
    d = days.get(day_num)
    return d['fact_hours'] if d else 0


def fill_employee_block(ws, row, emp):
    """Заполняет блок из 4 строк данными сотрудника и готовыми итогами."""
    safe_set_cell(ws, row, 2, emp['name'])     # ФИО
    safe_set_cell(ws, row, 3, emp['tab_number'] or '')  # табельный номер

    days = emp['days']

    # Половина 1: дни 1-15, колонки D..R (4..18)
    for day in range(1, 16):
        hours = _day_hours(days, day)
        safe_set_cell(ws, row, 3 + day, 'Я' if hours > 0 else '')
        safe_set_cell(ws, row + 1, 3 + day, round(hours, 1) if hours > 0 else '')

    # Половина 2: дни 16-31, колонки D..S (4..19)
    for day in range(16, 32):
        hours = _day_hours(days, day)
        safe_set_cell(ws, row + 2, 3 + (day - 15), 'Я' if hours > 0 else '')
        safe_set_cell(ws, row + 3, 3 + (day - 15), round(hours, 1) if hours > 0 else '')

    # Итоги — готовые числа (видны в любом просмотрщике без пересчёта формул):
    # T — половина месяца (дни/часы), W — итог за месяц
    days1 = sum(1 for day in range(1, 16) if _day_hours(days, day) > 0)
    days2 = sum(1 for day in range(16, 32) if _day_hours(days, day) > 0)
    hours1 = round(sum(_day_hours(days, day) for day in range(1, 16)), 1)
    hours2 = round(sum(_day_hours(days, day) for day in range(16, 32)), 1)

    safe_set_cell(ws, row, 20, days1)              # дни I половины
    safe_set_cell(ws, row, 23, days1 + days2)      # дни за месяц
    safe_set_cell(ws, row + 1, 20, hours1)         # часы I половины
    safe_set_cell(ws, row + 2, 20, days2)          # дни II половины
    safe_set_cell(ws, row + 2, 23, round(hours1 + hours2, 1))  # часы за месяц
    safe_set_cell(ws, row + 3, 20, hours2)         # часы II половины


def block_has_borders(ws, row):
    """Проверяет, есть ли у блока (строка row) оформление рамок."""
    cell = ws.cell(row, 4)  # D — первая ячейка дней
    b = cell.border
    return bool(b and (b.left and b.left.style or b.right and b.right.style or
                       b.top and b.top.style or b.bottom and b.bottom.style))


def copy_block_style(ws, src_row, dst_row):
    """Копирует стили ячеек блока из 4 строк (рамки, заливки, высоты) без объединений."""
    delta = dst_row - src_row
    for i in range(BLOCK_ROWS):
        src_r = src_row + i
        dst_r = dst_row + i
        if src_r in ws.row_dimensions and ws.row_dimensions[src_r].height:
            ws.row_dimensions[dst_r].height = ws.row_dimensions[src_r].height
        for col in range(1, MAX_COL + 1):
            src_cell = ws.cell(src_r, col)
            dst_cell = ws.cell(dst_r, col)
            # В уже объединённых ячейках стиль задаётся ячейкой-анкором
            if isinstance(dst_cell, MergedCell):
                continue
            if src_cell.has_style:
                try:
                    dst_cell._style = copy(src_cell._style)
                except Exception:
                    pass
    return delta


def copy_block(ws, src_row, dst_row):
    """Копирует блок из 4 строк (стили и объединённые ячейки) из src_row в dst_row."""
    delta = copy_block_style(ws, src_row, dst_row)

    # Объединённые ячейки внутри блока-образца
    merges_to_copy = [
        m for m in ws.merged_cells.ranges
        if m.min_row >= src_row and m.max_row <= src_row + BLOCK_ROWS - 1
    ]
    for m in merges_to_copy:
        new_range = (f"{get_column_letter(m.min_col)}{m.min_row + delta}:"
                     f"{get_column_letter(m.max_col)}{m.max_row + delta}")
        ws.merge_cells(new_range)


def export_timesheet(db, date_from, date_to, template_path=None,
                     sort_field=None, sort_direction='asc'):
    if template_path is None:
        template_path = os.path.join(os.path.dirname(__file__), 'табель.xlsx')

    try:
        wb = load_workbook(template_path)
    except FileNotFoundError:
        raise FileNotFoundError(f"Шаблон не найден: {template_path}")

    ws = wb.active
    data = get_timesheet_data(db, date_from, date_to)
    employees = data['employees']
    actual_date_from = data['date_from']
    actual_date_to = data['date_to']

    # Сортировка — в том же порядке, что и на экране вкладки «Табель»
    # (employee_name на экране = name в данных)
    sort_key = 'name' if sort_field == 'employee_name' else (sort_field or 'name')
    if sort_key in ('name', 'tab_number'):
        employees = sorted(
            employees,
            key=lambda e: str(e.get(sort_key) or '').lower(),
            reverse=(sort_direction or 'asc').lower() == 'desc'
        )

    print(f"[export_timesheet] Период: {actual_date_from} - {actual_date_to}, "
          f"сотрудников в БД: {len(employees)}, сортировка: {sort_key} {sort_direction}")

    # Обновляем реквизиты документа.
    # ВАЖНО: ячейки Z12/AE12 объединены (диапазон Z12:AE12, анкор — Z12),
    # поэтому дату НЕ пишем в AE — она затёрла бы номер документа.
    # Порядок: сначала даты, номер документа — последним.
    safe_set_cell(ws, 12, 41, actual_date_from.strftime('%d.%m.%Y'))  # Отчетный период: с
    safe_set_cell(ws, 12, 44, actual_date_to.strftime('%d.%m.%Y'))    # Отчетный период: по
    safe_set_cell(ws, 12, 32, date.today().strftime('%d.%m.%Y'))      # Дата составления (AF12)
    safe_set_cell(ws, 12, 26, '7')                                    # Номер документа (Z12)

    # Табельные номера из шаблона (по имени сотрудника) — на случай,
    # если их ещё нет в БД; при переупорядочивании номер следует за человеком.
    template_tabs = {}
    for r in range(FIRST_DATA_ROW, ws.max_row + 1, BLOCK_ROWS):
        name = ws.cell(r, 2).value
        tab = ws.cell(r, 3).value
        if name and str(name).strip() and tab and str(tab).strip():
            template_tabs[str(name).strip().lower()] = str(tab).strip()

    # Плейсхолдеры не экспортируем
    employees = [
        e for e in employees
        if not str(e['name']).strip().lower().startswith('вакансия')
    ]

    # Канонический блок оформления — первый блок шаблона: его рамки/заливки
    # применяем ко ВСЕМ блокам, чтобы таблица выглядела единообразно.
    ref_row = FIRST_DATA_ROW
    filled = 0
    appended = 0
    row = FIRST_DATA_ROW

    # Пишем сотрудников по порядку в блоки шаблона (4 строки на человека),
    # а если блоков не хватает — докопируем по образцу.
    for emp in employees:
        if row + BLOCK_ROWS - 1 > ws.max_row:
            copy_block(ws, ref_row, row)      # стили + объединения
            appended += 1
        elif row != FIRST_DATA_ROW:
            copy_block_style(ws, ref_row, row)  # единый стиль с первым блоком

        emp_filled = dict(emp)
        emp_filled['tab_number'] = emp.get('tab_number') or \
            template_tabs.get(str(emp['name']).strip().lower(), '')
        fill_employee_block(ws, row, emp_filled)
        filled += 1
        row += BLOCK_ROWS

    # Очищаем неиспользованные блоки шаблона (если сотрудников меньше, чем блоков)
    while row <= ws.max_row:
        for i in range(BLOCK_ROWS):
            for col in range(1, 20):
                ws.cell(row + i, col).value = None
        row += BLOCK_ROWS

    # Единая сквозная нумерация всех блоков
    number = 1
    row = FIRST_DATA_ROW
    while row <= ws.max_row:
        safe_set_cell(ws, row, 1, number)
        number += 1
        row += BLOCK_ROWS

    # В шаблоне некоторые строки данных могут быть скрыты (hidden) —
    # в выгрузке показываем все строки таблицы
    for r in list(ws.row_dimensions.keys()):
        if isinstance(r, int) and r >= FIRST_DATA_ROW:
            ws.row_dimensions[r].hidden = False

    # Удаляем пустые служебные колонки Z..BH (данные для зарплаты, неявки),
    # чтобы табель был компактным и помещался на страницу.
    # Оставляем A..Y: №, ФИО, таб.№, дни, итоги.
    first_del = 26  # Z
    if ws.max_column >= first_del:
        to_remove = [m for m in ws.merged_cells.ranges if m.min_col >= first_del]
        for m in to_remove:
            ws.merged_cells.remove(m)
        ws.delete_cols(first_del, ws.max_column - first_del + 1)

    print(f"[export_timesheet] Заполнено: {filled}, дописано блоков: {appended}")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
