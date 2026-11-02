# schedule_grid.py — данные графика (форма А3) для вкладки «График».
# Отдаёт структуру листа с цветами и сравнением с планом из БД,
# а также сохраняет изменения ячеек (в файл графика и в план БД)
# и добавление новых сотрудников.
import os
import re
import shutil
from collections import Counter
from datetime import datetime, date
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter, column_index_from_string

import models
import shift_codes

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_FILE = os.path.join(ROOT_DIR, 'ГРАФИК_ФОРМА A3.xlsx')
BACKUP_FILE = os.path.join(ROOT_DIR, 'ГРАФИК_ФОРМА A3.backup.xlsx')

THEME_NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
THEME_ORDER = ['lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2',
               'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink']

# Сокращённые названия дней недели (0 — понедельник)
WEEKDAYS_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

INDEXED_COLORS = {0: '000000', 1: 'FFFFFF', 2: 'FF0000', 3: '00FF00', 4: '0000FF',
                  5: 'FFFF00', 6: 'FF00FF', 7: '00FFFF', 64: '000000'}

# Цвета для значений графика (как размечено в исходном файле).
# «в» (доп смена с ноября 2026) красится так же, как «д» — жёлтым;
# «я» (основная смена) заливки не имеет, как и прежние «11»/«9»/«8».
VALUE_COLORS = {
    'д': 'FFFF00',    # доп смена (до ноября 2026) — жёлтый
    'в': 'FFFF00',    # доп смена (с ноября 2026) — жёлтый
    'о': '92D050',    # отпуск — зелёный
    'б': 'FF0000',    # больничный — красный
    'б/с': 'FFC000',  # б/с — оранжевый
}
# Заливка выходных, если в листе своего фона нет: тот же цвет, каким выходные
# рисует интерфейс (frontend/src/constants.js — «Выходной»).
WEEKEND_FILL_FALLBACK = 'ADD8E6'


def _theme_colors(wb):
    try:
        theme_xml = ET.fromstring(wb.loaded_theme)
    except Exception:
        return []
    scheme = theme_xml.find('.//a:clrScheme', THEME_NS)
    if scheme is None:
        return []
    found = {}
    for el in scheme:
        tag = el.tag.split('}')[-1]
        rgb = None
        srgb = el.find('a:srgbClr', THEME_NS)
        sysclr = el.find('a:sysClr', THEME_NS)
        if srgb is not None:
            rgb = srgb.get('val')
        elif sysclr is not None:
            rgb = sysclr.get('lastClr')
        found[tag] = rgb
    return [found.get(name) for name in THEME_ORDER]


def _apply_tint(rgb, tint):
    if not rgb or not tint:
        return rgb
    try:
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    except (ValueError, TypeError):
        return rgb

    def shift(c):
        c = c * (1 + tint) if tint < 0 else c + (255 - c) * tint
        return max(0, min(255, int(round(c))))

    return f'{shift(r):02X}{shift(g):02X}{shift(b):02X}'


def _color_hex(color, theme_colors):
    if color is None:
        return None
    ctype = getattr(color, 'type', None)
    if ctype == 'rgb':
        rgb = getattr(color, 'rgb', None)
        if isinstance(rgb, str) and len(rgb) >= 6:
            return rgb[-6:].upper()
        return None
    if ctype == 'theme':
        idx = getattr(color, 'theme', None)
        if idx is not None and 0 <= idx < len(theme_colors) and theme_colors[idx]:
            return _apply_tint(theme_colors[idx], getattr(color, 'tint', 0) or 0)
        return None
    if ctype == 'indexed':
        return INDEXED_COLORS.get(getattr(color, 'indexed', None))
    return None


def _fill_hex(cell, theme_colors):
    fill = cell.fill
    if not fill or not fill.patternType:
        return None
    color = _color_hex(fill.fgColor, theme_colors)
    if not color or color == 'FFFFFF':
        return None
    return color


def _has_border(cell):
    b = cell.border
    if not b:
        return False
    return any(getattr(b, side) is not None and getattr(b, side).style
               for side in ('left', 'right', 'top', 'bottom'))


def _norm(value):
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip().lower().replace('ё', 'е')


def _pick_sheet(wb, year, month):
    if year and month:
        wanted = f'{int(month):02d}.{int(year)}'
        for name in wb.sheetnames:
            if name.strip() == wanted:
                return wb[name]
    return wb[wb.sheetnames[0]]


def _weekday_short(year, month, day):
    """День недели для конкретной даты (пн…вс) — считается по календарю."""
    try:
        return WEEKDAYS_SHORT[datetime(int(year), int(month), int(day)).weekday()]
    except (TypeError, ValueError):
        return ''


def _days_in_month(year, month):
    try:
        year, month = int(year), int(month)
        return (datetime(year + (month == 12), (month % 12) + 1, 1) - datetime(year, month, 1)).days
    except (TypeError, ValueError):
        return 0


def _find_header(ws):
    """Строка с числами дней и карта «колонка -> день»."""
    for r in range(1, min(ws.max_row, 15) + 1):
        nums = [c for c in range(1, ws.max_column + 1)
                if isinstance(ws.cell(r, c).value, (int, float))
                and 1 <= int(ws.cell(r, c).value) <= 31]
        if len(nums) >= 20:
            days = {}
            for c in nums:
                days[c] = int(ws.cell(r, c).value)
            return r, days
    return None, {}


def _plan_value_for(value):
    """Цвет заливки для значения графика."""
    key = _norm(value)
    if key in VALUE_COLORS:
        return VALUE_COLORS[key]
    if key.startswith('б/с') or key.startswith('бс'):
        return VALUE_COLORS['б/с']
    return None


def _background_fill(ws, col, first_row, theme_colors):
    """Фоновая заливка колонки дня: у выходных в файле она серая (theme4).

    Определяется по преобладающей заливке в колонке среди ячеек,
    которые не окрашены «значением» (Д/О/Б/б-с, а с ноября 2026 — В):
    так при правке ячейки выходного дня подсветка не теряется.
    """
    value_fills = {c.upper() for c in VALUE_COLORS.values()}
    counts = Counter()
    for r in range(first_row, ws.max_row + 1):
        fill = (_fill_hex(ws.cell(r, col), theme_colors) or '').upper()
        if fill in value_fills:
            continue
        counts[fill] += 1
    if not counts:
        return None
    fill, _ = counts.most_common(1)[0]
    return fill or None


def _ensure_backup():
    if not os.path.exists(BACKUP_FILE):
        shutil.copy2(SCHEDULE_FILE, BACKUP_FILE)


def _is_empty(value):
    return value is None or str(value).strip() == ''


def _hidden_columns(ws, header_row, weekday_row):
    """Служебные колонки, которые не показываем (подпись сотрудника)."""
    hidden = set()
    for c in range(1, ws.max_column + 1):
        head = ' '.join(str(ws.cell(r, c).value or '') for r in range(header_row, weekday_row + 1))
        if head.strip().lower().startswith('подпись'):
            hidden.add(c)
    return hidden


def _visible_layout(ws, year=None, month=None):
    """Шапка, дни и список видимых колонок файла после обрезки.

    Возвращает (header_row, day_cols, kept_cols, max_row); kept_cols —
    колонки файла, которые показываются в интерфейсе по порядку.
    """
    header_row, day_cols = _find_header(ws)
    if header_row is None:
        return None, {}, [], ws.max_row
    weekday_row = header_row + 1
    hidden = _hidden_columns(ws, header_row, weekday_row)

    # дни, которых нет в выбранном месяце (например, 29–30 февраля) — скрываем
    limit = _days_in_month(year, month)
    drop = set()
    if limit:
        for c, d in list(day_cols.items()):
            if d > limit:
                drop.add(c)
                day_cols.pop(c, None)

    used = [c for c in range(1, ws.max_column + 1)
            if c not in hidden and c not in drop
            and any(not _is_empty(ws.cell(r, c).value)
                    for r in range(header_row, ws.max_row + 1))]
    if not used:
        return header_row, day_cols, [], ws.max_row
    kept = [c for c in range(min(used), max(used) + 1) if c not in hidden and c not in drop]
    return header_row, day_cols, kept, ws.max_row


