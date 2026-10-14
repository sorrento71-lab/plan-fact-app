"""Сервисный слой «План-Факт»: данные и выгрузки без веб-фреймворка.

Зачем этот модуль. Раньше логика чтения данных (план-факт, табель, статистика)
и сборки выгрузок (питание, неделя, месяц) жила прямо в эндпоинтах `app.py`,
то есть была неотделима от FastAPI. Настольному приложению (папка `desktop-b`)
нужны те же самые данные, но без HTTP — и оно вынуждено было импортировать
`app.py` вместе со всем веб-стеком.

Теперь логика живёт здесь, в обычных функциях без FastAPI:
`app.py` вызывает их из эндпоинтов, а настольное приложение — напрямую.

Что осталось в `app.py`: только описание HTTP (пути, коды, заголовки ответов).
Поведение веб-версии при переносе не менялось: функции перенесены дословно,
одинаковость ответов проверена снимком API (см. `check_api_parity.py`).
"""
from __future__ import annotations

import io
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Union

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# На Windows stdout/stderr по умолчанию cp1251: эмодзи в print() (📊, ✅ и т.п.)
# вызывают UnicodeEncodeError и роняют весь вызов. В app.py такая же настройка
# была при импорте, но настольная версия app.py не грузит — поэтому настройка
# нужна здесь, рядом с самими print().
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

import models
import shift_codes
from plan_fact_export import create_plan_fact_matrix_report
from schedule_grid import clear_schedule_days_for_employee, sync_schedule_from_plan

XLSX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

MONTH_NAMES = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
               'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

# Границы недель внутри месяца — как было в эндпоинте выгрузки недели
WEEKS = [
    {'id': 0, 'start': 1, 'end': 7, 'label': '1-7'},
    {'id': 1, 'start': 8, 'end': 14, 'label': '8-14'},
    {'id': 2, 'start': 15, 'end': 21, 'label': '15-21'},
    {'id': 3, 'start': 22, 'end': 28, 'label': '22-28'},
    {'id': 4, 'start': 29, 'end': 31, 'label': '29-31'},
]


@dataclass
class ReportFile:
    """Готовая выгрузка в xlsx."""
    stream: io.BytesIO
    filename: str                # обычное имя файла (для сохранения на диск)
    content_disposition: str     # ровно тот заголовок, что отдавала веб-версия


@dataclass
class ReportWarning:
    """Выгрузка не сделана, но это не ошибка — данных нет."""
    message: str
    count: int = 0


ReportResult = Union[ReportFile, ReportWarning]


