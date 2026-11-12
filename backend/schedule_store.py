"""Хранение листа графика в базе (переделка «правка без Excel»).

Файл xlsx остаётся источником для загрузки и для выгрузки, а содержимое
листа раскладывается по ячейкам — правка графика (добавление сотрудника
в участок, очистка, изменение любой ячейки) не перезаписывает файл.
"""
from openpyxl.cell.cell import MergedCell

import models
import schedule_grid as sg


def _key(name):
    return ' '.join(str(name or '').split()).casefold()


def import_sheet(db, year, month):
    """Переносит значения листа за месяц в таблицу schedule_cells."""
    from openpyxl import load_workbook

    year, month = int(year), int(month)
    if not sg.os.path.exists(sg.SCHEDULE_FILE):
        return {'status': 'error', 'message': 'Файл графика не найден'}

    wb = load_workbook(sg.SCHEDULE_FILE)
    ws = sg._sheet_for(wb, year, month)
    if ws is None:
        return {'status': 'error', 'message': f'В файле нет листа за {month:02d}.{year}'}

    header_row, day_cols, kept_cols, max_row = sg._visible_layout(ws, year, month)
    if header_row is None:
        return {'status': 'error', 'message': 'В листе не найдена строка с днями'}

    db.query(models.ScheduleCell).filter(
        models.ScheduleCell.year == year,
        models.ScheduleCell.month == month,
    ).delete()

    count = 0
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(r, c)
            if isinstance(cell, MergedCell) or cell.value is None:
                continue
            text = str(cell.value)
            if not text.strip():
                continue
            db.add(models.ScheduleCell(year=year, month=month, row=r, col=c, value=text))
            count += 1
    db.commit()
    return {'status': 'success', 'cells': count,
            'max_row': ws.max_row, 'max_col': ws.max_column,
            'header_row': header_row, 'day_cols': len(day_cols), 'kept_cols': len(kept_cols)}


def import_merges(db, year, month):
    """Сохраняет объединённые ячейки листа в таблицу schedule_merges."""
    from openpyxl import load_workbook

    year, month = int(year), int(month)
    wb = load_workbook(sg.SCHEDULE_FILE)
    ws = sg._sheet_for(wb, year, month)
    if ws is None:
        return 0

    db.query(models.ScheduleMerge).filter(
        models.ScheduleMerge.year == year,
        models.ScheduleMerge.month == month,
    ).delete()

    count = 0
    for merged in ws.merged_cells.ranges:
        db.add(models.ScheduleMerge(
            year=year, month=month,
            row1=merged.min_row, col1=merged.min_col,
            row2=merged.max_row, col2=merged.max_col,
        ))
        count += 1
    db.commit()
    return count


def load_merges(db, year, month):
    """Объединения месяца: [(строка1, колонка1, строка2, колонка2), …]."""
    year, month = int(year), int(month)
    rows = db.query(models.ScheduleMerge).filter(
        models.ScheduleMerge.year == year,
        models.ScheduleMerge.month == month,
    ).all()
    return [(m.row1, m.col1, m.row2, m.col2) for m in rows]


def load_cells(db, year, month):
    """Ячейки месяца из базы: {(строка, колонка): значение}."""
    year, month = int(year), int(month)
    rows = db.query(models.ScheduleCell).filter(
        models.ScheduleCell.year == year,
        models.ScheduleCell.month == month,
    ).all()
    return {(cell.row, cell.col): cell.value for cell in rows}


def save_cells(db, year, month, cells):
    """Заменяет все ячейки месяца переданной картой."""
    year, month = int(year), int(month)
    db.query(models.ScheduleCell).filter(
        models.ScheduleCell.year == year,
        models.ScheduleCell.month == month,
    ).delete()
    for (r, c), value in cells.items():
        text = '' if value is None else str(value)
        if not text.strip():
            continue
        db.add(models.ScheduleCell(year=year, month=month, row=int(r), col=int(c), value=text))
    db.commit()