def load_schedule_grid(db=None, year=None, month=None):
    """Структура графика (без служебной шапки и пустых колонок) + сравнение с БД."""
    if not os.path.exists(SCHEDULE_FILE):
        return {'error': f'Файл графика не найден: {os.path.basename(SCHEDULE_FILE)}'}

    wb = load_workbook(SCHEDULE_FILE)
    theme_colors = _theme_colors(wb)
    ws = _pick_sheet(wb, year, month)

    header_row, day_cols, kept_cols, max_row = _visible_layout(ws, year, month)
    if header_row is None:
        return {'error': 'В файле графика не найдена строка с днями месяца'}
    if not kept_cols:
        return {'error': 'Лист графика пуст'}

    weekday_row = header_row + 1

    # --- обрезка: без строк выше шапки и без пустых (без данных) колонок по краям ---
    col_index = {c: i + 1 for i, c in enumerate(kept_cols)}   # колонка файла -> колонка интерфейса
    origin_row, origin_col = header_row, kept_cols[0]

    def adj_r(r):
        return r - origin_row + 1

    def adj_c(c):
        return col_index.get(c, 0)

    # --- сотрудники ---
    section_spans = {}
    for m in ws.merged_cells.ranges:
        if m.min_col == 2 and m.max_col == 2 and m.max_row > m.min_row:
            section_spans[m.min_row] = m.max_row - m.min_row + 1

    employee_rows = {}
    for r in range(weekday_row + 1, max_row + 1):
        emp_name = ws.cell(r, 3).value
        name = str(emp_name).strip() if emp_name is not None else ''
        # Под таблицей идут обозначения смен («Я - основная смена»,
        # «В - дополнительная …» — текст в колонке B, иногда C/D).
        # Это не сотрудники: таблица на них заканчивается.
        legend = False
        for col in (2, 3, 4):
            value = ws.cell(r, col).value
            if value and 'смена' in str(value).casefold():
                legend = True
                break
        if legend:
            break
        # Пустые строки тоже отдаём: в них можно вписать нового сотрудника
        # (клик по строке и по ячейке ФИО доступен и без ФИО).
        employee_rows[r] = {
            'name': name,
            'position': str(ws.cell(r, 4).value).strip() if ws.cell(r, 4).value else '',
            'section': _section_of_row(ws, r),   # участок и для строк внутри объединения
            'section_span': section_spans.get(r, 1),
            'in_db': False,
        }

    # --- план из БД ---
    db_plans = {}
    if db is not None and day_cols:
        employees = {e.name.strip().lower(): e.id for e in db.query(models.Employee).all()}
        for info in employee_rows.values():
            info['in_db'] = info['name'].strip().lower() in employees

        dates = []
        for day in day_cols.values():
            try:
                dates.append(datetime(int(year), int(month), day).date())
            except (TypeError, ValueError):
                pass
        if dates and employees:
            plans = db.query(models.Plan).filter(
                models.Plan.date >= min(dates),
                models.Plan.date <= max(dates),
                models.Plan.employee_id.in_(list(employees.values()))
            ).all()
            id_to_name = {v: k for k, v in employees.items()}
            for p in plans:
                db_plans[(id_to_name.get(p.employee_id), p.date.day)] = p.plan_type or ''

    # --- ячейки ---
    # --- фон выходных ---
    # Серую заливку колонок-выходных отдаём отдельным признаком, а сам цвет —
    # в ответе, чтобы подсветка соответствовала календарю выбранного месяца
    # (в файле может быть лист другого месяца).
    weekend_bg = {}
    for c in day_cols:
        if c not in col_index:
            continue
        file_weekday = _norm(ws.cell(weekday_row, c).value)
        if file_weekday not in ('сб', 'вс'):
            continue
        bg = _background_fill(ws, c, weekday_row + 1, theme_colors)
        if bg:
            weekend_bg[c] = bg.upper()

    cells = []
    stats = {'diff': 0, 'db_missing': 0, 'graf_missing': 0, 'ok': 0, 'no_employee': 0}
    for r in range(origin_row, max_row + 1):
        for c in kept_cols:
            cell = ws.cell(r, c)
            value = cell.value
            fill = _fill_hex(cell, theme_colors)
            border = _has_border(cell)
            text = '' if value is None else str(value).strip()
            item = None

            # заливка выходного дня — не цвет данных, а фон колонки:
            # убираем её, чтобы подсветку рисовал интерфейс по календарю месяца
            if fill and c in weekend_bg and fill.upper() == weekend_bg[c]:
                fill = None

            # буквы дней недели — по календарю выбранного месяца,
            # а не из файла (лист может быть за другой месяц)
            if r == weekday_row and c in day_cols:
                text = _weekday_short(year, month, day_cols[c]) or text

            if text or fill or border:
                item = {'r': adj_r(r), 'c': adj_c(c)}
                if text:
                    item['v'] = text
                if fill:
                    item['fill'] = fill
                if border:
                    item['bd'] = 1
                font = cell.font
                if font and font.bold:
                    item['b'] = 1
                if font and font.italic:
                    item['i'] = 1
                fcolor = _color_hex(font.color, theme_colors) if font and font.color else None
                if fcolor and fcolor != '000000':
                    item['fc'] = fcolor

            if r in employee_rows and c in day_cols:
                info = employee_rows[r]
                db_value = db_plans.get((info['name'].strip().lower(), day_cols[c]))
                # сравнение — в схеме этого месяца: «11»/«9»/«8»/«Д» и «Я»/«В»
                # для ноября 2026 и позже считаются одним и тем же
                try:
                    cmp_date = datetime(int(year), int(month), day_cols[c]).date()
                except (TypeError, ValueError):
                    cmp_date = None
                graf_norm = _norm(shift_codes.canonical(text, cmp_date))
                db_norm = _norm(shift_codes.canonical(db_value, cmp_date))
                if not info['in_db']:
                    status = 'no_employee'
                elif graf_norm == db_norm:
                    status = 'ok'
                elif not db_norm:
                    status = 'db_missing'
                elif not graf_norm:
                    status = 'graf_missing'
                else:
                    status = 'diff'
                stats[status] = stats.get(status, 0) + 1
                if item is None:
                    item = {'r': adj_r(r), 'c': adj_c(c)}
                item['db'] = (db_value or '')
                item['cmp'] = status
                item['editable'] = 1

            # редактируемые текстовые колонки (изменения / подпись)
            elif r in employee_rows and c > max(day_cols.keys()):
                if item is None:
                    item = {'r': adj_r(r), 'c': adj_c(c)}
                item['editable'] = 1

            # данные сотрудника: участок, ФИО, должность
            if r in employee_rows and c in EMPLOYEE_FIELD_COLS:
                if item is None:
                    item = {'r': adj_r(r), 'c': adj_c(c)}
                item['editable'] = 1
                item['ef'] = EMPLOYEE_FIELD_COLS[c]

            if item is not None:
                cells.append(item)

    # --- объединённые ячейки (с обрезкой по видимой области) ---
    merges = []
    for m in ws.merged_cells.ranges:
        r1, r2 = max(m.min_row, origin_row), min(m.max_row, max_row)
        if r1 > r2:
            continue
        span = [c for c in kept_cols if m.min_col <= c <= m.max_col]
        if not span:
            continue
        merges.append({
            'r': adj_r(r1), 'c': adj_c(span[0]),
            'rows': r2 - r1 + 1, 'cols': len(span),
        })

    days = []
    for c, d in sorted(day_cols.items()):
        if c not in col_index:
            continue
        # день недели считаем по календарю выбранного месяца, а не берём из файла:
        # у файла может быть лист другого месяца (например, при просмотре октября)
        wd = ws.cell(weekday_row, c).value
        weekday = _weekday_short(year, month, d) or (str(wd).strip() if wd else '')
        days.append({
            'col': col_index[c],
            'day': d,
            'weekday': weekday,
            'weekend': weekday in ('сб', 'вс'),
        })

    month_days = _days_in_month(year, month)

    return {
        'file': os.path.basename(SCHEDULE_FILE),
        'sheet': ws.title,
        'sheet_month': ws.title.strip(),
        'month_days': month_days,
        'days_in_file': len(days),
        'max_row': max_row - origin_row + 1,
        'max_col': len(kept_cols),
        'origin_row': origin_row,
        'origin_col': origin_col,
        'header_row': 1,
        'weekday_row': 2,
        'first_data_row': 3,
        'days': days,
        'weekend_fill': next(iter(weekend_bg.values()), '73A0B4'),
        'employee_rows': {str(adj_r(k)): v for k, v in employee_rows.items()},
        'merges': merges,
        'cells': cells,
        'stats': stats,
    }


# Колонки данных сотрудника: участок, ФИО, должность
EMPLOYEE_FIELD_COLS = {2: 'section', 3: 'name', 4: 'position'}


def _is_placeholder_name(name):
    """Служебное имя строки («вакансия», строки-легенды) — за ним нет человека."""
    key = _norm(name)
    if (not key) or key.startswith('вакан') or key in ('резерв', 'свободно', 'итого'):
        return True
    # строки-легенды вида «Я-(основная смена )» и «В- (Доп.смена )»:
    # в настоящих ФИО скобок не бывает
    return 'смена' in key and ('(' in key or ')' in key)


def _section_of_row(ws, file_row):
    """Название участка строки (значение может лежать в якоре объединения)."""
    value = ws.cell(file_row, 2).value
    if value is not None and str(value).strip():
        return str(value).strip()
    for m in ws.merged_cells.ranges:
        if m.min_col == 2 and m.max_col == 2 and m.min_row <= file_row <= m.max_row:
            anchor = ws.cell(m.min_row, 2).value
            return str(anchor).strip() if anchor else ''
    return ''