class ServiceError(Exception):
    """Ошибка сервиса с кодом ответа.

    В веб-версии такие ошибки поднимались как HTTPException прямо в эндпоинте,
    но попадали в общий `except Exception` и превращались в 500 с текстом
    «код: сообщение». Чтобы поведение API не изменилось, текст исключения
    формируется точно так же, как у starlette.HTTPException.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


# ============================================================
# ПЛАН-ФАКТ
# ============================================================
def get_plan_fact(
        db,
        employee: Optional[str] = None,
        department: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Возвращает объединённые данные план-факт с ВСЕМИ сотрудниками"""

    # Если переданы year и month - устанавливаем диапазон дат
    if year and month:
        date_from = date(year, month, 1)
        if month == 12:
            date_to = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            date_to = date(year, month + 1, 1) - timedelta(days=1)

    emp_query = db.query(models.Employee)
    if employee:
        emp_query = emp_query.filter(models.Employee.name.contains(employee))
    if department:
        emp_query = emp_query.filter(models.Employee.department == department)

    employees = emp_query.order_by(models.Employee.order, models.Employee.id).all()

    emp_ids = [e.id for e in employees]
    plans_query = db.query(models.Plan).filter(models.Plan.employee_id.in_(emp_ids))

    if date_from:
        plans_query = plans_query.filter(models.Plan.date >= date_from)
    if date_to:
        plans_query = plans_query.filter(models.Plan.date <= date_to)

    plans = plans_query.all()

    facts_query = db.query(models.Fact).filter(models.Fact.employee_id.in_(emp_ids))
    if date_from:
        facts_query = facts_query.filter(models.Fact.date >= date_from)
    if date_to:
        facts_query = facts_query.filter(models.Fact.date <= date_to)

    facts = facts_query.all()

    plans_by_employee = {}
    for plan in plans:
        key = (plan.employee_id, plan.date)
        plans_by_employee[key] = plan

    facts_by_employee = {}
    for fact in facts:
        key = (fact.employee_id, fact.date)
        facts_by_employee[key] = fact

    day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

    output = []
    for emp in employees:
        all_dates = set()
        for plan in plans:
            if plan.employee_id == emp.id:
                all_dates.add(plan.date)
        for fact in facts:
            if fact.employee_id == emp.id:
                all_dates.add(fact.date)

        if not all_dates:
            continue

        for d in sorted(all_dates):
            plan_key = (emp.id, d)
            fact_key = (emp.id, d)

            plan = plans_by_employee.get(plan_key)
            fact = facts_by_employee.get(fact_key)

            plan_type = plan.plan_type if plan else ''
            # Часы плана по коду: 11/9/8 — по длительности, «Д», «Я» и «В» — 11 ч.
            plan_hours = shift_codes.plan_hours(plan_type)

            start_time = fact.start_time if fact else ''
            end_time = fact.end_time if fact else ''
            fact_hours = fact.fact_hours if fact else 0
            production_stage = fact.production_stage if fact else ''

            status = 'Нет данных'
            if plan_type and plan_type.upper() in ['О', 'Б', 'б/с']:
                if fact_hours > 0:
                    status = 'Явка в выходной'
                else:
                    status = 'Выходной'
            elif not plan_type or plan_type == '':
                if fact_hours > 0:
                    status = 'Неучтенная работа'
            else:
                if fact_hours >= 11:
                    status = 'Совпадает'
                elif fact_hours > 0:
                    status = 'Неполный день'
                else:
                    status = 'Отсутствует'

            day_of_week = day_names[d.weekday()] if d else None

            output.append({
                'employee_name': emp.name,
                'department': emp.department,
                'position': emp.position,
                'date': d.isoformat() if d else None,
                'plan_hours': plan_hours,
                'plan_type': plan_type,
                'start_time': start_time,
                'end_time': end_time,
                'fact_hours': round(float(fact_hours), 2),
                'production_stage': production_stage,
                'status': status,
                'day_of_week': day_of_week
            })

    return output


# ============================================================
# ТАБЕЛЬ УЧЕТА РАБОЧЕГО ВРЕМЕНИ (ФОРМА Т-13)
# ============================================================
def get_timesheet(
        db,
        employee_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
):
    if not date_from:
        today = date.today()
        date_from = date(today.year, today.month, 1)
    if not date_to:
        if date_from.month == 12:
            date_to = date(date_from.year + 1, 1, 1) - timedelta(days=1)
        else:
            date_to = date(date_from.year, date_from.month + 1, 1) - timedelta(days=1)

    query = db.query(models.Employee)
    if employee_id:
        query = query.filter(models.Employee.id == employee_id)
    employees = query.order_by(models.Employee.order, models.Employee.id).all()

    facts_query = db.query(models.Fact).filter(
        models.Fact.date >= date_from,
        models.Fact.date <= date_to
    )
    if employee_id:
        facts_query = facts_query.filter(models.Fact.employee_id == employee_id)
    facts = facts_query.all()

    facts_by_employee = {}
    for fact in facts:
        key = (fact.employee_id, fact.date)
        facts_by_employee[key] = fact

    plans_query = db.query(models.Plan).filter(
        models.Plan.date >= date_from,
        models.Plan.date <= date_to
    )
    if employee_id:
        plans_query = plans_query.filter(models.Plan.employee_id == employee_id)
    plans = plans_query.all()

    plans_by_employee = {}
    for plan in plans:
        key = (plan.employee_id, plan.date)
        plans_by_employee[key] = plan

    result = []
    days_in_month = (date_to - date_from).days + 1
    all_dates = [date_from + timedelta(days=i) for i in range(days_in_month)]

    for emp in employees:
        emp_data = {
            'employee_id': emp.id,
            'employee_name': emp.name,
            'tab_number': emp.tab_number or '',
            'days': []
        }

        for d in all_dates:
            fact_key = (emp.id, d)
            plan_key = (emp.id, d)

            fact = facts_by_employee.get(fact_key)
            plan = plans_by_employee.get(plan_key)

            fact_hours = fact.fact_hours if fact else 0
            plan_type = plan.plan_type if plan else ''

            mark = ''
            if fact_hours > 0:
                mark = 'Я'
            elif plan_type and plan_type.upper() in ['О', 'Б', 'б/с'] and fact_hours > 0:
                mark = 'Я'

            emp_data['days'].append({
                'date': d.isoformat(),
                'day': d.day,
                'fact_hours': round(fact_hours, 2) if fact_hours > 0 else None,
                'plan_type': plan_type if plan_type else None,
                'mark': mark
            })

        result.append(emp_data)

    return {
        'period': {
            'from': date_from.isoformat(),
            'to': date_to.isoformat()
        },
        'employees': result
    }


