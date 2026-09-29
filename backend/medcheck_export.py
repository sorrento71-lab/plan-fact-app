# medcheck_export.py — выгрузка графика прохождения медицинских осмотров
# (форма «Приложение Б»). Список формируется по графику смен: в него попадают
# сотрудники, у которых за выбранный месяц стоят смены 11, 9 или 8.
import os
import re
from collections import Counter
from copy import deepcopy
from datetime import date
from io import BytesIO

from docx import Document
from openpyxl import load_workbook

import models
import shift_codes
from schedule_grid import (SCHEDULE_FILE, _is_empty, _is_placeholder_name, _sheet_for,
                           _visible_layout)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(ROOT_DIR, 'Приложение Б.docx')

# Набор кодов смен зависит от месяца: до ноября 2026 — 11/9/8,
# с ноября 2026 — «Я» (основная) и «В» (доп смена). См. shift_codes.
DEFAULT_START_TIME = '08:00'   # стандартное начало смены, если журнала за месяц нет
# Подразделение в строке «_______ на _______ 20__ г.» — в родительном падеже:
# строка читается «График … работников <подразделение> на <месяц> 20__ г.»
DEPARTMENT_NAME = 'производственного отдела'
MONTHS_RU = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
             'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
# родительный падеж — для даты вида «на 08 октября 2026 г.»
MONTHS_RU_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']


def _norm_text(value):
    return ' '.join(str(value).split()).strip().lower().replace('ё', 'е')


def collect_medcheck_rows(db, year, month, day=None):
    """Сотрудники из графика за месяц, у которых есть смены этого месяца.

    До ноября 2026 это смены 11, 9 или 8, с ноября 2026 — «Я» и «В».
    Если указан день — только те, у кого смена стоит именно в этот день.
    Служебные строки графика («вакансия» и подобные) в список не попадают.
    """
    if not os.path.exists(SCHEDULE_FILE):
        return None, 'Файл графика не найден'

    year, month = int(year), int(month)
    day = int(day) if day else None
    shift_values = shift_codes.shift_values(date(year, month, 1))
    shift_keys = {code.upper() for code in shift_values}
    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, year, month)
    if ws is None:
        return None, f'В файле графика нет листа за {month:02d}.{year}'

    header_row, day_cols, _kept, max_row = _visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return None, 'В листе не найдены дни месяца'

    if day is not None and day not in day_cols.values():
        return None, f'В листе {month:02d}.{year} нет {day}-го числа'

    # начало смены берём из журнала — самое частое время прихода за месяц
    start_times = {}
    if db is not None:
        month_start = date(year, month, 1)
        month_end = date(year, month, 28)
        if month == 12:
            month_end = date(year, 12, 31)
        facts = db.query(models.Fact).filter(models.Fact.date >= month_start,
                                             models.Fact.date <= month_end).all()
        if day:
            facts = [f for f in facts if f.date.day == day]
        by_employee = {}
        for fact in facts:
            by_employee.setdefault(fact.employee_id, []).append(fact.start_time)
        if by_employee:
            ids = {e.id: e.name for e in db.query(models.Employee).all()}
            for emp_id, times in by_employee.items():
                clean = [t for t in times if t]
                if clean and emp_id in ids:
                    start_times[_norm_text(ids[emp_id])] = Counter(clean).most_common(1)[0][0]

    rows = []
    for r in range(header_row + 2, max_row + 1):
        name = ws.cell(r, 3).value
        name = str(name).strip() if name else ''
        if not name:
            continue
        # «вакансия» и подобные служебные строки — не люди: в именной документ
        # медосмотра они не попадают (та же проверка, что и в сетке графика)
        if _is_placeholder_name(name):
            continue

        month_shifts = []
        day_shifts = []
        for c, d in day_cols.items():
            value = ws.cell(r, c).value
            text = '' if value is None else str(value).strip()
            if not text:
                continue
            # код приводим к схеме месяца: в листе с ноября 2026 может остаться
            # «11»/«9»/«8» (например, после ручной правки) — это та же основная смена
            code = shift_codes.canonical(text, date(year, month, d))
            if code.upper().replace('Ё', 'Е') not in shift_keys:
                continue
            month_shifts.append(code)
            if day is not None and d == day:
                day_shifts.append(code)

        shifts = day_shifts if day is not None else month_shifts
        if not shifts:
            continue

        position = ws.cell(r, 4).value
        rows.append({
            'name': name,
            'position': str(position).strip() if position else '',
            # время начала смены: из журнала, если он загружен, иначе стандартные 08:00
            'start_time': start_times.get(_norm_text(name)) or DEFAULT_START_TIME,
            'shifts': sorted({s.upper() for s in shifts}, key=_shift_sort_key),
            'days': len(month_shifts),
        })

    if not rows:
        where = f'{day:02d}.{month:02d}.{year}' if day else f'{month:02d}.{year}'
        return None, (f'В графике за {where} нет смен '
                      f'({shift_codes.describe(date(year, month, 1))})')
    return rows, None


def _shift_sort_key(value):
    """Порядок кодов смен в подсказках: как в легенде месяца."""
    order = ('Я', 'В', '11', '9', '8', 'Д')
    key = (value or '').upper()
    return order.index(key) if key in order else len(order)


def _find_employees_table(doc):
    """Таблица со списком сотрудников — ищем по её шапке, а не по номеру.

    В образце может быть ещё таблица-шапка документа (ООО, версия, лист),
    поэтому ориентируемся на заголовки «№ п/п» / «Ф.И.О.».
    """
    for table in doc.tables:
        header = ' '.join(_norm_text(cell.text) for cell in table.rows[0].cells)
        if 'ф.и.о' in header or '№ п/п' in header or 'работник' in header:
            return table
    return None