def set_schedule_employee_field(row, field, value, db=None, year=None, month=None):
    """Меняет ФИО, должность или участок сотрудника в графике и в базе.

    ФИО: если строка служебная («вакансия») или такое же ФИО есть ещё в графике,
    создаётся новый сотрудник (его план на месяц пустой, он сразу виден
    в План-Факте). Иначе сотрудник переименовывается — его планы и факты
    остаются при нём.
    """
    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}
    if field not in EMPLOYEE_FIELD_COLS.values():
        return {'status': 'error', 'message': 'Неизвестное поле сотрудника'}

    text = (value or '').strip()
    if field == 'name' and not text:
        return {'status': 'error', 'message': 'ФИО не может быть пустым'}

    _ensure_backup()
    wb = load_workbook(SCHEDULE_FILE)
    ws = _pick_sheet(wb, year, month)
    header_row, _day_cols, _kept, max_row = _visible_layout(ws, year, month)
    if header_row is None:
        return {'status': 'error', 'message': 'В файле графика не найдена строка с днями'}

    file_row = row + header_row - 1
    first_data_row = header_row + 2
    if file_row < first_data_row or file_row > max_row:
        return {'status': 'error', 'message': 'Это не строка сотрудника'}

    old_name = ws.cell(file_row, 3).value
    old_name = str(old_name).strip() if old_name else ''
    if not old_name:
        return {'status': 'error', 'message': 'В строке нет ФИО сотрудника'}

    col = next(c for c, f in EMPLOYEE_FIELD_COLS.items() if f == field)
    old_value = ws.cell(file_row, col).value
    old_value = str(old_value).strip() if old_value else ''

    # --- проверки для ФИО ---
    same_name_rows = [r for r in range(first_data_row, max_row + 1)
                      if _norm(ws.cell(r, 3).value) == _norm(old_name)]
    employee = None
    if db is not None:
        employee = db.query(models.Employee).filter(
            models.Employee.name == old_name).first()

    mode = 'edit'
    same_name_note = ''
    if field == 'name' and _norm(text) != _norm(old_name):
        twin = db.query(models.Employee).filter(
            models.Employee.name == text).first() if db is not None else None
        if twin is not None:
            # такое ФИО уже есть: служебную строку привязываем к нему,
            # а живого сотрудника переименовывать в занятое ФИО не даём
            if _is_placeholder_name(old_name):
                employee = twin
                mode = 'link'
            else:
                return {'status': 'error',
                        'message': f'Сотрудник с ФИО «{text}» уже есть в базе — '
                                   f'укажите другое ФИО'}
        elif employee is not None and not _is_placeholder_name(old_name):
            # обычное переименование: планы и факты остаются за сотрудником
            mode = 'rename'
            if len(same_name_rows) > 1:
                same_name_note = (f'. В графике ещё {len(same_name_rows) - 1} строка '
                                  f'с прежним ФИО — у неё теперь нет сотрудника в базе.')
        else:
            mode = 'create'

    # --- запись в файл ---
    target_row = file_row
    group_rows = [file_row]
    if field == 'section':
        for m in ws.merged_cells.ranges:
            if m.min_col == 2 and m.max_col == 2 and m.min_row <= file_row <= m.max_row:
                target_row = m.min_row
                group_rows = [r for r in range(m.min_row, m.max_row + 1)
                              if ws.cell(r, 3).value and str(ws.cell(r, 3).value).strip()]
                break

    cell = ws.cell(target_row, col)
    if isinstance(cell, MergedCell):
        cell = ws.cell(target_row, col)
    cell.value = text or None

    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    # --- изменения в базе ---
    created_plans = 0
    db_note = ''
    if db is not None:
        if field == 'name':
            if mode == 'rename':
                employee.name = text
                db_note = 'планы и факты сохранены'
            elif mode == 'link':
                db_note = f'строка привязана к сотруднику «{text}» (он уже есть в базе)'
            elif mode == 'create':
                position = ws.cell(file_row, 4).value
                order = db.query(models.Employee).count() + 1
                employee = models.Employee(
                    name=text,
                    position=str(position).strip() if position else '',
                    department=_section_of_row(ws, file_row),
                    order=order,
                )
                db.add(employee)
                db.flush()
                # пустой план на месяц, чтобы сотрудник сразу появился в План-Факте
                days = _days_in_month(year, month)
                if year and month and days:
                    for day in range(1, days + 1):
                        db.add(models.Plan(employee_id=employee.id,
                                           date=date(int(year), int(month), day),
                                           plan_type=''))
                        created_plans += 1
                db_note = (f'добавлен в План-Факт: план на месяц пустой '
                           f'({created_plans} дн.), можно заполнять')
            else:
                db_note = ''      # ФИО не менялось — в базе править нечего
        elif field == 'position' and employee is not None:
            employee.position = text
            db_note = 'должность обновлена'
        elif field == 'section':
            changed = 0
            for r in group_rows:
                nm = ws.cell(r, 3).value
                nm = str(nm).strip() if nm else ''
                if not nm:
                    continue
                e = db.query(models.Employee).filter(models.Employee.name == nm).first()
                if e is not None:
                    e.department = text
                    changed += 1
            db_note = f'участок обновлён у {changed} сотрудников'
        db.commit()

    labels = {'name': 'ФИО', 'position': 'должность', 'section': 'участок'}
    message = f'{labels[field].capitalize()} сохранён' if field != 'name' else 'Сохранено'
    if field == 'name' and mode in ('rename', 'create', 'link'):
        message = f'ФИО изменено: «{old_name}» → «{text}»'
    elif field == 'name':
        message = f'ФИО: «{text}»'
    elif old_value != text:
        message = f'{labels[field].capitalize()} изменён: «{old_value}» → «{text}»'
    else:
        message = f'{labels[field].capitalize()}: «{text}»'
    if db_note:
        message += f' — {db_note}'
    if field == 'name':
        message += same_name_note

    return {
        'status': 'success',
        'message': message,
        'field': field,
        'mode': mode,
        'old_name': old_name,
        'name': text,
        'created_plans': created_plans,
        'db_note': db_note,
    }


def set_schedule_cell(row, col, value, db=None, year=None, month=None):
    """Сохраняет значение ячейки графика: в файл и (для дней) в план БД."""
    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    _ensure_backup()
    wb = load_workbook(SCHEDULE_FILE)
    ws = _pick_sheet(wb, year, month)
    theme_colors = _theme_colors(wb)
    header_row, day_cols, kept_cols, _max_row = _visible_layout(ws, year, month)
    if header_row is None:
        return {'status': 'error', 'message': 'В файле графика не найдена строка с днями'}
    if col < 1 or col > len(kept_cols):
        return {'status': 'error', 'message': 'Колонка недоступна для редактирования'}

    # координаты приходят в системе координат интерфейса (обрезанная таблица)
    origin_row = header_row
    row = row + origin_row - 1
    col = kept_cols[col - 1]

    try:
        cell = ws.cell(row, col)
        if not hasattr(cell, 'value'):
            return {'status': 'error', 'message': 'Эта ячейка объединена — редактирование недоступно'}
    except AttributeError:
        return {'status': 'error', 'message': 'Эта ячейка объединена — редактирование недоступно'}

    text = (value or '').strip()

    # С ноября 2026 в листе действуют коды «Я» (основная) и «В» (доп смена):
    # введённые «11»/«9»/«8»/«Д» приводим к схеме месяца и в файле, и в плане.
    cell_date = None
    if col in day_cols:
        try:
            cell_date = date(int(year), int(month), day_cols[col])
        except (TypeError, ValueError):
            cell_date = None
    text = shift_codes.canonical(text, cell_date)

    cell.value = text or None

    # цвет по стандарту файла; если значения нет в палитре —
    # возвращаем фоновую заливку дня (у выходных она серая)
    color = _plan_value_for(text)
    if color:
        cell.fill = PatternFill('solid', fgColor=color)
    else:
        base = _background_fill(ws, col, header_row + 2, theme_colors)
        cell.fill = PatternFill('solid', fgColor=base) if base else PatternFill(fill_type=None)

    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    # план в БД — только для ячеек дней
    db_result = None
    if db is not None and col in day_cols and row > header_row + 1:
        emp_name = ws.cell(row, 3).value
        emp_name = str(emp_name).strip() if emp_name else ''
        if emp_name:
            employee = db.query(models.Employee).filter(models.Employee.name == emp_name).first()
            if not employee:
                position = ws.cell(row, 4).value
                section = ws.cell(row, 2).value
                max_order = db.query(models.Employee).count()
                employee = models.Employee(
                    name=emp_name,
                    position=str(position).strip() if position else '',
                    department=str(section).strip() if section else '',
                    order=max_order + 1,
                )
                db.add(employee)
                db.flush()

            try:
                target_date = datetime(int(year), int(month), day_cols[col]).date()
            except (TypeError, ValueError):
                target_date = None

            if target_date:
                plan = db.query(models.Plan).filter(
                    models.Plan.employee_id == employee.id,
                    models.Plan.date == target_date
                ).first()
                if text:
                    if plan:
                        plan.plan_type = text
                    else:
                        db.add(models.Plan(employee_id=employee.id, date=target_date, plan_type=text))
                elif plan:
                    db.delete(plan)
                db.commit()
                db_result = {'employee': emp_name, 'date': target_date.isoformat(),
                             'plan_type': text}

    return {
        'status': 'success',
        'message': f'Сохранено: «{text}»' + (f' (план для {db_result["employee"]} на {db_result["date"]})'
                                             if db_result else ''),
        'plan': db_result,
    }


def add_schedule_employee(name, position='', section='', db=None, year=None, month=None):
    """Добавляет сотрудника: в справочник БД и строкой в файл графика."""
    name = (name or '').strip()
    if not name:
        return {'status': 'error', 'message': 'Не указано ФИО'}

    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    _ensure_backup()
    wb = load_workbook(SCHEDULE_FILE)
    ws = _pick_sheet(wb, year, month)
    header_row, _ = _find_header(ws)

    # Строки сотрудников и их участки: участок берём из колонки B, затем A —
    # так же, как это делает парсер графика.
    employee_rows = [r for r in range(header_row + 2, ws.max_row + 1)
                     if ws.cell(r, 3).value and str(ws.cell(r, 3).value).strip()]
    departments = {}
    current = ''
    for r in range(header_row + 2, ws.max_row + 1):
        for col in (2, 1):
            value = ws.cell(r, col).value
            text = str(value).strip() if value is not None else ''
            if text and text.lower() != 'nan':
                current = text
                break
        departments[r] = current

    section_key = _norm(section or '')
    last_of_section = None
    if not employee_rows:
        new_row = header_row + 3
    elif section_key:
        # встаём в конец блока нужного участка, а не в конец всего списка
        same = [r for r in employee_rows if _norm(departments.get(r, '')) == section_key]
        if same:
            last_of_section = max(same)
            new_row = last_of_section + 1
        else:
            new_row = max(employee_rows) + 1
    else:
        new_row = max(employee_rows) + 1

    # Вторая строка сотрудника — «Вн. совм. <должность>» (в листе она курсивом).
    # Вставлять нового человека между сотрудником и этой строкой нельзя: иначе
    # его вторая строка остаётся у предыдущего. Ставим после неё.
    def _is_vn_sovm(r):
        for col in (2, 3, 4):
            value = ws.cell(r, col).value
            if value and 'совм' in str(value).lower():
                return True
        return False

    if _is_vn_sovm(new_row):
        new_row += 1

    # если место занято (следующий участок, служебная строка) — вставляем строку
    # со сдвигом. openpyxl не переносит объединённые ячейки и не двигает их
    # значения, поэтому снимаем объединения ниже точки вставки, запоминаем
    # значения их первых ячеек (там названия участков) и восстанавливаем после.
    if ws.cell(new_row, 3).value and str(ws.cell(new_row, 3).value).strip():
        merged_below = []
        for merged in list(ws.merged_cells.ranges):
            if merged.min_row >= new_row:
                merged_below.append((merged.min_row, merged.min_col, merged.max_row,
                                     merged.max_col,
                                     ws.cell(merged.min_row, merged.min_col).value))
                ws.unmerge_cells(str(merged))

        ws.insert_rows(new_row, 1)

        for min_row, min_col, max_row_, max_col, value in merged_below:
            ws.cell(min_row + 1, min_col).value = value
            ws.merge_cells(start_row=min_row + 1, start_column=min_col,
                           end_row=max_row_ + 1, end_column=max_col)

    # переносим оформление строки-образца
    from copy import copy
    from openpyxl.styles import Border as _Border
    style_row = new_row - 1 if new_row > header_row + 2 else header_row + 2
    for c in range(1, ws.max_column + 1):
        src = ws.cell(style_row, c)
        dst = ws.cell(new_row, c)
        if src.has_style:
            dst._style = copy(src._style)
    # Подпись участка: у существующего участка она уже есть выше (и растянута
    # объединением), поэтому в новой строке ничего не пишем — иначе сотрудник
    # выглядит как отдельный участок. Для нового участка подпись ставим.
    ws.cell(new_row, 2).value = None if last_of_section else (section or None)
    ws.cell(new_row, 3).value = name
    ws.cell(new_row, 4).value = position or None
    for c in range(5, ws.max_column + 1):
        ws.cell(new_row, c).value = None

    # Продлеваем объединение подписи участка на новую строку — чтобы человек
    # визуально остался внутри своего участка (колонки 1–2: участок и ФИО).
    if last_of_section:
        for merged in list(ws.merged_cells.ranges):
            if (merged.min_row < merged.max_row and merged.max_row == last_of_section
                    and merged.min_col <= 2):
                ws.unmerge_cells(str(merged))
                ws.merge_cells(start_row=merged.min_row, start_column=merged.min_col,
                               end_row=merged.max_row + 1, end_column=merged.max_col)

    # Вторая строка сотрудника — «Вн. совм. <должность>» курсивом, как в листе.
    if position:
        vn_row = new_row + 1
        # если сразу под сотрудником стоит чужая строка — освобождаем место
        if ws.cell(vn_row, 3).value and str(ws.cell(vn_row, 3).value).strip():
            ws.insert_rows(vn_row, 1)
            for merged in list(ws.merged_cells.ranges):
                if merged.min_row >= vn_row:
                    ws.unmerge_cells(str(merged))
                    ws.merge_cells(start_row=merged.min_row + 1, start_column=merged.min_col,
                                   end_row=merged.max_row + 1, end_column=merged.max_col)
        for c in range(1, ws.max_column + 1):
            src = ws.cell(new_row, c)
            dst = ws.cell(vn_row, c)
            if isinstance(dst, MergedCell):
                continue
            if src.has_style:
                dst._style = copy(src._style)
            dst.border = _Border()   # строка «Вн. совм.» в листе без рамок
            if c != 4:
                dst.value = None
        vn_cell = ws.cell(vn_row, 4)
        vn_cell.value = f'Вн. совм. {position}'
        vn_font = copy(vn_cell.font)
        vn_font.italic = True
        vn_cell.font = vn_font

    # фон дней новой строки — как у пустой строки: выходные/праздники, без цветов смен
    if year and month:
        try:
            theme_colors = _theme_colors(wb)
            _h, day_cols, _kept, _mx = _visible_layout(ws, int(year), int(month))
            for c, day in (day_cols or {}).items():
                base = _background_fill(ws, c, header_row + 1, theme_colors)
                if not base and (_weekday_short(int(year), int(month), day) or '') in ('сб', 'вс'):
                    base = WEEKEND_FILL_FALLBACK
                cell = ws.cell(new_row, c)
                cell.fill = (PatternFill('solid', fgColor=base) if base
                             else PatternFill(fill_type=None))
        except Exception as exc:  # noqa: BLE001 — вид строки не важнее самой вставки
            print(f"⚠️ Не удалось выставить фон новой строки: {exc}")
    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    created = False
    if db is not None:
        employee = db.query(models.Employee).filter(models.Employee.name == name).first()
        if not employee:
            max_order = db.query(models.Employee).count()
            db.add(models.Employee(name=name, position=position or '',
                                   department=section or '', order=max_order + 1))
            db.commit()
            created = True

    return {
        'status': 'success',
        'message': f'Сотрудник «{name}» добавлен' + (' в справочник и в график' if created
                                                     else ' в график (в базе уже был)'),
        'row': new_row,
        'created': created,
    }


