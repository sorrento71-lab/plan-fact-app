"""Хранение листа графика в базе (шаг 1 переделки).

Файл xlsx остаётся источником для загрузки и для выгрузки, а здесь
содержимое листа раскладывается по ячейкам — чтобы правка графика
(добавление сотрудника в участок, очистка, изменение любой ячейки)
не перезаписывала файл.
"""
from openpyxl.cell.cell import MergedCell

import models
import schedule_grid as sg


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


def load_cells(db, year, month):
    """Ячейки месяца из базы: {(строка, колонка): значение}."""
    year, month = int(year), int(month)
    rows = db.query(models.ScheduleCell).filter(
        models.ScheduleCell.year == year,
        models.ScheduleCell.month == month,
    ).all()
    return {(cell.row, cell.col): cell.value for cell in rows}


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