def _set_cell(cell, text):
    """Пишем текст в ячейку, сохраняя оформление первого фрагмента."""
    paragraph = cell.paragraphs[0]
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ''
    else:
        paragraph.add_run(text)


def build_medcheck_docx(db, year, month, day=None):
    """Формирует документ медосмотра по образцу «Приложение Б». Возвращает (файл, имя)."""
    if not os.path.exists(SAMPLE_FILE):
        return None, 'Не найден образец «Приложение Б.docx»'
    if not os.path.exists(SCHEDULE_FILE):
        return None, 'Файл графика не найден'

    rows, error = collect_medcheck_rows(db, year, month, day)
    if error:
        return None, error

    year, month = int(year), int(month)
    day = int(day) if day else None
    doc = Document(SAMPLE_FILE)

    # период в строке «___ на ____________ 20__ г.»
    if day:
        period = f'на {day:02d} {MONTHS_RU_GEN[month - 1]} {year} г.'
    else:
        period = f'на {MONTHS_RU[month - 1]} {year} г.'
    for paragraph in doc.paragraphs:
        if 'на ____________ 20__ г.' in paragraph.text:
            # подставляем подразделение вместо линии для заполнения и период
            text = re.sub(r'_{4,}', DEPARTMENT_NAME.replace('\\', '\\\\'), paragraph.text, count=1)
            text = text.replace('на ____________ 20__ г.', period)
            for run in paragraph.runs:
                run.text = ''
            if paragraph.runs:
                paragraph.runs[0].text = text
            else:
                paragraph.add_run(text)

    # подсказка «(наименование структурного подразделения)» при заполненном
    # названии не нужна — убираем её из выгрузки
    for paragraph in list(doc.paragraphs):
        if paragraph.text.strip().lower().startswith('(наименование'):
            paragraph._element.getparent().remove(paragraph._element)

    table = _find_employees_table(doc)
    if table is None:
        return None, 'В образце «Приложение Б.docx» не найдена таблица со списком сотрудников'
    header = [_norm_text(cell.text) for cell in table.rows[0].cells]

    def column_index(*fragments):
        """Номер колонки по её заголовку — чтобы правки образца не ломали выгрузку."""
        for i, text in enumerate(header):
            if all(fragment in text for fragment in fragments):
                return i
        return None

    columns = {
        'num': column_index('№'),
        'name': column_index('ф.и.о') or column_index('фио') or column_index('работник'),
        'position': column_index('должность'),
        'start': column_index('начало смены'),
        'note': column_index('примечание'),
    }

    template = deepcopy(table.rows[1]._tr)
    for row in list(table.rows)[1:]:
        table._tbl.remove(row._tr)

    for index, emp in enumerate(rows, start=1):
        table._tbl.append(deepcopy(template))
        cells = table.rows[-1].cells
        values = {
            'num': f'{index}.',
            'name': emp['name'],
            'position': emp['position'],
            'start': emp['start_time'],
            'note': '',
        }
        for key, value in values.items():
            column = columns.get(key)
            if column is not None and column < len(cells):
                _set_cell(cells[column], value)

    stream = BytesIO()
    doc.save(stream)
    stream.seek(0)
    suffix = f'_{day:02d}' if day else ''
    filename = f'Медосмотр_{month:02d}.{year}{suffix}.docx'
    return stream, filename


def medcheck_summary(db, year, month, day=None, with_days=False):
    """Кто попадёт в список медосмотра: за месяц или за конкретный день."""
    rows, error = collect_medcheck_rows(db, year, month, day)
    if error:
        return {'status': 'error', 'message': error}

    result = {
        'status': 'success',
        'month': f'{int(month):02d}.{int(year)}',
        'day': int(day) if day else None,
        'employees': len(rows),
        # Ключи — коды смен этого месяца: «Я»/«В» с ноября 2026, иначе 11/9/8.
        'by_shift': {
            code: sum(1 for r in rows
                      if code.upper() in {s.upper() for s in r['shifts']})
            for code in shift_codes.shift_values(date(int(year), int(month), 1))
        },
        'shift_codes': shift_codes.legend(date(int(year), int(month), 1)),
        'rows': rows,
    }

    # сколько людей со сменами приходится на каждый день месяца, если он есть в листе
    if with_days:
        counts = {}
        wb = load_workbook(SCHEDULE_FILE)
        ws = _sheet_for(wb, int(year), int(month))
        if ws is not None:
            shift_keys = {code.upper() for code in
                          shift_codes.shift_values(date(int(year), int(month), 1))}
            header_row, day_cols, _kept, max_row = _visible_layout(ws, int(year), int(month))
            if header_row is not None and day_cols:
                for day_number in sorted(day_cols.values()):
                    counts[day_number] = 0
                for r in range(header_row + 2, max_row + 1):
                    name = ws.cell(r, 3).value
                    if not (name and str(name).strip()):
                        continue
                    if _is_placeholder_name(str(name).strip()):
                        continue     # служебные строки в счётчик не входят
                    for c, day_number in day_cols.items():
                        value = ws.cell(r, c).value
                        text = '' if value is None else str(value).strip()
                        if not text:
                            continue
                        code = shift_codes.canonical(
                            text, date(int(year), int(month), day_number))
                        if code.upper().replace('Ё', 'Е') in shift_keys:
                            counts[day_number] = counts.get(day_number, 0) + 1
        result['by_day'] = counts

    return result