def import_schedule_to_plan(db, year, month):
    """Загружает план из файла графика за выбранный месяц.

    Значения ячеек дней переносятся в план БД: новые добавляются,
    отличающиеся обновляются, совпадающие не трогаются. Пустые ячейки
    графика существующий план НЕ удаляют — их количество возвращается
    отдельным счётчиком.
    """
    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}
    if not year or not month:
        return {'status': 'error', 'message': 'Не указан месяц'}

    year, month = int(year), int(month)
    wanted = f'{month:02d}.{year}'

    wb = load_workbook(SCHEDULE_FILE)
    sheets = [n.strip() for n in wb.sheetnames]
    if wanted not in sheets:
        return {'status': 'error',
                'message': f'В файле графика нет листа за {wanted}. '
                           f'Есть листы: {", ".join(sheets)}. '
                           f'Загрузите график за этот месяц или выберите другой месяц.'}
    ws = wb[wb.sheetnames[sheets.index(wanted)]]

    header_row, day_cols, kept_cols, max_row = _visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return {'status': 'error', 'message': 'В файле графика не найдены дни месяца'}

    col_index = {c: i + 1 for i, c in enumerate(kept_cols)}

    # сотрудники (недостающих создаём, как при правке ячейки)
    employees = {e.name.strip().lower(): e for e in db.query(models.Employee).all()}
    max_order = db.query(models.Employee).count()
    created_employees = []

    # уже существующие планы за месяц
    existing = {}
    month_start = date(year, month, 1)
    month_end = date(year, month, _days_in_month(year, month))
    for p in db.query(models.Plan).filter(
            models.Plan.date >= month_start, models.Plan.date <= month_end).all():
        existing[(p.employee_id, p.date.day)] = p

    added = updated = unchanged = 0
    plan_without_graf = 0

    last_employee = None
    for r in range(header_row + 2, max_row + 1):
        raw_name = ws.cell(r, 3).value
        name = str(raw_name).strip() if raw_name else ''
        if not name:
            # строка «Вн. совм. …» под сотрудником — её смены его же
            mark = ws.cell(r, 4).value
            if last_employee is None or not mark or 'совм' not in str(mark).lower():
                continue
            employee = last_employee
        else:
            key = name.lower()
            employee = employees.get(key)
            if employee is None:
                position = ws.cell(r, 4).value
                department = ws.cell(r, 2).value
                max_order += 1
                employee = models.Employee(
                    name=name,
                    position=str(position).strip() if position else '',
                    department=str(department).strip() if department else '',
                    order=max_order,
                )
                db.add(employee)
                db.flush()
                employees[key] = employee
                created_employees.append(name)
            last_employee = employee

        for c, day in day_cols.items():
            if c not in col_index:
                continue
            raw = ws.cell(r, c).value
            text = '' if raw is None else str(raw).strip()
            plan = existing.get((employee.id, day))

            if not text:
                if plan is not None:
                    plan_without_graf += 1
                continue

            target_date = date(year, month, day)
            # с ноября 2026 старые коды смен приводим к «Я»/«В» и в плане базы
            text = shift_codes.canonical(text, target_date)
            if plan is None:
                new_plan = models.Plan(employee_id=employee.id, date=target_date, plan_type=text)
                db.add(new_plan)
                existing[(employee.id, day)] = new_plan
                added += 1
            elif _norm(plan.plan_type) == _norm(text):
                unchanged += 1
            else:
                plan.plan_type = text
                updated += 1

    db.commit()

    # Смены из строк «Вн. совм. …» переносим в план того же сотрудника
    try:
        import vn_sovm
        vn_result = vn_sovm.apply(db, year, month)
        added += vn_result.get('added', 0)
        updated += vn_result.get('updated', 0)
    except Exception as exc:  # noqa: BLE001 — перенос не должен ломать импорт
        print(f'⚠️ Не удалось перенести смены «Вн. совм.»: {exc}')

    message = (f'Из графика «{wanted}» загружено: добавлено {added}, '
               f'обновлено {updated}, без изменений {unchanged}')
    if plan_without_graf:
        message += f'. Планов, которых нет в графике, оставлено: {plan_without_graf}'
    if created_employees:
        message += f'. Добавлено сотрудников в справочник: {len(created_employees)}'

    return {
        'status': 'success',
        'message': message,
        'sheet': wanted,
        'added': added,
        'updated': updated,
        'unchanged': unchanged,
        'plan_without_graf': plan_without_graf,
        'created_employees': created_employees,
    }


def _sheet_for(wb, year, month):
    """Лист строго за указанный месяц (без подмены другим листом)."""
    if not year or not month:
        return None
    wanted = f'{int(month):02d}.{int(year)}'
    for name in wb.sheetnames:
        if name.strip() == wanted:
            return wb[name]
    return None


def _month_start(year, month):
    """Первое число месяца или None, если месяц не задан."""
    try:
        return date(int(year), int(month), 1)
    except (TypeError, ValueError):
        return None


def _row_shift_value(ws, file_row, day_cols, year=None, month=None):
    """Основное значение смен сотрудника в листе.

    До ноября 2026 это «11»/«9»/«8», с ноября 2026 — «Я»: набор кодов
    берётся у схемы месяца (см. shift_codes).
    """
    allowed = {code.upper() for code in shift_codes.main_shift_values(_month_start(year, month))}
    counts = Counter()
    for c in day_cols:
        value = ws.cell(file_row, c).value
        text = '' if value is None else str(value).strip().upper().replace('Ё', 'Е')
        if text in allowed:
            counts[text] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _fit_cycle_phase(ws, file_row, day_cols, value, year, month, target_date):
    """Подбирает ритм и сдвиг цикла, который лучше всего описывает смены в листе.

    Возвращает ((рабочих, отдыха), сдвиг). До ноября 2026 ритм задан кодом
    (11 — 2 через 2, 9 и 8 — 5 через 2); с ноября код длительность не несёт,
    поэтому варианты 2 через 2 и 5 через 2 перебираются по рисунку месяца.
    """
    best = None
    for on_len, off_len in shift_codes.rhythm_cycles(value, target_date):
        period = on_len + off_len
        for phase in range(period):
            score = 0
            for c, day in day_cols.items():
                try:
                    abs_day = date(int(year), int(month), day).toordinal()
                except ValueError:
                    continue
                expected_on = ((abs_day + phase) % period) < on_len
                raw = ws.cell(file_row, c).value
                text = '' if raw is None else str(raw).strip()
                if _norm(text) == _norm(value):
                    score += 3 if expected_on else -3
                elif text == '':
                    score += 1 if not expected_on else -1
                # отпуск/больничный/прочее — не учитываем
            if best is None or score > best[2]:
                best = ((on_len, off_len), phase, score)
    if best is None:
        return (2, 2), 0
    return best[0], best[1]