# ============================================================
# СТАТИСТИКА
# ============================================================
def get_stats(db) -> dict:
    employees_count = db.query(models.Employee).count()
    plans_count = db.query(models.Plan).count()
    facts_count = db.query(models.Fact).count() if hasattr(models, 'Fact') else 0

    return {
        "employees": employees_count,
        "plans": plans_count,
        "facts": facts_count
    }


# ============================================================
# ПИТАНИЕ
# ============================================================
MEAL_EXCLUDED_EMPLOYEES = ['Корнеева Елена', 'Миронов Тимофей']
# Планы, при которых сотрудник в список питания не попадает:
# «О» — отпуск, «Б» — больничный, «Б/С» — без сохранения заработной платы.
# Значение из базы нормализуется: регистр, пробелы и точки не важны,
# поэтому «б/с», «Б/С» и «БС» — одно и то же.
MEAL_EXCLUDED_PLAN_TYPES = ('О', 'Б', 'Б/Л', 'БЛ', 'Б/С', 'БС')
# Подмены имён в списке питания больше нет: выводим ФИО как в справочнике.


def collect_meal_employees(db, target_date: date) -> list[dict]:
    """Сотрудники, которые попадают в список питания на дату.

    Отдельная функция нужна, чтобы правила отбора были ровно в одном месте:
    их использует и выгрузка в Excel, и предпросмотр списка на экране.
    """
    # Получаем ВСЕХ сотрудников через plan-fact (как на фронтенде)
    # Используем ту же логику, что и в get_plan_fact
    employees_data = get_plan_fact(
        db=db,
        date_from=target_date,
        date_to=target_date
    )

    print(f"📊 Получено записей из plan-fact: {len(employees_data)}")

    # Собираем уникальных сотрудников по тем же критериям, что и на фронтенде
    employees_map = {}

    for row in employees_data:
        employee_name = row.get('employee_name')
        if not employee_name:
            continue

        # Проверяем план
        plan_type = row.get('plan_type', '').upper() if row.get('plan_type') else ''
        plan_key = plan_type.replace(' ', '').replace('.', '')

        # Исключаем отпуск («О») и «б/с» — как и в предпросмотре на экране
        if plan_key in MEAL_EXCLUDED_PLAN_TYPES:
            print(f"  ⏭️ Исключен (план {plan_key}): {employee_name}")
            continue

        # Проверяем, есть ли данные для включения в список
        has_plan = plan_type and plan_type != ''
        has_fact = row.get('fact_hours', 0) > 0
        has_production_stage = row.get('production_stage', '') and row.get('production_stage', '').strip() != ''

        # Проверяем, не исключен ли сотрудник по имени
        is_excluded = any(name in employee_name for name in MEAL_EXCLUDED_EMPLOYEES)

        if (has_plan or has_fact or has_production_stage) and not is_excluded:
            display_name = employee_name
            if display_name not in employees_map:
                employees_map[display_name] = {
                    'name': display_name
                }
                print(
                    f"  ✅ Добавлен: {display_name} (план={plan_type}, факт={has_fact}, этапы={has_production_stage})")

    # Получаем список сотрудников
    employees_list = list(employees_map.values())
    employees_list.sort(key=lambda x: x['name'].lower())
    return employees_list


