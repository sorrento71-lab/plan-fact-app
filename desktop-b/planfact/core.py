"""Мост прототипа Б к ядру «План-Факт».

Бизнес-логика не переписывается: приложение вызывает те же функции из
`backend/`, которыми пользуется веб-версия, — но напрямую, в своём процессе,
без HTTP, сокетов и портов.

Откуда что берётся:
    данные и выгрузки план-факта -> backend/planfact_service.py (сервисный слой)
    правка ячеек план-факта      -> backend/planfact_service.py
    сетка графика и действия     -> backend/schedule_grid.py
    табель (xlsx)                -> backend/export_timesheet.py
    загрузка файлов              -> backend/parse_schedule.py, parse_journal.py
    база                         -> backend/database.py (тот же plan_fact.db)

FastAPI здесь не участвует: `app.py` не импортируется вообще.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Модули ядра печатают эмодзи в stdout. На Windows это cp1251, и print() падает
# с UnicodeEncodeError, унося с собой весь вызов. В веб-версии такая настройка
# была в app.py; здесь app.py не участвует, поэтому ставим её сами.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

# --------------------------------------------------------------------------
# backend/ подключаем как корень импортов: модули ядра написаны «плоско»
# (from database import ..., import models), поэтому при запуске из исходников
# их иначе не импортировать.
#
# В собранном exe это не нужно: модули ядра упакованы внутрь программы и
# импортируются напрямую, а рядом с exe лежат только ДАННЫЕ (база, шаблоны,
# книга графика) — их подготавливает frozen.py.
# --------------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    BACKEND_DIR = PROJECT_ROOT / 'backend'
else:
    PROJECT_ROOT = PKG_DIR.parents[1]             # ...\plan-fact-app
    BACKEND_DIR = PROJECT_ROOT / 'backend'
    if not BACKEND_DIR.is_dir():
        raise RuntimeError(
            f"Не найден каталог backend/ рядом с прототипом: {BACKEND_DIR}"
        )
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

import database                                                  # noqa: E402
import models                                                    # noqa: E402
import planfact_service as service                               # noqa: E402
import schedule_grid as grid                                     # noqa: E402
from database import SessionLocal                                # noqa: E402
from export_timesheet import export_timesheet as _build_timesheet  # noqa: E402
from parse_journal import parse_journal_file                     # noqa: E402
from parse_schedule import parse_schedule_file                   # noqa: E402

from . import frozen                                             # noqa: E402

# Пути ядра: при запуске из исходников остаются как есть, в собранном exe
# переводятся на папку рядом с программой (см. frozen.py).
PATHS = frozen.configure(database, grid)

# Таблицы на месте (в app.py это делалось при импорте — теперь делаем явно).
models.Base.metadata.create_all(bind=database.engine)

MONTH_NAMES = service.MONTH_NAMES
WEEKDAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
WEEK_LABELS = ['с 1 по 7', 'с 8 по 14', 'с 15 по 21', 'с 22 по 28', 'с 29 по 31']
WEEK_LABELS_SHORT = ['1–7', '8–14', '15–21', '22–28', '29–31']


class CoreError(RuntimeError):
    """Ошибка, которую нужно показать пользователю как текст."""


@dataclass
class ExportResult:
    """Готовая выгрузка: байты xlsx + имя файла."""
    data: bytes
    filename: str

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_bytes(self.data)
        return path


# --------------------------------------------------------------------------
# Период и недели
# --------------------------------------------------------------------------
def month_period(year: int, month: int) -> tuple[date, date]:
    """Первое и последнее число месяца."""
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return first, last


def days_in_month(year: int, month: int) -> int:
    return month_period(year, month)[1].day


def weeks_of_month(year: int, month: int) -> list[dict]:
    """Недели месяца так же, как их считает веб-версия (29-е по 31-е)."""
    last_day = days_in_month(year, month)
    weeks = []
    for index, (start, end) in enumerate([(1, 7), (8, 14), (15, 21), (22, 28), (29, 31)]):
        if start > last_day:
            continue
        weeks.append({
            'id': index,
            'start': start,
            'end': min(end, last_day),
            'label': WEEK_LABELS[index],
            'label_short': WEEK_LABELS_SHORT[index],
        })
    return weeks


def week_bounds(year: int, month: int, week_id: int) -> tuple[date, date]:
    """Границы недели с поправкой на короткие месяцы."""
    weeks = weeks_of_month(year, month)
    week = next((w for w in weeks if w['id'] == week_id), weeks[0])
    return date(year, month, week['start']), date(year, month, week['end'])


# --------------------------------------------------------------------------
# Чтение данных
# --------------------------------------------------------------------------
def _session():
    return SessionLocal()


def load_plan_fact(year: int, month: int) -> list[dict]:
    db = _session()
    try:
        return service.get_plan_fact(db=db, year=year, month=month)
    finally:
        db.close()


def load_timesheet(year: int, month: int) -> dict:
    first, last = month_period(year, month)
    db = _session()
    try:
        return service.get_timesheet(db=db, date_from=first, date_to=last)
    finally:
        db.close()


def load_schedule(year: int, month: int) -> dict:
    db = _session()
    try:
        result = grid.load_schedule_grid(db=db, year=year, month=month)
    finally:
        db.close()
    if result.get('error'):
        raise CoreError(result['error'])
    return result


def database_stats() -> dict:
    db = _session()
    try:
        return service.get_stats(db)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Правка данных план-факта
# --------------------------------------------------------------------------
def update_time(employee_name: str, day: str | date, field: str, value: str) -> dict:
    """Приход/уход. После сохранения веб-версия перезагружает список."""
    return _write(service.update_time, employee_name=employee_name,
                  date_str=_iso(day), field=field, value=value)


def update_production_stage(employee_name: str, day: str | date, value: str) -> dict:
    return _write(service.update_production_stage, employee_name=employee_name,
                  date_str=_iso(day), value=value)


def update_plan(employee_name: str, day: str | date, value: str) -> dict:
    return _write(service.update_plan, employee_name=employee_name,
                  date_str=_iso(day), value=value)


def delete_employee_from(employee_name: str, date_from: str | date,
                         date_to: str | date) -> dict:
    return _write(service.delete_employee_from, employee_name=employee_name,
                  date_from=_as_date(date_from), date_to=_as_date(date_to))


def _iso(day: str | date) -> str:
    return day if isinstance(day, str) else day.isoformat()


def _as_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _write(func, **kwargs) -> dict:
    """Общая обёртка для операций записи: своя сессия + откат при ошибке."""
    db = _session()
    try:
        return func(db=db, **kwargs)
    except service.ServiceError as exc:
        db.rollback()
        raise CoreError(exc.detail) from exc
    except Exception as exc:                       # noqa: BLE001
        db.rollback()
        raise CoreError(str(exc)) from exc
    finally:
        db.close()


# --------------------------------------------------------------------------
# Вкладка «График»: правки и действия
# --------------------------------------------------------------------------
def save_schedule_cell(row: int, col: int, value: str, year: int, month: int) -> dict:
    return _write(grid.set_schedule_cell, row=row, col=col, value=value,
                  year=year, month=month)


def save_schedule_employee_field(row: int, field: str, value: str,
                                year: int, month: int) -> dict:
    """ФИО / должность / участок сотрудника в графике и в справочнике."""
    return _write(grid.set_schedule_employee_field, row=row, field=field,
                  value=value, year=year, month=month)


def add_schedule_employee(name: str, position: str = '', section: str = '',
                          year: int | None = None, month: int | None = None) -> dict:
    return _write(grid.add_schedule_employee, name=name, position=position,
                  section=section, year=year, month=month)


def delete_schedule_employee(row: int, year: int, month: int) -> dict:
    return _write(grid.delete_schedule_employee, row=row, year=year, month=month)


def clear_schedule(year: int, month: int, *, clear_plan: bool = True,
                   clear_notes: bool = True, clear_shifts: bool = True) -> dict:
    return _write(grid.clear_schedule_data, year=year, month=month,
                  clear_plan=clear_plan, clear_notes=clear_notes,
                  clear_shifts=clear_shifts)


def schedule_clear_summary(year: int, month: int) -> dict:
    db = _session()
    try:
        return grid.clear_schedule_summary(db, year, month)
    finally:
        db.close()


def schedule_shifts_summary(year: int, month: int) -> dict:
    return grid.shift_fill_summary(year, month)


def fill_schedule_shifts(year: int, month: int) -> dict:
    """«Расставить смены»: 11/9/8 по ритму."""
    return _write(grid.fill_schedule_shifts, year=year, month=month)


def create_schedule_sheet(year: int, month: int) -> dict:
    """«Создать лист за MM.YYYY»."""
    return grid.create_month_sheet(year, month)


# --------------------------------------------------------------------------
# Загрузка исходных файлов
# --------------------------------------------------------------------------
def import_journal(path: str | Path) -> dict:
    path = Path(path)
    db = _session()
    try:
        result = parse_journal_file(str(path), db)
    finally:
        db.close()
    if result.get('status') == 'error':
        raise CoreError(str(result.get('message') or result))
    return result


def import_schedule(path: str | Path) -> dict:
    path = Path(path)
    db = _session()
    try:
        result = parse_schedule_file(str(path), db)
        if result.get('status') == 'error':
            raise CoreError(str(result.get('message') or result))

        # данные графика сразу переносятся в лист файла — как в веб-версии
        synced: dict = {}
        sheet = str(result.get('sheet_processed') or '')
        parsed = re.match(r'^\s*(\d{1,2})[.\-/](\d{4})', sheet)
        if parsed:
            sync_month, sync_year = int(parsed.group(1)), int(parsed.group(2))
            synced = grid.apply_plan_to_schedule(db, sync_year, sync_month)
    finally:
        db.close()

    return {
        'employees': result.get('employees', 0),
        'records': result.get('records', 0),
        'schedule': synced,
    }


# --------------------------------------------------------------------------
# Выгрузки
# --------------------------------------------------------------------------
def _to_bytes(stream: Any) -> bytes:
    """Байты из BytesIO или из потока сервиса."""
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream)
    if hasattr(stream, 'read'):
        data = stream.read()
        return data if isinstance(data, bytes) else bytes(data)
    return b''.join(stream)


def export_timesheet(year: int, month: int, sort_field: str | None = None,
                     sort_direction: str = 'asc') -> ExportResult:
    """Табель Т-13 по шаблону backend/табель.xlsx."""
    first, last = month_period(year, month)
    db = _session()
    try:
        stream = _build_timesheet(db, first, last,
                                  template_path=PATHS.get('template'),
                                  sort_field=sort_field,
                                  sort_direction=sort_direction)
        data = _to_bytes(stream)
    finally:
        db.close()
    return ExportResult(data, f"Табель_{MONTH_NAMES[month - 1]}_{year}.xlsx")


def export_schedule(year: int, month: int, mode: str = 'actual') -> ExportResult:
    stream, filename = grid.export_schedule_xlsx(year, month, mode)
    if stream is None:
        raise CoreError(str(filename))
    return ExportResult(_to_bytes(stream), str(filename))


def export_week(year: int, month: int, week_id: int) -> ExportResult:
    report = _report(service.build_week_report, year=year, month=month, week_id=week_id)
    return ExportResult(_to_bytes(report.stream), report.filename)


def export_month(year: int, month: int) -> ExportResult:
    report = _report(service.build_month_report, year=year, month=month)
    return ExportResult(_to_bytes(report.stream), report.filename)


def export_meal(day: date, meal_type: str) -> ExportResult:
    report = _report(service.build_meal_report, target_date=day, meal_type=meal_type)
    return ExportResult(_to_bytes(report.stream), report.filename)


def _report(func, **kwargs):
    db = _session()
    try:
        result = func(db=db, **kwargs)
    finally:
        db.close()
    if isinstance(result, service.ReportWarning):
        raise CoreError(result.message)
    return result


def meal_preview(day: date) -> list[str]:
    """Кого ядро положит в выгрузку питания.

    Правила отбора живут в сервисе (одна реализация и для файла, и для экрана).
    """
    db = _session()
    try:
        employees = service.collect_meal_employees(db, day)
    finally:
        db.close()
    return [employee['name'] for employee in employees]


__all__ = [
    'CoreError', 'ExportResult', 'PROJECT_ROOT', 'BACKEND_DIR', 'MONTH_NAMES',
    'WEEKDAY_SHORT', 'WEEK_LABELS', 'WEEK_LABELS_SHORT',
    'month_period', 'days_in_month', 'weeks_of_month', 'week_bounds',
    'load_plan_fact', 'load_timesheet', 'load_schedule', 'database_stats',
    'update_time', 'update_production_stage', 'update_plan', 'delete_employee_from',
    'save_schedule_cell', 'save_schedule_employee_field', 'add_schedule_employee',
    'delete_schedule_employee', 'clear_schedule', 'schedule_clear_summary',
    'schedule_shifts_summary', 'fill_schedule_shifts', 'create_schedule_sheet',
    'import_journal', 'import_schedule',
    'export_timesheet', 'export_schedule', 'export_week', 'export_month',
    'export_meal', 'meal_preview',
]