def _plan_shift_fill(year, month):
    """Что и куда будет расставлено. Смены в файле не меняются."""
    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    year, month = int(year), int(month)
    wb = load_workbook(SCHEDULE_FILE)
    target = _sheet_for(wb, year, month)
    if target is None:
        return {'status': 'error',
                'message': f'В файле графика нет листа за {month:02d}.{year} — '
                           f'сначала создайте лист за этот месяц'}

    t_header, t_days, _kept, t_max = _visible_layout(target, year, month)
    if t_header is None or not t_days:
        return {'status': 'error', 'message': 'В листе не найдены дни месяца'}

    # источник ритма: сам месяц, если в нём есть смены, иначе предыдущие месяцы
    source = None
    src_year, src_month = year, month
    for _ in range(13):
        ws = _sheet_for(wb, src_year, src_month)
        if ws is not None:
            hdr, days, _k, mx = _visible_layout(ws, src_year, src_month)
            if hdr is not None and days:
                has_shifts = any(_row_shift_value(ws, r, days, src_year, src_month)
                                 for r in range(hdr + 2, mx + 1))
                if has_shifts:
                    source = (ws, src_year, src_month, hdr, days, mx)
                    break
        src_month -= 1
        if src_month == 0:
            src_month = 12
            src_year -= 1
    if source is None:
        return {'status': 'error',
                'message': 'Не нашёл графика со сменами — расставлять не от чего'}

    src_ws, src_year, src_month, src_header, src_days, src_max = source
    src_rows = {}
    for r in range(src_header + 2, src_max + 1):
        name = src_ws.cell(r, 3).value
        name = str(name).strip() if name else ''
        if name:
            src_rows.setdefault(_norm(name), r)

    cells = []
    by_value = Counter()
    skipped = []
    for r in range(t_header + 2, t_max + 1):
        name = target.cell(r, 3).value
        name = str(name).strip() if name else ''
        if not name:
            continue
        src_row = src_rows.get(_norm(name))
        value = _row_shift_value(src_ws, src_row, src_days, src_year, src_month) if src_row else None
        if value is None:
            skipped.append(name)
            continue

        cycle, phase = _fit_cycle_phase(src_ws, src_row, src_days, value,
                                        src_year, src_month, date(year, month, 1))
        on_len, off_len = cycle
        period = on_len + off_len

        for c, day in t_days.items():
            if not _is_empty(target.cell(r, c).value):
                continue
            try:
                day_date = date(year, month, day)
            except ValueError:
                continue
            if ((day_date.toordinal() + phase) % period) < on_len:
                # в лист пишем код в схеме этого месяца: с ноября 2026 — «Я»
                fill_value = shift_codes.canonical(value, day_date) or value
                cells.append({'r': r, 'c': c, 'day': day, 'value': fill_value, 'name': name})
                by_value[fill_value] += 1

    return {
        'status': 'success',
        'year': year,
        'month': month,
        'target': f'{month:02d}.{year}',
        'source': f'{src_month:02d}.{src_year}',
        'cells': cells,
        'filled': len(cells),
        'by_value': {v: by_value.get(v, 0)
                     for v in shift_codes.shift_values(date(year, month, 1))},
        'shift_codes': shift_codes.legend(date(year, month, 1)),
        'employees': len({c['name'] for c in cells}),
        'skipped': sorted(set(skipped)),
    }


def shift_fill_summary(year, month):
    """Сводка для уточняющего вопроса перед расстановкой смен."""
    plan = _plan_shift_fill(year, month)
    if plan.get('status') == 'error':
        return plan
    return {
        'status': 'success',
        'target': plan['target'],
        'source': plan['source'],
        'filled': plan['filled'],
        'employees': plan['employees'],
        'by_value': plan['by_value'],
        'shift_codes': plan.get('shift_codes', []),
        'skipped': plan['skipped'],
    }


def fill_schedule_shifts(db=None, year=None, month=None):
    """Расставляет смены в листе месяца по ритму из графика.

    До ноября 2026 код несёт и длительность, и ритм (11 — 2 через 2,
    9 и 8 — 5 через 2); с ноября 2026 код один — «Я» (основная смена),
    поэтому ритм (2 через 2 или 5 через 2) подбирается по рисунку месяца
    для каждого сотрудника. Уже заполненные дни (в том числе отпуска и
    больничные) не трогаются.
    """
    plan = _plan_shift_fill(year, month)
    if plan.get('status') == 'error':
        return plan
    if not plan['cells']:
        return {'status': 'success',
                'message': f'За {plan["target"]} расставлять нечего — все дни уже заполнены',
                'filled': 0, 'by_value': plan['by_value']}

    _ensure_backup()
    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, plan['year'], plan['month'])
    theme_colors = _theme_colors(wb)
    header_row, day_cols, _k, _mx = _visible_layout(ws, plan['year'], plan['month'])
    # фон дней (у выходных — серый), чтобы цвет клетки соответствовал смене
    base_fill = {}
    for c in day_cols:
        base_fill[c] = _background_fill(ws, c, header_row + 2, theme_colors)

    for cell in plan['cells']:
        target = ws.cell(cell['r'], cell['c'])
        if isinstance(target, MergedCell):
            continue
        target.value = cell['value']
        color = _plan_value_for(cell['value'])
        if color:
            target.fill = PatternFill('solid', fgColor=color)
        elif base_fill.get(cell['c']):
            target.fill = PatternFill('solid', fgColor=base_fill[cell['c']])
        else:
            target.fill = PatternFill(fill_type=None)
    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    # план в базе — чтобы смены сразу появились в План-Факте
    created_employees = []
    if db is not None:
        employees = {e.name.strip().lower(): e for e in db.query(models.Employee).all()}
        max_order = db.query(models.Employee).count()
        month_start = date(plan['year'], plan['month'], 1)
        month_end = date(plan['year'], plan['month'], _days_in_month(plan['year'], plan['month']))
        existing = {(p.employee_id, p.date.day): p for p in db.query(models.Plan).filter(
            models.Plan.date >= month_start, models.Plan.date <= month_end).all()}

        for cell in plan['cells']:
            key = cell['name'].lower()
            employee = employees.get(key)
            if employee is None:
                position = ws.cell(cell['r'], 4).value
                max_order += 1
                employee = models.Employee(
                    name=cell['name'],
                    position=str(position).strip() if position else '',
                    department=_section_of_row(ws, cell['r']),
                    order=max_order,
                )
                db.add(employee)
                db.flush()
                employees[key] = employee
                created_employees.append(cell['name'])

            target_date = date(plan['year'], plan['month'], cell['day'])
            row = existing.get((employee.id, cell['day']))
            if row is None:
                row = models.Plan(employee_id=employee.id, date=target_date,
                                  plan_type=cell['value'])
                db.add(row)
                existing[(employee.id, cell['day'])] = row
            else:
                row.plan_type = cell['value']
        db.commit()

    parts = [f'{v} — {n} дн.' for v, n in plan['by_value'].items() if n]
    message = (f'Смены расставлены за {plan["target"]}: заполнено {plan["filled"]} дн. '
               f'у {plan["employees"]} сотрудников ({", ".join(parts)})')
    if plan['skipped']:
        message += f'. Без смен в {plan["source"]} (пропущены): {", ".join(plan["skipped"][:6])}'
        if len(plan['skipped']) > 6:
            message += f' и ещё {len(plan["skipped"]) - 6}'
    return {
        'status': 'success',
        'message': message,
        'target': plan['target'],
        'source': plan['source'],
        'filled': plan['filled'],
        'employees': plan['employees'],
        'by_value': plan['by_value'],
        'skipped': plan['skipped'],
        'created_employees': created_employees,
    }


def _clone_sheet(wb, src, title, keep_cols):
    """Копия листа с оставленными колонками keep_cols (шапка, оформление, объединения)."""
    from copy import copy as _copy

    dst = wb.create_sheet(title)
    cmap = {c: i + 1 for i, c in enumerate(keep_cols)}

    for row in src.iter_rows():
        for cell in row:
            tc = cmap.get(cell.column)
            if tc is None:
                continue
            new = dst.cell(cell.row, tc)
            if not isinstance(cell, MergedCell):
                new.value = cell.value
            if cell.has_style:
                new._style = _copy(cell._style)

    for m in src.merged_cells.ranges:
        span = [c for c in keep_cols if m.min_col <= c <= m.max_col]
        if not span:
            continue
        dst.merge_cells(start_row=m.min_row, start_column=cmap[span[0]],
                        end_row=m.max_row, end_column=cmap[span[-1]])

    for letter, dim in src.column_dimensions.items():
        if dim.width is None:
            continue
        try:
            tc = cmap.get(column_index_from_string(letter))
        except ValueError:
            continue
        if tc:
            dst.column_dimensions[get_column_letter(tc)].width = dim.width
    for r, dim in src.row_dimensions.items():
        if dim.height:
            dst.row_dimensions[r].height = dim.height

    dst.page_setup.orientation = src.page_setup.orientation
    dst.page_setup.paperSize = src.page_setup.paperSize
    dst.page_setup.fitToWidth = src.page_setup.fitToWidth
    dst.page_setup.fitToHeight = src.page_setup.fitToHeight
    if src.sheet_properties.pageSetUpPr is not None:
        dst.sheet_properties.pageSetUpPr = _copy(src.sheet_properties.pageSetUpPr)
    dst.print_options.horizontalCentered = src.print_options.horizontalCentered
    dst.page_margins = _copy(src.page_margins)
    dst.freeze_panes = src.freeze_panes
    return dst, cmap


def _rhythm_by_row(wb, year, month, ws):
    """Значение ритма, цикл и сдвиг для каждой строки сотрудника."""
    source = None
    src_year, src_month = int(year), int(month)
    for _ in range(13):
        src_ws = _sheet_for(wb, src_year, src_month)
        if src_ws is not None:
            src_hdr, src_days, _k, src_max = _visible_layout(src_ws, src_year, src_month)
            if src_hdr is not None and src_days and any(
                    _row_shift_value(src_ws, r, src_days, src_year, src_month)
                    for r in range(src_hdr + 2, src_max + 1)):
                source = (src_ws, src_year, src_month, src_hdr, src_days, src_max)
                break
        src_month -= 1
        if src_month == 0:
            src_month = 12
            src_year -= 1
    if source is None:
        return {}

    src_ws, src_year, src_month, src_hdr, src_days, src_max = source
    src_rows = {}
    for r in range(src_hdr + 2, src_max + 1):
        name = src_ws.cell(r, 3).value
        name = str(name).strip() if name else ''
        if name:
            src_rows.setdefault(_norm(name), r)

    header_row, _days, _kept, max_row = _visible_layout(ws, year, month)
    result = {}
    for r in range(header_row + 2, max_row + 1):
        name = ws.cell(r, 3).value
        name = str(name).strip() if name else ''
        if not name:
            continue
        src_row = src_rows.get(_norm(name))
        if not src_row:
            continue
        value = _row_shift_value(src_ws, src_row, src_days, src_year, src_month)
        if not value:
            continue
        cycle, phase = _fit_cycle_phase(src_ws, src_row, src_days, value,
                                        src_year, src_month, date(int(year), int(month), 1))
        result[r] = (value, cycle, phase)
    return result