def build_meal_report(db, target_date: date, meal_type: str) -> ReportResult:
    """Выгрузка списка на питание: (файл, имя) или предупреждение «нет данных»."""
    from openpyxl.worksheet.properties import PageSetupProperties

    # Определяем стоимость
    cost = 165 if meal_type == "morning" else 460
    meal_name = "Кафе утро" if meal_type == "morning" else "Кафе обед"

    print(f"📊 Выгрузка питания: {meal_name} за {target_date}")
    print(f"📅 Дата: {target_date}")

    employees_list = collect_meal_employees(db, target_date)

    if not employees_list:
        return ReportWarning(
            message=f"Нет сотрудников с данными на {target_date}",
            count=0,
        )

    print(f"👤 Итого сотрудников: {len(employees_list)}")

    # Создаем Excel файл
    wb = Workbook()
    ws = wb.active
    ws.title = "Питание"

    # Шрифт Times New Roman 14 для всего документа
    default_font = Font(name='Times New Roman', size=14)

    # Определяем стили
    header_font = Font(name='Times New Roman', bold=True, size=14)  # без заливки шапки
    header_alignment = Alignment(horizontal='center', vertical='center')

    title_font = Font(name='Times New Roman', bold=True, size=14)
    title_alignment = Alignment(horizontal='center', vertical='center')

    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    thick_border = Border(
        left=Side(style='medium'),
        right=Side(style='medium'),
        top=Side(style='medium'),
        bottom=Side(style='medium')
    )

    center_alignment = Alignment(horizontal='center', vertical='center')
    left_alignment = Alignment(horizontal='left', vertical='center')

    # ============================================================
    # 1. КОЛОНТИТУЛ - ЗАГОЛОВОК
    # ============================================================
    ws.merge_cells('A1:D1')
    title_cell = ws.cell(row=1, column=1, value='Журнал учета питания работников ООО "МегаТек"')
    title_cell.font = title_font
    title_cell.alignment = title_alignment

    # Дата выгрузки
    ws.merge_cells('A2:D2')
    date_cell = ws.cell(row=2, column=1, value=f'Дата выгрузки: {target_date.strftime("%d.%m.%Y")}')
    date_cell.font = Font(name='Times New Roman', bold=True, size=14)
    date_cell.alignment = title_alignment

    # Пустая строка для отступа
    ws.merge_cells('A3:D3')
    ws.cell(row=3, column=1, value='')

    # ============================================================
    # 2. ЗАГОЛОВКИ ТАБЛИЦЫ
    # ============================================================
    headers = ['№', 'ФИО', 'Стоимость питания, руб.', 'подпись']
    header_row = 4

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = header_font
        cell.alignment = header_alignment
        cell.border = thin_border

    # ============================================================
    # 3. ДАННЫЕ
    # ============================================================
    for idx, emp in enumerate(employees_list, 1):
        row = header_row + idx

        # №
        cell = ws.cell(row=row, column=1, value=idx)
        cell.font = default_font
        cell.border = thin_border
        cell.alignment = center_alignment

        # ФИО
        cell = ws.cell(row=row, column=2, value=emp['name'])
        cell.font = default_font
        cell.border = thin_border

        # Стоимость
        cell = ws.cell(row=row, column=3, value=cost)
        cell.font = default_font
        cell.border = thin_border
        cell.alignment = center_alignment

        # Подпись (пустая)
        cell = ws.cell(row=row, column=4, value="")
        cell.font = default_font
        cell.border = thin_border

    # ============================================================
    # 4. ДОБАВЛЯЕМ ПУСТЫЕ СТРОКИ ПОСЛЕ ПОСЛЕДНЕГО СОТРУДНИКА
    # ============================================================
    last_data_row = header_row + len(employees_list)

    # Если сотрудников 28 и больше — 3 пустые строки, если 27 и меньше — 5
    empty_rows = 3 if len(employees_list) >= 28 else 5
    for i in range(1, empty_rows + 1):
        row = last_data_row + i
        for col in range(1, 5):
            cell = ws.cell(row=row, column=col, value="")
            cell.border = thin_border

    # ============================================================
    # 5. ОТВЕТСТВЕННЫЙ (после пустых строк)
    # ============================================================
    resp_row = last_data_row + empty_rows + 1

    # Ячейка с текстом "Ответственный за выдачу питания" (выровнено по левому краю)
    resp_cell = ws.cell(row=resp_row, column=1, value='Ответственный за выдачу питания')
    resp_cell.font = Font(name='Times New Roman', bold=True, size=14)
    resp_cell.alignment = left_alignment
    resp_cell.border = thick_border

    # Объединяем первые 3 колонки для текста
    ws.merge_cells(
        start_row=resp_row,
        start_column=1,
        end_row=resp_row,
        end_column=3
    )

    # Ячейка для подписи (колонка D) с границами
    sign_cell = ws.cell(row=resp_row, column=4, value="")
    sign_cell.font = default_font
    sign_cell.border = thick_border
    sign_cell.alignment = center_alignment

    # ============================================================
    # 6. НАСТРОЙКА ШИРИНЫ КОЛОНОК
    # ============================================================
    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 45
    ws.column_dimensions['C'].width = 21
    ws.column_dimensions['D'].width = 28

    # ============================================================
    # 7. ВЫСОТА СТРОК
    # ============================================================
    ws.row_dimensions[1].height = 35  # Заголовок
    ws.row_dimensions[2].height = 30  # Дата
    # Все строки таблицы (шапка, данные, пустые, ответственный) — высота 22
    for r in range(header_row, resp_row + 1):
        ws.row_dimensions[r].height = 22

    # ============================================================
    # 8. НАСТРОЙКА ПЕЧАТИ: все колонки в ширину одной страницы,
    # чтобы колонка «подпись» не уезжала на вторую страницу
    # ============================================================
    ws.print_area = f'A1:D{resp_row}'
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = 9  # A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0  # по высоте — сколько нужно страниц
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins.left = 0.43
    ws.page_margins.right = 0.43
    ws.page_margins.top = 0.85
    ws.page_margins.bottom = 0.35

    # Сохраняем в BytesIO
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"Питание_{meal_name}_{target_date.strftime('%d.%m.%Y')}.xlsx"
    encoded_filename = urllib.parse.quote(filename)

    return ReportFile(
        stream=output,
        filename=filename,
        content_disposition=f"attachment; filename*=UTF-8''{encoded_filename}",
    )