def get_cell(db, year, month, row, col):
    year, month, row, col = int(year), int(month), int(row), int(col)
    return db.query(models.ScheduleCell).filter(
        models.ScheduleCell.year == year,
        models.ScheduleCell.month == month,
        models.ScheduleCell.row == row,
        models.ScheduleCell.col == col,
    ).first()


def set_value(db, year, month, row, col, value):
    """Записывает значение ячейки (пустое значение — удаляет ячейку)."""
    year, month, row, col = int(year), int(month), int(row), int(col)
    text = '' if value is None else str(value)
    cell = get_cell(db, year, month, row, col)
    if not text.strip():
        if cell is not None:
            db.delete(cell)
            db.commit()
        return {'status': 'success', 'value': ''}
    if cell is None:
        db.add(models.ScheduleCell(year=year, month=month, row=row, col=col, value=text))
    else:
        cell.value = text
    db.commit()
    return {'status': 'success', 'value': text}


def _sections(cells, max_row):
    """Участок каждой строки по колонке B (название тянется вниз)."""
    out = {}
    current = ''
    for r in range(1, max_row + 1):
        value = (cells.get((r, 2)) or '').strip()
        if value and value.upper() != 'УЧАСТКИ':
            current = value
        out[r] = current
    return out


def _employee_rows(cells, max_row):
    """Строки сотрудников: (строка, ФИО, должность)."""
    out = []
    for r in range(1, max_row + 1):
        name = (cells.get((r, 3)) or '').strip()
        if not name:
            continue
        position = (cells.get((r, 4)) or '').strip()
        if 'совм' in position.casefold():
            continue
        out.append((r, name, position))
    return out


def add_employee(db, year, month, name, position='', section=''):
    """Добавляет сотрудника в конец его участка (в базе).

    Сдвигаются только номера строк — объединения Excel не участвуют,
    поэтому лист не может «съехать» или потерять названия участков.
    """
    year, month = int(year), int(month)
    name = (name or '').strip()
    if not name:
        return {'status': 'error', 'message': 'Не указано ФИО'}

    cells = load_cells(db, year, month)
    if not cells:
        return {'status': 'error',
                'message': 'График за этот месяц не загружен в базу — сначала загрузите график'}

    max_row = max(r for r, _c in cells)
    sections = _sections(cells, max_row)
    employees = _employee_rows(cells, max_row)
    if not employees:
        return {'status': 'error', 'message': 'В листе нет сотрудников'}

    wanted = _key(section)
    same = [r for r, _n, _p in employees if wanted and _key(sections.get(r, '')) == wanted]
    last = max(same) if same else max(r for r, _n, _p in employees)
    insert_at = last + 2          # сразу после сотрудника и его строки «Вн. совм.»

    shifted = {}
    for (r, c), value in cells.items():
        shifted[(r + 2 if r >= insert_at else r, c)] = value

    shifted[(insert_at, 3)] = name
    if position:
        shifted[(insert_at, 4)] = str(position).strip()
        shifted[(insert_at + 1, 4)] = f'Вн. совм. {str(position).strip()}'

    save_cells(db, year, month, shifted)

    # объединения: сдвигаем вместе со строками, а объединение участка,
    # в который добавили сотрудника, продлеваем на две новые строки
    for merge in db.query(models.ScheduleMerge).filter(
            models.ScheduleMerge.year == year,
            models.ScheduleMerge.month == month).all():
        if merge.row1 >= insert_at:
            merge.row1 += 2
            merge.row2 += 2
        elif merge.row1 <= last <= merge.row2 and merge.row1 < merge.row2:
            merge.row2 += 2
    db.commit()

    return {'status': 'success', 'row': insert_at,
            'message': f'Сотрудник «{name}» добавлен в участок '
                       f'«{section or "—"}» (строка {insert_at})'}