def export_schedule_xlsx(year, month, mode='actual'):
    """Выгрузка графика за месяц в формате формы (шапка утверждения, без «Изменений»).

    mode='actual' — данные как есть; mode='rhythm' — только смены по ритму
    (до ноября 2026 это 11/9/8, с ноября 2026 — «Я» основной смены).
    Возвращает (файл в памяти, имя файла) или (None, текст ошибки).
    """
    from io import BytesIO

    if not os.path.exists(SCHEDULE_FILE):
        return None, 'Файл графика не найден'

    year, month = int(year), int(month)
    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, year, month)
    if ws is None:
        return None, f'В файле графика нет листа за {month:02d}.{year}'

    header_row, day_cols, kept_cols, max_row = _visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return None, 'В листе не найдены дни месяца'

    notes = set(_notes_columns(ws, day_cols, kept_cols))
    filled_cols = [c for c in range(1, ws.max_column + 1)
                   if c not in notes
                   and any(not _is_empty(ws.cell(r, c).value) for r in range(1, max_row + 1))]
    last_col = max(filled_cols) if filled_cols else max(kept_cols)
    keep = [c for c in range(1, last_col + 1) if c not in notes]

    title = f'График {month:02d}.{year}'
    dst, cmap = _clone_sheet(wb, ws, title, keep)
    dst.print_area = f'A1:{get_column_letter(len(keep))}{dst.max_row}'
    # закрепляем только шапку таблицы (дни месяца и дни недели), без колонок
    weekday_row = header_row + 1
    dst.freeze_panes = f'A{weekday_row + 1}'

    if mode == 'rhythm':
        # цвет выходных берём из исходного листа
        theme_colors = _theme_colors(wb)
        weekend_bg = None
        for c in sorted(day_cols):
            if _norm(ws.cell(weekday_row, c).value) in ('сб', 'вс'):
                weekend_bg = _background_fill(ws, c, header_row + 2, theme_colors)
                if weekend_bg:
                    break

        # заливка значений (Д, О, Б, б/с) в выгрузке ритмов не нужна —
        # остаётся только подсветка выходных
        for c, day in day_cols.items():
            tc = cmap.get(c)
            if tc is None:
                continue
            letter = _weekday_short(year, month, day)
            is_weekend = letter in ('сб', 'вс')
            fill = (PatternFill('solid', fgColor=weekend_bg)
                    if (is_weekend and weekend_bg) else PatternFill(fill_type=None))
            for r in range(header_row, max_row + 1):
                cell = dst.cell(r, tc)
                if not isinstance(cell, MergedCell):
                    cell.fill = fill

        # затем убираем всё, что не ритм, и расставляем смены по циклу
        for r in range(header_row + 2, max_row + 1):
            name = dst.cell(r, 3).value
            if not (name and str(name).strip()):
                continue
            for c in day_cols:
                tc = cmap.get(c)
                if tc is None:
                    continue
                cell = dst.cell(r, tc)
                if not isinstance(cell, MergedCell):
                    cell.value = None
        for r, (value, cycle, phase) in _rhythm_by_row(wb, year, month, ws).items():
            on_len, off_len = cycle
            period = on_len + off_len
            for c, day in day_cols.items():
                tc = cmap.get(c)
                if tc is None:
                    continue
                cell = dst.cell(r, tc)
                if isinstance(cell, MergedCell):
                    continue
                try:
                    day_date = date(year, month, day)
                except ValueError:
                    continue
                if ((day_date.toordinal() + phase) % period) < on_len:
                    cell.value = shift_codes.canonical(value, day_date) or value
                else:
                    cell.value = None

    for name in list(wb.sheetnames):
        if name != title:
            del wb[name]

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    suffix = '_ритмы' if mode == 'rhythm' else ''
    return stream, f'График_{month:02d}.{year}{suffix}.xlsx'


def sync_schedule_from_plan(employee_name, target_date, value):
    """Переносит значение плана в ячейку графика (обратная синхронизация).

    Вызывается при правке плана в План-Факте: та же смена появляется
    в листе графика за нужный месяц. Если листа за этот месяц нет —
    ничего не делаем.
    """
    if not os.path.exists(SCHEDULE_FILE):
        return {'updated': 0, 'reason': 'файл графика не найден'}

    name = (employee_name or '').strip()
    if not name or target_date is None:
        return {'updated': 0, 'reason': 'не указан сотрудник или дата'}

    year, month = int(target_date.year), int(target_date.month)
    wanted = f'{month:02d}.{year}'
    text = shift_codes.canonical((value or '').strip(), target_date)

    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, year, month)
    if ws is None:
        return {'updated': 0, 'sheet': None,
                'reason': f'в файле графика нет листа за {wanted}'}

    header_row, day_cols, _kept, max_row = _visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return {'updated': 0, 'sheet': wanted, 'reason': 'в листе не найдены дни месяца'}

    col = next((c for c, d in day_cols.items() if d == target_date.day), None)
    if col is None:
        return {'updated': 0, 'sheet': wanted,
                'reason': f'в листе нет колонки для {target_date.day}-го числа'}

    theme_colors = _theme_colors(wb)
    color = _plan_value_for(text)
    base = None
    if not color:
        base = _background_fill(ws, col, header_row + 2, theme_colors)

    updated = 0
    for r in range(header_row + 2, max_row + 1):
        cell_name = ws.cell(r, 3).value
        cell_name = str(cell_name).strip() if cell_name else ''
        if _norm(cell_name) != _norm(name):
            continue
        cell = ws.cell(r, col)
        if isinstance(cell, MergedCell):
            continue
        if (str(cell.value).strip() if cell.value is not None else '') == text:
            updated += 1          # значение уже такое же
            continue
        cell.value = text or None
        if color:
            cell.fill = PatternFill('solid', fgColor=color)
        elif base:
            cell.fill = PatternFill('solid', fgColor=base)
        else:
            cell.fill = PatternFill(fill_type=None)
        updated += 1

    if not updated:
        return {'updated': 0, 'sheet': wanted,
                'reason': f'сотрудник «{name}» не найден в листе {wanted}'}

    _ensure_backup()
    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'updated': 0, 'sheet': wanted,
                'reason': 'файл графика открыт в Excel — правка не перенесена'}

    return {'updated': updated, 'sheet': wanted, 'day': target_date.day, 'value': text}


def clear_schedule_days_for_employee(employee_name, date_from, date_to):
    """Очищает ячейки графика сотрудника за период (при удалении данных)."""
    if not os.path.exists(SCHEDULE_FILE) or not employee_name:
        return {'cleared': 0}

    name = str(employee_name).strip()
    wb = load_workbook(SCHEDULE_FILE)
    cleared = 0
    saved_sheets = []
    for month in {(date_from.year, date_from.month), (date_to.year, date_to.month)}:
        ws = _sheet_for(wb, month[0], month[1])
        if ws is None:
            continue
        header_row, day_cols, _kept, max_row = _visible_layout(ws, month[0], month[1])
        if header_row is None or not day_cols:
            continue
        theme_colors = _theme_colors(wb)
        for col, day in day_cols.items():
            try:
                dd = date(month[0], month[1], day)
            except ValueError:
                continue
            if dd < date_from or dd > date_to:
                continue
            for r in range(header_row + 2, max_row + 1):
                cell_name = ws.cell(r, 3).value
                cell_name = str(cell_name).strip() if cell_name else ''
                if _norm(cell_name) != _norm(name):
                    continue
                cell = ws.cell(r, col)
                if isinstance(cell, MergedCell) or _is_empty(cell.value):
                    continue
                cell.value = None
                base = _background_fill(ws, col, header_row + 2, theme_colors)
                cell.fill = (PatternFill('solid', fgColor=base) if base
                             else PatternFill(fill_type=None))
                cleared += 1
        if cleared:
            saved_sheets.append(ws.title)

    if cleared:
        _ensure_backup()
        try:
            wb.save(SCHEDULE_FILE)
        except PermissionError:
            return {'cleared': 0, 'reason': 'файл графика открыт в Excel'}
    return {'cleared': cleared, 'sheets': saved_sheets}


def plan_to_schedule_summary(db, year, month):
    """Сколько дней графика изменится, если перенести в него план из базы."""
    plan = _plan_to_schedule_plan(db, year, month)
    if plan.get('status') == 'error':
        return plan
    return {
        'status': 'success',
        'month': plan['month'],
        'sheet': plan['sheet'],
        'changed': len(plan['cells']),
        'cleared': plan['cleared'],
        'employees': len({c['name'] for c in plan['cells']}),
        'kept': plan['kept'],
        'missing': plan['missing'],
    }


def _plan_to_schedule_plan(db, year, month):
    """Что нужно записать в лист графика из плана базы за месяц."""
    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    year, month = int(year), int(month)
    wanted = f'{month:02d}.{year}'
    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, year, month)
    if ws is None:
        return {'status': 'error',
                'message': f'В файле графика нет листа за {wanted} — сначала создайте лист'}

    header_row, day_cols, _kept, max_row = _visible_layout(ws, year, month)
    if header_row is None or not day_cols:
        return {'status': 'error', 'message': 'В листе не найдены дни месяца'}

    month_start = date(year, month, 1)
    month_end = date(year, month, _days_in_month(year, month))
    employees = {e.id: e.name.strip() for e in db.query(models.Employee).all()}
    plan_by_name = {}
    for p in db.query(models.Plan).filter(models.Plan.date >= month_start,
                                          models.Plan.date <= month_end).all():
        name = employees.get(p.employee_id)
        if not name:
            continue
        plan_by_name[(_norm(name), p.date.day)] = p.plan_type or ''

    cells = []
    kept = 0
    cleared = 0
    for r in range(header_row + 2, max_row + 1):
        raw_name = ws.cell(r, 3).value
        name = str(raw_name).strip() if raw_name else ''
        if not name:
            continue
        key = _norm(name)
        for c, day in day_cols.items():
            cell = ws.cell(r, c)
            if isinstance(cell, MergedCell):
                continue
            current = '' if cell.value is None else str(cell.value).strip()
            new_value = plan_by_name.get((key, day))
            if (key, day) not in plan_by_name:
                if current:
                    kept += 1          # в плане пусто — смену в графике оставляем
                continue
            new_value = (new_value or '').strip()
            # план переносим в схеме того месяца, в который пишем
            day_date = date(year, month, day)
            new_value = shift_codes.canonical(new_value, day_date)
            if _norm(new_value) == _norm(shift_codes.canonical(current, day_date)):
                continue          # значение то же (регистр и лишние пробелы не в счёт)
            if not new_value:
                cleared += 1
            cells.append({'r': r, 'c': c, 'day': day, 'name': name, 'value': new_value})
    sheet_names = {_norm(ws.cell(r, 3).value)
                   for r in range(header_row + 2, max_row + 1) if ws.cell(r, 3).value}
    missing = sorted({name for (name, _day) in plan_by_name if name not in sheet_names})

    return {
        'status': 'success',
        'month': wanted,
        'month_num': month,
        'sheet': wanted,
        'cells': cells,
        'cleared': cleared,
        'kept': kept,
        'missing': sorted(missing),
        'year': year,
    }