# ============================================================
# ПЛАН-ФАКТ: НЕДЕЛЯ И МЕСЯЦ
# ============================================================
def _empty_period_report(title: str, filename: str) -> ReportFile:
    """Лист-подсказка, когда за период нет данных (как было в эндпоинтах)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "План-Факт"
    ws['A1'] = title
    ws['A1'].font = Font(size=14, bold=True)

    ws['A3'] = "Возможные причины:"
    ws['A4'] = "1. Не загружен график (план)"
    ws['A5'] = "2. Не загружен журнал (факт)"
    ws['A6'] = "3. Нет данных за выбранный период"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return ReportFile(
        stream=output,
        filename=filename,
        content_disposition=f"attachment; filename={filename}",
    )


def build_week_report(db, week_id: int,
                      year: Optional[int] = None,
                      month: Optional[int] = None) -> ReportFile:
    """Выгрузка план-факта за неделю месяца."""
    week = next((w for w in WEEKS if w['id'] == week_id), None)
    if not week:
        raise ValueError("Неверный ID недели")

    # Если не переданы год и месяц - используем текущие
    if not year or not month:
        today = date.today()
        year = today.year
        month = today.month

    # Проверяем, что даты существуют
    try:
        date_from = date(year, month, week['start'])
        date_to = date(year, month, week['end'])
    except ValueError:
        # Если дата не существует (например 31 февраля), корректируем
        if week['end'] == 31:
            if month == 2:
                date_to = date(year, month, 28)
            elif month in [4, 6, 9, 11]:
                date_to = date(year, month, 30)
            else:
                date_to = date(year, month, 31)
            date_from = date(year, month, week['start'])
        else:
            raise

    print(f"📊 Выгрузка недели {week['label']} за {month}.{year}")

    data = get_plan_fact(
        db=db,
        date_from=date_from,
        date_to=date_to
    )

    if not data or len(data) == 0:
        filename = f"Plan_Fact_week_{week['label']}_empty.xlsx"
        return _empty_period_report(
            f"Нет данных за неделю {week['label']} ({month}.{year})", filename)

    excel_file = create_plan_fact_matrix_report(data, f"План-Факт неделя {week['label']}")
    filename = f"Plan_Fact_week_{week['label']}.xlsx"

    return ReportFile(
        stream=excel_file,
        filename=filename,
        content_disposition=f"attachment; filename={filename}",
    )


def build_month_report(db,
                       year: Optional[int] = None,
                       month: Optional[int] = None) -> ReportFile:
    """Выгрузка план-факта за месяц."""
    # Если не переданы год и месяц - используем текущие
    if not year or not month:
        today = date.today()
        year = today.year
        month = today.month

    date_from = date(year, month, 1)
    if month == 12:
        date_to = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        date_to = date(year, month + 1, 1) - timedelta(days=1)

    print(f"📊 Выгрузка за {month}.{year}")

    data = get_plan_fact(
        db=db,
        date_from=date_from,
        date_to=date_to
    )

    if not data or len(data) == 0:
        filename = f"Plan_Fact_{year}_{month}_empty.xlsx"
        return _empty_period_report(
            f"Нет данных за {MONTH_NAMES[month - 1]} {year}", filename)

    excel_file = create_plan_fact_matrix_report(
        data, f"План-Факт {MONTH_NAMES[month - 1]} {year}")
    filename = f"Plan_Fact_{year}_{month}.xlsx"

    return ReportFile(
        stream=excel_file,
        filename=filename,
        content_disposition=f"attachment; filename={filename}",
    )


# ============================================================
# ИЗМЕНЕНИЕ ДАННЫХ (правка ячеек на вкладке «План-Факт»)
# ============================================================
def update_time(db, employee_name: str, date_str: str, field: str, value: str) -> dict:
    """Приход/уход сотрудника за день. Часы считаются из разницы времени."""
    employee = db.query(models.Employee).filter_by(name=employee_name).first()
    if not employee:
        raise ServiceError(404, "Сотрудник не найден")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    if field not in ['start_time', 'end_time']:
        raise ServiceError(400, "Поле должно быть start_time или end_time")

    fact = db.query(models.Fact).filter(
        models.Fact.employee_id == employee.id,
        models.Fact.date == target_date
    ).first()

    if fact:
        if field == 'start_time':
            fact.start_time = value
        else:
            fact.end_time = value

        if fact.start_time and fact.end_time:
            try:
                start_h, start_m = map(int, fact.start_time.split(':'))
                end_h, end_m = map(int, fact.end_time.split(':'))

                start_min = start_h * 60 + start_m
                end_min = end_h * 60 + end_m

                if end_min < start_min:
                    end_min += 24 * 60

                diff_min = end_min - start_min
                fact.fact_hours = round(diff_min / 60, 2)
            except:                                   # noqa: E722 — как было в app.py
                fact.fact_hours = 0
        else:
            fact.fact_hours = 0

        db.commit()

        return {
            "status": "success",
            "message": f"Обновлено {field} для {employee.name} на {target_date}",
            "start_time": fact.start_time,
            "end_time": fact.end_time,
            "fact_hours": fact.fact_hours
        }

    new_fact = models.Fact(
        employee_id=employee.id,
        date=target_date,
        start_time=value if field == 'start_time' else "",
        end_time=value if field == 'end_time' else "",
        fact_hours=0
    )
    db.add(new_fact)
    db.commit()

    return {
        "status": "success",
        "message": f"Создан факт для {employee.name} на {target_date}",
        "start_time": new_fact.start_time,
        "end_time": new_fact.end_time,
        "fact_hours": 0
    }


def update_production_stage(db, employee_name: str, date_str: str, value: str) -> dict:
    """Этап производства за день."""
    employee = db.query(models.Employee).filter_by(name=employee_name).first()
    if not employee:
        raise ServiceError(404, "Сотрудник не найден")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    fact = db.query(models.Fact).filter(
        models.Fact.employee_id == employee.id,
        models.Fact.date == target_date
    ).first()

    if fact:
        fact.production_stage = value
        db.commit()

        return {
            "status": "success",
            "message": f"Обновлен этап производства для {employee.name} на {target_date}",
            "production_stage": fact.production_stage
        }

    new_fact = models.Fact(
        employee_id=employee.id,
        date=target_date,
        start_time="",
        end_time="",
        fact_hours=0,
        production_stage=value
    )
    db.add(new_fact)
    db.commit()

    return {
        "status": "success",
        "message": f"Создан факт с этапом производства для {employee.name} на {target_date}",
        "production_stage": new_fact.production_stage
    }


def update_plan(db, employee_name: str, date_str: str, value: str) -> dict:
    """План на день. Значение переносится ещё и в файл графика."""
    employee = db.query(models.Employee).filter_by(name=employee_name).first()
    if not employee:
        raise ServiceError(404, "Сотрудник не найден")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    # С ноября 2026 смена в плане обозначается «Я»/«В»: введённые «11»/«9»/«8»/«Д»
    # приводим к схеме месяца, чтобы план и график не расходились.
    value = shift_codes.canonical((value or '').strip(), target_date)

    plan = db.query(models.Plan).filter(
        models.Plan.employee_id == employee.id,
        models.Plan.date == target_date
    ).first()

    if not value:
        # Пустое значение — убираем план на этот день
        if plan:
            db.delete(plan)
            db.commit()
        synced = sync_schedule_from_plan(employee.name, target_date, '')
        return {
            "status": "success",
            "message": f"План на {target_date} для {employee.name} очищен"
                       + (f" (в графике {synced['sheet']} тоже очищено)" if synced.get('updated') else ""),
            "plan_type": "",
            "schedule": synced
        }

    if plan:
        plan.plan_type = value
    else:
        db.add(models.Plan(
            employee_id=employee.id,
            date=target_date,
            plan_type=value
        ))
    db.commit()

    synced = sync_schedule_from_plan(employee.name, target_date, value)
    return {
        "status": "success",
        "message": f"Обновлен план для {employee.name} на {target_date}: {value}"
                   + (f" (перенесено в график {synced['sheet']})" if synced.get('updated') else
                      (f" (в график не перенесено: {synced.get('reason')})" if synced.get('reason') else "")),
        "plan_type": value,
        "schedule": synced
    }


def delete_employee_from(db, employee_name: str,
                         date_from: date, date_to: date) -> dict:
    """Удаляет планы и факты сотрудника за период (с недели до конца месяца)."""
    emp = db.query(models.Employee).filter(models.Employee.name == employee_name).first()
    if not emp:
        raise ServiceError(404, f"Сотрудник не найден: {employee_name}")

    deleted_plans = db.query(models.Plan).filter(
        models.Plan.employee_id == emp.id,
        models.Plan.date >= date_from,
        models.Plan.date <= date_to
    ).delete()

    deleted_facts = db.query(models.Fact).filter(
        models.Fact.employee_id == emp.id,
        models.Fact.date >= date_from,
        models.Fact.date <= date_to
    ).delete() if hasattr(models, 'Fact') else 0

    db.commit()

    # убираем смены этого сотрудника и в графике — чтобы таблицы не расходились
    synced = clear_schedule_days_for_employee(emp.name, date_from, date_to)

    print(f"🗑️ Удалены данные сотрудника {emp.name} за {date_from} - {date_to}: "
          f"{deleted_plans} планов, {deleted_facts} фактов, "
          f"в графике очищено {synced.get('cleared', 0)} дней")

    return {
        "status": "success",
        "message": f"Удалены данные сотрудника «{emp.name}»: {deleted_plans} планов, "
                   f"{deleted_facts} фактов"
                   + (f", в графике очищено {synced['cleared']} дней" if synced.get('cleared') else ""),
        "deleted_plans": deleted_plans,
        "deleted_facts": deleted_facts,
        "schedule": synced
    }