def apply_plan_to_schedule(db, year, month):
    """Переносит план из базы в лист графика за месяц (правки План-Факта → график)."""
    plan = _plan_to_schedule_plan(db, year, month)
    if plan.get('status') == 'error':
        return plan
    if not plan['cells']:
        return {'status': 'success',
                'message': f'График за {plan["month"]} уже совпадает с планом — менять нечего',
                'changed': 0, 'kept': plan['kept']}

    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, plan['year'], plan['month_num'])
    theme_colors = _theme_colors(wb)
    base_fill = {}
    for cell in plan['cells']:
        c = cell['c']
        if c not in base_fill:
            base_fill[c] = _background_fill(ws, c, 1, theme_colors)
        target = ws.cell(cell['r'], c)
        if isinstance(target, MergedCell):
            continue
        text = cell['value']
        target.value = text or None
        color = _plan_value_for(text)
        if color:
            target.fill = PatternFill('solid', fgColor=color)
        elif base_fill.get(c):
            target.fill = PatternFill('solid', fgColor=base_fill[c])
        else:
            target.fill = PatternFill(fill_type=None)

    _ensure_backup()
    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    message = (f'План перенесён в график {plan["month"]}: изменено {len(plan["cells"])} дней '
               f'у {len({c["name"] for c in plan["cells"]})} сотрудников')
    if plan['cleared']:
        message += f' (в том числе очищено {plan["cleared"]})'
    if plan['kept']:
        message += f'. Дней со сменой в графике, но без плана в базе, оставлено: {plan["kept"]}'
    return {
        'status': 'success',
        'message': message,
        'month': plan['month'],
        'changed': len(plan['cells']),
        'cleared': plan['cleared'],
        'kept': plan['kept'],
    }


def delete_schedule_employee(row, db=None, year=None, month=None):
    """Удаляет строку сотрудника из листа графика за выбранный месяц.

    Строка убирается из файла (нижние строки сдвигаются вверх), объединённые
    ячейки участков подправляются, название участка сохраняется. Планы и факты
    в базе при этом не трогаются — сотрудник остаётся в План-Факте.
    """
    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    wb = load_workbook(SCHEDULE_FILE)
    ws = _sheet_for(wb, year, month)
    if ws is None:
        return {'status': 'error',
                'message': f'В файле графика нет листа за {int(month):02d}.{int(year)} — '
                           f'сначала создайте лист за этот месяц'}
    header_row, day_cols, _kept, max_row = _visible_layout(ws, year, month)
    if header_row is None:
        return {'status': 'error', 'message': 'В файле графика не найдена строка с днями'}

    file_row = row + header_row - 1
    first_data_row = header_row + 2
    if file_row < first_data_row or file_row > max_row:
        return {'status': 'error', 'message': 'Это не строка сотрудника'}

    raw_name = ws.cell(file_row, 3).value
    name = str(raw_name).strip() if raw_name else ''
    # Пустую строку тоже можно удалить: в базе за ней ничего нет,
    # из листа она просто убирается (ниже строки сдвинутся).

    shifts = sum(1 for c in day_cols if not _is_empty(ws.cell(file_row, c).value))
    section = _section_of_row(ws, file_row)
    section_range = None
    for m in ws.merged_cells.ranges:
        if m.min_col == 2 and m.max_col == 2 and m.min_row <= file_row <= m.max_row:
            section_range = (m.min_row, m.max_row)
            break

    # пересчитываем объединения: всё ниже сдвигается, диапазон с удаляемой строкой сжимается
    merges = list(ws.merged_cells.ranges)
    new_ranges = []
    for m in merges:
        if m.min_row > file_row:
            new_ranges.append((m.min_row - 1, m.min_col, m.max_row - 1, m.max_col))
        elif m.max_row >= file_row:
            r2 = m.max_row - 1
            if r2 > m.min_row:
                new_ranges.append((m.min_row, m.min_col, r2, m.max_col))
        else:
            new_ranges.append((m.min_row, m.min_col, m.max_row, m.max_col))

    for m in merges:
        ws.unmerge_cells(str(m))
    ws.delete_rows(file_row, 1)
    for r1, c1, r2, c2 in new_ranges:
        if (r1, c1) != (r2, c2):
            ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)

    # участок мог «уехать» вместе с удалённой строкой — возвращаем название
    if section and section_range:
        anchor = section_range[0] if section_range[0] < file_row else max(first_data_row, section_range[0] - 1)
        cell = ws.cell(anchor, 2)
        if not isinstance(cell, MergedCell) and _is_empty(cell.value):
            cell.value = section

    _ensure_backup()
    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    # Вторая строка сотрудника — «Вн. совм. …» — удаляется вместе с ним
    try:
        second_deleted = False
        if file_row <= ws.max_row:
            mark = ws.cell(file_row, 4).value
            if mark and 'совм' in str(mark).lower():
                extra = delete_schedule_employee(row, db=None, year=year, month=month)
                second_deleted = extra.get('status') == 'success'
    except Exception as exc:  # noqa: BLE001 — удаление сотрудника уже выполнено
        print(f"⚠️ Не удалось удалить строку «Вн. совм.»: {exc}")
        second_deleted = False

    plans_left = 0
    if db is not None and year and month:
        employee = db.query(models.Employee).filter(models.Employee.name == name).first()
        if employee is not None:
            start = date(int(year), int(month), 1)
            end = date(int(year), int(month), _days_in_month(year, month))
            plans_left = db.query(models.Plan).filter(
                models.Plan.employee_id == employee.id,
                models.Plan.date >= start,
                models.Plan.date <= end).count()

    if name:
        message = f'Сотрудник «{name}» удалён из графика (смен было {shifts})'
    else:
        message = f'Пустая строка удалена из графика (смен было {shifts})'
    if plans_left:
        message += f'. План в базе за этот месяц не тронут: {plans_left} записей'
    return {
        'status': 'success',
        'message': message,
        'name': name,
        'shifts': shifts,
        'plans_left': plans_left,
    }


def create_month_sheet(year, month):
    """Создаёт в файле графика лист за выбранный месяц — пустую форму.

    Форма копируется с имеющегося листа: сотрудники, участки, должности,
    рамки, ширины, объединения и параметры печати сохраняются. Дни месяца
    расставляются по календарю (сколько дней в месяце — столько колонок),
    смены и примечания остаются пустыми. Исходный лист не меняется.
    """
    from copy import copy as _copy

    if not os.path.exists(SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    year, month = int(year), int(month)
    title = f'{month:02d}.{year}'
    days_count = _days_in_month(year, month)
    if not days_count:
        return {'status': 'error', 'message': 'Неверно указан месяц'}

    wb = load_workbook(SCHEDULE_FILE)
    if title in [n.strip() for n in wb.sheetnames]:
        return {'status': 'error', 'message': f'Лист «{title}» уже есть в файле графика'}

    src = wb[wb.sheetnames[0]]
    header_row, day_cols = _find_header(src)
    if header_row is None or not day_cols:
        return {'status': 'error', 'message': 'В файле графика не найдена строка с днями'}
    theme_colors = _theme_colors(wb)

    weekday_row = header_row + 1
    first_data_row = weekday_row + 1
    src_first_day = min(day_cols)
    src_last_day = max(day_cols)
    src_days = len(day_cols)
    shift = days_count - src_days          # +1 для 31-дневного месяца, -2 для 28-дневного

    # фон выходных берём из исходного листа
    weekend_bg = None
    for c in sorted(day_cols):
        if _norm(src.cell(weekday_row, c).value) in ('сб', 'вс'):
            weekend_bg = _background_fill(src, c, first_data_row, theme_colors)
            if weekend_bg:
                break

    def tcol(c):
        """Колонка исходного листа -> колонка нового листа (None, если день лишний)."""
        if c < src_first_day:
            return c
        if c <= src_last_day:
            day = c - src_first_day + 1
            return c if day <= days_count else None
        return c + shift

    idx = wb.sheetnames.index(src.title) + 1
    dst = wb.create_sheet(title, idx)

    # переносим значения и оформление
    for row in src.iter_rows():
        for cell in row:
            tc = tcol(cell.column)
            if tc is None:
                continue
            new = dst.cell(cell.row, tc)
            if not isinstance(cell, MergedCell):
                new.value = cell.value
            if cell.has_style:
                new._style = _copy(cell._style)

    # объединённые ячейки
    for m in src.merged_cells.ranges:
        c1 = tcol(m.min_col)
        if c1 is None:
            continue
        c2 = tcol(m.max_col)
        if c2 is None:
            c2 = src_first_day + days_count - 1
        dst.merge_cells(start_row=m.min_row, start_column=c1,
                        end_row=m.max_row, end_column=c2)

    # дополнительные дни месяца (31-е и т.п.): оформление и ширину берём
    # с последнего дня образца, иначе колонка остаётся без рамок
    extra_width = src.column_dimensions[get_column_letter(src_last_day)].width
    for day in range(src_days + 1, days_count + 1):
        tc = src_first_day + day - 1
        if extra_width:
            dst.column_dimensions[get_column_letter(tc)].width = extra_width
        for r in range(1, max_row + 1):
            cell = dst.cell(r, tc)
            if isinstance(cell, MergedCell):
                continue
            sample = src.cell(r, src_last_day)
            if sample.has_style:
                cell._style = _copy(sample._style)

    # ширины колонок и высоты строк
    for letter, dim in src.column_dimensions.items():
        if dim.width is None:
            continue
        try:
            tc = tcol(column_index_from_string(letter))
        except ValueError:
            continue
        if tc is None:
            continue
        dst.column_dimensions[get_column_letter(tc)].width = dim.width
    for r, dim in src.row_dimensions.items():
        if dim.height:
            dst.row_dimensions[r].height = dim.height

    # параметры печати
    dst.page_setup.orientation = src.page_setup.orientation
    dst.page_setup.paperSize = src.page_setup.paperSize
    dst.page_setup.fitToWidth = src.page_setup.fitToWidth
    dst.page_setup.fitToHeight = src.page_setup.fitToHeight
    if src.sheet_properties.pageSetUpPr is not None:
        dst.sheet_properties.pageSetUpPr = _copy(src.sheet_properties.pageSetUpPr)
    dst.print_options.horizontalCentered = src.print_options.horizontalCentered
    dst.page_margins = _copy(src.page_margins)
    dst.freeze_panes = src.freeze_panes
    if src.print_area:
        areas = []
        for area in (src.print_area if isinstance(src.print_area, (list, tuple)) else [src.print_area]):
            text = str(area).split('!')[-1].replace('$', '')
            start, end = text.split(':')
            c1 = column_index_from_string(''.join(ch for ch in start if ch.isalpha()))
            c2 = column_index_from_string(''.join(ch for ch in end if ch.isalpha()))
            r2 = int(''.join(ch for ch in end if ch.isdigit()))
            tc2 = tcol(c2) or (src_first_day + days_count - 1)
            areas.append(f'A1:{get_column_letter(tc2)}{r2}')
        dst.print_area = areas

    # --- дни месяца: номера, буквы, пустые смены, подсветка выходных ---
    for day in range(1, days_count + 1):
        c = src_first_day + day - 1
        letter = _weekday_short(year, month, day)
        head = dst.cell(header_row, c)
        if not isinstance(head, MergedCell):
            head.value = day
        wd_cell = dst.cell(weekday_row, c)
        if not isinstance(wd_cell, MergedCell):
            wd_cell.value = letter

        is_weekend = letter in ('сб', 'вс')
        fill = (PatternFill('solid', fgColor=weekend_bg)
                if (is_weekend and weekend_bg) else PatternFill(fill_type=None))
        for r in range(1, dst.max_row + 1):
            cell = dst.cell(r, c)
            if isinstance(cell, MergedCell):
                continue
            if r >= first_data_row:
                cell.value = None
            if r >= header_row:
                cell.fill = fill

    # примечания и подпись в новом месяце пустые
    cleared_notes = 0
    for c in range(src_last_day + 1, src.max_column + 1):
        tc = tcol(c)
        if tc is None:
            continue
        for r in range(first_data_row, dst.max_row + 1):
            cell = dst.cell(r, tc)
            if isinstance(cell, MergedCell):
                continue
            if cell.value is not None:
                cell.value = None
                cleared_notes += 1

    employees = sum(1 for r in range(first_data_row, dst.max_row + 1)
                    if dst.cell(r, 3).value and str(dst.cell(r, 3).value).strip())

    _ensure_backup()
    try:
        wb.save(SCHEDULE_FILE)
    except PermissionError:
        return {'status': 'error',
                'message': 'Не удалось записать файл графика — возможно, он открыт в Excel'}

    return {
        'status': 'success',
        'message': f'Создан лист «{title}»: дней {days_count}, сотрудников {employees}, '
                   f'смены пустые. Лист «{src.title}» не изменён.',
        'sheet': title,
        'days': days_count,
        'employees': employees,
    }


def _notes_columns(ws, day_cols, kept_cols):
    """Колонки справа от дней месяца: «Х», «Изменения в графике», подпись.

    Берём все колонки правее последнего дня (а не только те, что попали в
    kept_cols): в них тоже бывают данные — например, отметка «Х».
    """
    last_day_col = max(day_cols) if day_cols else 0
    if not last_day_col:
        return []
    return [c for c in range(last_day_col + 1, ws.max_column + 1)]


def clear_schedule_summary(db, year, month):
    """Что именно будет очищено за выбранный месяц (для подтверждения)."""
    year, month = int(year), int(month)
    start = date(year, month, 1)
    end = date(year, month, _days_in_month(year, month))

    plans = db.query(models.Plan).filter(
        models.Plan.date >= start, models.Plan.date <= end).all()
    employees = len({p.employee_id for p in plans})

    notes = 0
    shifts = 0
    sheet = None
    wanted = f'{month:02d}.{year}'
    if os.path.exists(SCHEDULE_FILE):
        wb = load_workbook(SCHEDULE_FILE)
        sheets = [n.strip() for n in wb.sheetnames]
        if wanted in sheets:
            sheet = wanted
            ws = wb[wb.sheetnames[sheets.index(wanted)]]
            header_row, day_cols, kept_cols, max_row = _visible_layout(ws, year, month)
            if header_row is not None and day_cols:
                for r in range(header_row + 2, max_row + 1):
                    name = ws.cell(r, 3).value
                    if not (name and str(name).strip()):
                        continue
                    shifts += sum(1 for c in day_cols if not _is_empty(ws.cell(r, c).value))
                for c in _notes_columns(ws, day_cols, kept_cols):
                    for r in range(header_row + 2, max_row + 1):
                        name = ws.cell(r, 3).value
                        if name and str(name).strip() and not _is_empty(ws.cell(r, c).value):
                            notes += 1

    return {
        'status': 'success',
        'month': wanted,
        'sheet': sheet,
        'plans': len(plans),
        'employees': employees,
        'shifts': shifts,
        'notes': notes,
    }


def clear_schedule_data(db, year, month, clear_plan=True, clear_notes=True, clear_shifts=True):
    """Очистка данных за месяц: смены в листе, план в БД и примечания.

    Смены (ячейки дней) очищаются только в листе самого месяца; оформление,
    сотрудники и выходные остаются на месте.
    """
    year, month = int(year), int(month)
    wanted = f'{month:02d}.{year}'
    plan_deleted = 0
    notes_cleared = 0
    shifts_cleared = 0
    sheet_used = None
    warnings = []

    if clear_plan:
        start = date(year, month, 1)
        end = date(year, month, _days_in_month(year, month))
        plan_deleted = db.query(models.Plan).filter(
            models.Plan.date >= start, models.Plan.date <= end
        ).delete(synchronize_session=False)
        db.commit()

    if (clear_shifts or clear_notes) and os.path.exists(SCHEDULE_FILE):
        wb = load_workbook(SCHEDULE_FILE)
        sheets = [n.strip() for n in wb.sheetnames]
        if wanted in sheets:
            sheet_used = wanted
            ws = wb[wb.sheetnames[sheets.index(wanted)]]
            header_row, day_cols, kept_cols, max_row = _visible_layout(ws, year, month)
            if header_row is not None and day_cols:
                theme_colors = _theme_colors(wb)
                # После очистки остаётся ТОЛЬКО заливка выходных (сб/вс):
                # у всех остальных дней фон убирается полностью.
                base_fill = {}
                weekend_color = None
                for c, day in day_cols.items():
                    is_weekend = (_weekday_short(year, month, day) or '') in ('сб', 'вс')
                    if is_weekend:
                        base_fill[c] = _background_fill(ws, c, header_row + 1, theme_colors)
                        if base_fill[c] and not weekend_color:
                            weekend_color = base_fill[c]
                    else:
                        base_fill[c] = None
                for c, day in day_cols.items():
                    if (base_fill.get(c) is None
                            and (_weekday_short(year, month, day) or '') in ('сб', 'вс')):
                        base_fill[c] = weekend_color or WEEKEND_FILL_FALLBACK

                changed = False
                for r in range(header_row + 2, max_row + 1):
                    name = ws.cell(r, 3).value
                    # Примечания и колонка «Х» чистятся во всех строках месяца
                    # (значения там бывают и без ФИО), а смены — только в строках
                    # сотрудников: в служебных строках смен не бывает.
                    if clear_notes:
                        for c in _notes_columns(ws, day_cols, kept_cols):
                            cell = ws.cell(r, c)
                            if isinstance(cell, MergedCell):
                                continue
                            if not _is_empty(cell.value):
                                cell.value = None
                                notes_cleared += 1
                                changed = True
                    has_name = bool(name and str(name).strip())
                    mark = ws.cell(r, 4).value
                    is_part_time = bool(mark and 'совм' in str(mark).lower())
                    # смены чистим у сотрудников и у их вторых строк «Вн. совм.»
                    if not has_name and not is_part_time:
                        continue
                    if clear_shifts:
                        for c in day_cols:
                            cell = ws.cell(r, c)
                            if isinstance(cell, MergedCell):
                                continue
                            # Фон возвращаем у всех клеток дней: у выходных — прежний,
                            # у рабочих дней — без заливки. Иначе после очистки
                            # остаются цвета смен, в том числе в пустых клетках.
                            base = base_fill.get(c)
                            want = str(base or '').upper()[-6:]
                            color = (_fill_hex(cell, theme_colors) or '').upper()[-6:]
                            if not _is_empty(cell.value):
                                cell.value = None
                                shifts_cleared += 1
                                changed = True
                            if color != want:
                                if base:
                                    cell.fill = PatternFill('solid', fgColor=base)
                                else:
                                    cell.fill = PatternFill(fill_type=None)
                                changed = True
                if changed:
                    _ensure_backup()
                    try:
                        wb.save(SCHEDULE_FILE)
                    except PermissionError:
                        shifts_cleared = 0
                        notes_cleared = 0
                        warnings.append('файл графика открыт в Excel — смены и примечания не очищены')
        else:
            warnings.append(f'в файле графика нет листа за {wanted} — смены и примечания не очищены')

    parts = []
    if clear_shifts:
        parts.append(f'смены в листе «{sheet_used or wanted}»: удалено {shifts_cleared}')
    if clear_plan:
        parts.append(f'план в базе за {wanted}: удалено записей {plan_deleted}')
    if clear_notes:
        parts.append(f'колонка «Изменения в графике»: очищено значений {notes_cleared}')
    if not parts:
        parts.append('нечего очищать')
    message = 'Очистка выполнена — ' + '; '.join(parts) + '.'
    if warnings:
        message += ' Внимание: ' + '; '.join(warnings) + '.'

    return {
        'status': 'success',
        'message': message,
        'month': wanted,
        'plan_deleted': plan_deleted,
        'notes_cleared': notes_cleared,
        'shifts_cleared': shifts_cleared,
        'sheet': sheet_used,
        'warnings': warnings,
    }
