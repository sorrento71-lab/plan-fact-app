from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime, timedelta
import os
import sys
import tempfile
import io
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils.dataframe import dataframe_to_rows
import urllib.parse
import socket
import re

# На Windows stdout/stderr по умолчанию cp1251: эмодзи в print() (📊, ❌ и т.п.)
# вызывают UnicodeEncodeError и роняют эндпоинты. Переключаемся на UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

from database import SessionLocal, engine
import models
from parse_schedule import parse_schedule_file
from parse_journal import parse_journal_file
from export_timesheet import export_timesheet
import planfact_service as service
from schedule_grid import (load_schedule_grid, set_schedule_cell, add_schedule_employee,
                           import_schedule_to_plan, clear_schedule_summary,
                           clear_schedule_data, create_month_sheet,
                           set_schedule_employee_field, shift_fill_summary,
                           fill_schedule_shifts, export_schedule_xlsx,
                           sync_schedule_from_plan, clear_schedule_days_for_employee,
                           plan_to_schedule_summary, apply_plan_to_schedule,
                           delete_schedule_employee)
from medcheck_export import build_medcheck_docx, medcheck_summary

# Создаём таблицы в БД
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="План-Факт API")

# ============================================================
# CORS - расширенные настройки для удаленного доступа
# ============================================================
app.add_middleware(
    CORSMiddleware,
    # Без "*": с allow_credentials=True браузеры всё равно отклоняют
    # запросы с wildcard-источником, поэтому указываем явный список.
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://30.77.123.68:3000",
        "http://30.77.123.68:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# КОРЕНЬ
# ============================================================
@app.get("/")
def root():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    return {
        "message": "Сервер работает!",
        "server": {
            "hostname": hostname,
            "local_ip": local_ip,
            "port": 8000
        },
        "endpoints": {
            "/employees": "Список сотрудников",
            "/plans": "Список планов",
            "/facts": "Список фактов",
            "/plan-fact/": "План-факт с фильтрами",
            "/timesheet/": "Табель учета рабочего времени (Т-13)",
            "/upload/schedule/": "Загрузка графика (POST)",
            "/upload/journal/": "Загрузка журнала (POST)",
            "/clear-week/": "Очистка недели (POST)",
            "/update-time/": "Обновление прихода/ухода (POST)",
            "/update-production-stage/": "Обновление этапов производства (POST)",
            "/export/weekly/": "Выгрузка недели (GET)",
            "/export/monthly/": "Выгрузка месяца (GET)",
            "/export/current-week/": "Выгрузка текущей недели (GET)",
            "/export/timesheet/": "Выгрузка табеля Т-13 (GET)",
            "/export/meal/": "Выгрузка питания (POST)",
            "/stats": "Статистика"
        }
    }


# ============================================================
# СОТРУДНИКИ
# ============================================================
@app.get("/employees")
def get_employees(
        db: Session = Depends(get_db),
        department: Optional[str] = None
):
    query = db.query(models.Employee)
    if department:
        query = query.filter(models.Employee.department == department)
    return query.order_by(models.Employee.order, models.Employee.id).all()


@app.get("/employees/{employee_id}")
def get_employee(employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return employee


# ============================================================
# ПЛАНЫ
# ============================================================
@app.get("/plans")
def get_plans(
        employee_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        db: Session = Depends(get_db)
):
    query = db.query(models.Plan)
    if employee_id:
        query = query.filter(models.Plan.employee_id == employee_id)
    if start_date:
        query = query.filter(models.Plan.date >= start_date)
    if end_date:
        query = query.filter(models.Plan.date <= end_date)
    return query.all()


# ============================================================
# ФАКТЫ
# ============================================================
@app.get("/facts")
def get_facts(
        employee_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        db: Session = Depends(get_db)
):
    if not hasattr(models, 'Fact'):
        return []
    query = db.query(models.Fact)
    if employee_id:
        query = query.filter(models.Fact.employee_id == employee_id)
    if start_date:
        query = query.filter(models.Fact.date >= start_date)
    if end_date:
        query = query.filter(models.Fact.date <= end_date)
    return query.all()


# ============================================================
# ПЛАН-ФАКТ (СВОДКА) - ОБНОВЛЕН С ПОДДЕРЖКОЙ МЕСЯЦЕВ
# ============================================================
@app.get("/plan-fact/")
def get_plan_fact(
        db: Session = Depends(get_db),
        employee: Optional[str] = None,
        department: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        year: Optional[int] = None,
        month: Optional[int] = None
):
    return service.get_plan_fact(
        db=db,
        employee=employee,
        department=department,
        date_from=date_from,
        date_to=date_to,
        year=year,
        month=month
    )


# ============================================================
# ТАБЕЛЬ УЧЕТА РАБОЧЕГО ВРЕМЕНИ (ФОРМА Т-13)
# ============================================================
@app.get("/timesheet/")
def get_timesheet(
        db: Session = Depends(get_db),
        employee_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
):
    return service.get_timesheet(
        db=db,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to
    )


# ============================================================
# ГРАФИК (ФОРМА А3): структура, цвета и сравнение с планом БД
# ============================================================
@app.get("/schedule/grid/")
def get_schedule_grid(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Таблица графика с исходными цветами и сравнением с планом из БД."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month

    result = load_schedule_grid(db=db, year=year, month=month)
    if result.get('error'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


class ScheduleCellRequest(BaseModel):
    row: int
    col: int
    value: str
    year: Optional[int] = None
    month: Optional[int] = None


@app.post("/schedule/cell/")
def save_schedule_cell(request: ScheduleCellRequest, db: Session = Depends(get_db)):
    """Сохраняет ячейку графика: в файл и (для дней) в план БД."""
    result = set_schedule_cell(request.row, request.col, request.value, db=db,
                               year=request.year, month=request.month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


class ScheduleEmployeeRequest(BaseModel):
    name: str
    position: Optional[str] = ''
    section: Optional[str] = ''
    year: Optional[int] = None
    month: Optional[int] = None


@app.post("/schedule/employee/")
def add_employee_to_schedule(request: ScheduleEmployeeRequest, db: Session = Depends(get_db)):
    """Добавляет сотрудника в график и в справочник БД."""
    result = add_schedule_employee(request.name, request.position or '', request.section or '',
                                   db=db, year=request.year, month=request.month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


class ScheduleEmployeeUpdateRequest(BaseModel):
    row: int
    field: str          # name | position | section
    value: str
    year: Optional[int] = None
    month: Optional[int] = None


@app.post("/schedule/employee/update/")
def update_schedule_employee(request: ScheduleEmployeeUpdateRequest,
                             db: Session = Depends(get_db)):
    """Меняет ФИО, должность или участок сотрудника в графике и в базе."""
    result = set_schedule_employee_field(request.row, request.field, request.value,
                                         db=db, year=request.year, month=request.month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.post("/schedule/to-plan/")
def schedule_to_plan(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Загружает план из файла графика за выбранный месяц (кнопка в План-Факте)."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month

    result = import_schedule_to_plan(db, year, month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.get("/schedule/clear/summary/")
def schedule_clear_summary(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Сколько данных будет очищено за месяц (для уточняющего вопроса)."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    return clear_schedule_summary(db, year, month)


@app.get("/export/medcheck/")
def export_medcheck(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None
):
    """График прохождения медосмотров (Приложение Б) по сменам месяца из графика.

    До ноября 2026 это смены 11, 9, 8, с ноября 2026 — «Я» (основная) и «В» (доп смена).

    Без day — за весь месяц, с day — только на этот день.
    """
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month

    stream, filename = build_medcheck_docx(db, year, month, day)
    if stream is None:
        raise HTTPException(status_code=400, detail=filename)
    encoded = urllib.parse.quote(filename)
    return StreamingResponse(
        stream,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@app.get("/medcheck/summary/")
def medcheck_info(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None
):
    """Кто попадёт в список медосмотра: за месяц или за конкретный день."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    result = medcheck_summary(db, year, month, day, with_days=day is None)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.get("/export/schedule/")
def export_schedule(
        year: Optional[int] = None,
        month: Optional[int] = None,
        mode: str = 'actual'
):
    """Выгрузка графика (форма А3): mode=actual — как есть, mode=rhythm — только смены месяца по ритму."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    if mode not in ('actual', 'rhythm'):
        raise HTTPException(status_code=400, detail='mode должен быть actual или rhythm')

    stream, filename = export_schedule_xlsx(year, month, mode)
    if stream is None:
        raise HTTPException(status_code=400, detail=filename)
    encoded = urllib.parse.quote(filename)
    return StreamingResponse(
        stream,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


class ScheduleEmployeeDeleteRequest(BaseModel):
    row: int
    year: Optional[int] = None
    month: Optional[int] = None


@app.post("/schedule/employee/delete/")
def delete_employee_from_schedule(request: ScheduleEmployeeDeleteRequest,
                                  db: Session = Depends(get_db)):
    """Удаляет строку сотрудника из листа графика (план и факты в базе остаются)."""
    result = delete_schedule_employee(request.row, db=db,
                                      year=request.year, month=request.month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.get("/schedule/from-plan/summary/")
def schedule_from_plan_summary(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Сводка: сколько дней графика изменится при переносе плана из базы."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    return plan_to_schedule_summary(db, year, month)


@app.post("/schedule/from-plan/")
def schedule_from_plan(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Переносит план из базы в лист графика за месяц (правки План-Факта → график)."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    result = apply_plan_to_schedule(db, year, month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.get("/schedule/shifts/summary/")
def schedule_shifts_summary(
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Сводка по расстановке смен (для уточняющего вопроса)."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    return shift_fill_summary(year, month)


@app.post("/schedule/shifts/fill/")
def schedule_shifts_fill(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Расставляет смены в графике за месяц по ритму (11 — 2/2, 8 и 9 — 5/2)."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    result = fill_schedule_shifts(db=db, year=year, month=month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.post("/schedule/create-sheet/")
def schedule_create_sheet(
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Создаёт в файле графика лист за выбранный месяц — пустую форму."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month

    result = create_month_sheet(year, month)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


@app.post("/schedule/clear/")
def schedule_clear(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None,
        clear_plan: bool = True,
        clear_notes: bool = True,
        clear_shifts: bool = True
):
    """Очищает смены в листе месяца, план за месяц в БД и примечания."""
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month

    result = clear_schedule_data(db, year, month, clear_plan=clear_plan,
                                 clear_notes=clear_notes, clear_shifts=clear_shifts)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result['message'])
    return result


# ============================================================
# ВЫГРУЗКА ТАБЕЛЯ В EXCEL (ФОРМА Т-13)
# ============================================================
@app.get("/export/timesheet/")
def export_timesheet_excel(
        db: Session = Depends(get_db),
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        sort_field: Optional[str] = None,
        sort_direction: Optional[str] = 'asc'
):
    """
    Выгружает табель учета рабочего времени (форма Т-13) в формате XLSX.
    sort_field / sort_direction — порядок сотрудников, как на экране
    (employee_name, tab_number).
    """
    try:
        if not date_from:
            today = date.today()
            date_from = date(today.year, today.month, 1)
        if not date_to:
            if date_from.month == 12:
                date_to = date(date_from.year + 1, 1, 1) - timedelta(days=1)
            else:
                date_to = date(date_from.year, date_from.month + 1, 1) - timedelta(days=1)

        print(f"📊 Выгрузка табеля в XLSX за {date_from} - {date_to}, "
              f"сортировка: {sort_field} {sort_direction}")

        excel_file = export_timesheet(
            db, date_from, date_to,
            sort_field=sort_field,
            sort_direction=sort_direction
        )

        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                       'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

        filename = f"Табель_{month_names[date_from.month - 1]}_{date_from.year}.xlsx"
        encoded_filename = urllib.parse.quote(filename)

        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )

    except Exception as e:
        print(f"❌ Ошибка выгрузки табеля: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ОБНОВЛЕНИЕ ВРЕМЕНИ (ПРИХОД/УХОД)
# ============================================================
from pydantic import BaseModel


class TimeUpdateRequest(BaseModel):
    employee_name: str
    date: str
    field: str
    value: str


@app.post("/update-time/")
def update_time(request: TimeUpdateRequest, db: Session = Depends(get_db)):
    try:
        return service.update_time(
            db=db,
            employee_name=request.employee_name,
            date_str=request.date,
            field=request.field,
            value=request.value
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ОБНОВЛЕНИЕ ЭТАПОВ ПРОИЗВОДСТВА
# ============================================================
class ProductionStageUpdateRequest(BaseModel):
    employee_name: str
    date: str
    value: str


@app.post("/update-production-stage/")
def update_production_stage(request: ProductionStageUpdateRequest, db: Session = Depends(get_db)):
    try:
        return service.update_production_stage(
            db=db,
            employee_name=request.employee_name,
            date_str=request.date,
            value=request.value
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ОБНОВЛЕНИЕ ПЛАНА (график)
# ============================================================
class PlanUpdateRequest(BaseModel):
    employee_name: str
    date: str
    value: str


@app.post("/update-plan/")
def update_plan(request: PlanUpdateRequest, db: Session = Depends(get_db)):
    try:
        return service.update_plan(
            db=db,
            employee_name=request.employee_name,
            date_str=request.date,
            value=request.value
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ВЫГРУЗКА ПИТАНИЯ (КАФЕ) - ПОЛНАЯ СИНХРОНИЗАЦИЯ С ФРОНТЕНДОМ
# ============================================================
class ExportMealRequest(BaseModel):
    date: str  # "2026-08-19"
    meal_type: str  # "morning" или "lunch"


@app.post("/export/meal/")
def export_meal(
        request: ExportMealRequest,
        db: Session = Depends(get_db)
):
    """
    Выгружает список сотрудников для питания на указанную дату
    meal_type: "morning" - 165 руб, "lunch" - 460 руб
    """
    try:
        target_date = datetime.strptime(request.date, "%Y-%m-%d").date()
        report = service.build_meal_report(db=db, target_date=target_date,
                                           meal_type=request.meal_type)

        if isinstance(report, service.ReportWarning):
            return {
                "status": "warning",
                "message": report.message,
                "count": report.count
            }

        return StreamingResponse(
            report.stream,
            media_type=service.XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": report.content_disposition}
        )

    except Exception as e:
        print(f"❌ Ошибка выгрузки питания: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ВЫГРУЗКА В EXCEL (ПЛАН-ФАКТ)
# ============================================================
def create_excel_report(data: list, title: str = "План-Факт") -> io.BytesIO:
    if not data:
        wb = Workbook()
        ws = wb.active
        ws.title = "План-Факт"
        ws['A1'] = "Нет данных для выгрузки"
        ws['A1'].font = Font(size=14, bold=True)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    df = pd.DataFrame(data)

    if 'employee_name' in df.columns and 'date' in df.columns:
        df = df.sort_values(['employee_name', 'date'])

    column_names = {
        'employee_name': 'Сотрудник',
        'department': 'Участок',
        'position': 'Должность',
        'date': 'Дата',
        'plan_type': 'План',
        'plan_hours': 'План (часы)',
        'start_time': 'Приход',
        'end_time': 'Уход',
        'fact_hours': 'Факт (часы)',
        'production_stage': 'Этапы производства',
        'status': 'Статус',
        'day_of_week': 'День недели'
    }

    for old_name, new_name in column_names.items():
        if old_name in df.columns:
            df = df.rename(columns={old_name: new_name})

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='План-Факт', index=False)

        workbook = writer.book
        worksheet = writer.sheets['План-Факт']

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1565C0", end_color="1565C0", fill_type="solid")
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        for cell in worksheet[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value:
                        length = len(str(cell.value))
                        if length > max_length:
                            max_length = length
                except:
                    pass
            adjusted_width = min(max_length + 2, 30)
            worksheet.column_dimensions[column_letter].width = adjusted_width

        worksheet.auto_filter.ref = worksheet.dimensions

    output.seek(0)
    return output


@app.get("/export/weekly/")
def export_weekly(
        week_id: int,
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Выгружает данные за указанную неделю в Excel"""
    try:
        report = service.build_week_report(db=db, week_id=week_id, year=year, month=month)
        return StreamingResponse(
            report.stream,
            media_type=service.XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": report.content_disposition}
        )

    except Exception as e:
        print(f"❌ Ошибка выгрузки: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export/monthly/")
def export_monthly(
        db: Session = Depends(get_db),
        year: Optional[int] = None,
        month: Optional[int] = None
):
    """Выгружает данные за указанный месяц в Excel"""
    try:
        report = service.build_month_report(db=db, year=year, month=month)
        return StreamingResponse(
            report.stream,
            media_type=service.XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": report.content_disposition}
        )

    except Exception as e:
        print(f"❌ Ошибка выгрузки: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export/current-week/")
def export_current_week(
        db: Session = Depends(get_db)
):
    """Выгружает данные за текущую неделю"""
    try:
        today = date.today()
        day = today.day

        if day <= 7:
            week_id = 0
            start_day, end_day = 1, 7
            label = '1-7'
        elif day <= 14:
            week_id = 1
            start_day, end_day = 8, 14
            label = '8-14'
        elif day <= 21:
            week_id = 2
            start_day, end_day = 15, 21
            label = '15-21'
        elif day <= 28:
            week_id = 3
            start_day, end_day = 22, 28
            label = '22-28'
        else:
            week_id = 4
            start_day, end_day = 29, 31
            label = '29-31'

        date_from = date(today.year, today.month, start_day)
        date_to = date(today.year, today.month, end_day)

        print(f"📊 Выгрузка текущей недели {label} за {today.month}.{today.year}")

        data = service.get_plan_fact(
            db=db,
            date_from=date_from,
            date_to=date_to
        )

        if not data or len(data) == 0:
            wb = Workbook()
            ws = wb.active
            ws.title = "План-Факт"
            ws['A1'] = f"Нет данных за текущую неделю ({label})"
            ws['A1'].font = Font(size=14, bold=True)

            output = io.BytesIO()
            wb.save(output)
            output.seek(0)

            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=Plan_Fact_current_week_empty.xlsx"}
            )

        excel_file = create_excel_report(data, f"План-Факт текущая неделя ({label})")

        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Plan_Fact_current_week.xlsx"}
        )

    except Exception as e:
        print(f"❌ Ошибка выгрузки: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ЗАГРУЗКА ГРАФИКА
# ============================================================
@app.post("/upload/schedule/")
async def upload_schedule(
        file: UploadFile = File(...),
        year: Optional[int] = None,
        month: Optional[int] = None,
        db: Session = Depends(get_db)
):
    print(f"📁 Получен файл: {file.filename}")
    print(f"📦 Content-Type: {file.content_type}")
    print(f"📅 Запрошен лист за: {year}-{month}")

    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате Excel")

    contents = await file.read()
    print(f"📦 Размер файла: {len(contents)} байт")

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Файл пуст")

    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
        print(f"💾 Временный файл: {tmp_path}")

    try:
        result = parse_schedule_file(tmp_path, db, year=year, month=month)
        print(f"✅ Результат парсинга: {result}")
        if result.get('status') == 'error':
            # Это ошибка входных данных пользователя, а не сервера
            raise HTTPException(status_code=400, detail=result['message'])

        # данные графика сразу переносим в лист файла — чтобы вкладка «График»
        # показывала то же, что попало в план (без отдельных кнопок)
        synced = {}
        sheet = str(result.get('sheet_processed') or '')
        # месяц ищем в любом месте имени листа: «10.2026», «10.2026 », «График 10.2026»
        parsed = re.search(r'(\d{1,2})\s*[.\-/]\s*(\d{4})', sheet)
        if parsed and 1 <= int(parsed.group(1)) <= 12:
            sync_month, sync_year = int(parsed.group(1)), int(parsed.group(2))
            synced = apply_plan_to_schedule(db, sync_year, sync_month)
            print(f"🔁 Синхронизация листа {sync_year}-{sync_month:02d}: {synced.get('message')}")
        elif sheet:
            print(f"🔁 Лист «{sheet}»: месяц не распознан, перенос в лист пропущен")

        return {
            "status": "success",
            "message": f"Загружено из листа «{sheet.strip()}»: "
                       f"{result.get('employees_found', result.get('employees', 0))} сотрудников, "
                       f"{result.get('records', 0)} записей плана"
                       + (f". {synced['message']}" if synced.get('status') == 'success' else
                          (f". Лист графика не обновлён: {synced.get('message')}" if synced.get('message') else "")),
            "employees": result.get('employees', 0),
            "records": result.get('records', 0),
            "schedule": synced
        }
    except HTTPException:
        raise  # свои ошибки (например, 400 при неверном файле) не оборачиваем
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ Ошибка: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Ошибка при парсинге: {str(e)}")
    finally:
        import time
        time.sleep(0.5)
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                print("🗑️ Временный файл удалён")
        except Exception as e:
            print(f"⚠️ Не удалось удалить временный файл: {e}")


# ============================================================
# ЗАГРУЗКА ЖУРНАЛА
# ============================================================
@app.post("/upload/journal/")
async def upload_journal(
        file: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    print(f"📁 Получен файл журнала: {file.filename}")
    print(f"📦 Content-Type: {file.content_type}")

    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате Excel")

    contents = await file.read()
    print(f"📦 Размер файла: {len(contents)} байт")

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Файл пуст")

    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
        print(f"💾 Временный файл: {tmp_path}")

    try:
        result = parse_journal_file(tmp_path, db)
        print(f"✅ Результат парсинга: {result}")
        if result.get('status') == 'error':
            # Это ошибка входных данных пользователя, а не сервера
            raise HTTPException(status_code=400, detail=result['message'])
        return {
            "status": "success",
            "message": f"Добавлено: {result.get('added', 0)}, обновлено: {result.get('updated', 0)}",
            **result
        }
    except HTTPException:
        raise  # свои ошибки (например, 400 при неверном файле) не оборачиваем
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ Ошибка: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Ошибка при парсинге: {str(e)}")
    finally:
        import time
        time.sleep(0.5)
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                print("🗑️ Временный файл удалён")
        except Exception as e:
            print(f"⚠️ Не удалось удалить временный файл: {e}")


# ============================================================
# ИНИЦИАЛИЗАЦИЯ ТЕСТОВЫХ ДАННЫХ
# ============================================================
@app.post("/init-data")
def init_data(db: Session = Depends(get_db)):
    if db.query(models.Employee).count() > 0:
        return {"message": "Данные уже есть", "count": db.query(models.Employee).count()}

    employees = [
        models.Employee(name="Иванов Иван", position="Сварщик", department="", order=1),
        models.Employee(name="Петров Петр", position="Слесарь", department="", order=2),
    ]
    for emp in employees:
        db.add(emp)
    db.commit()
    return {"message": f"Добавлено {len(employees)} сотрудников"}


# ============================================================
# СТАТИСТИКА
# ============================================================
@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    return service.get_stats(db)


# ============================================================
# ЗДОРОВЬЕ
# ============================================================
@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ============================================================
# ОЧИСТКА НЕДЕЛИ
# ============================================================
class WeekClearRequest(BaseModel):
    week_id: int
    start_day: int
    end_day: int
    year: Optional[int] = None    # по умолчанию — текущий год
    month: Optional[int] = None   # по умолчанию — текущий месяц


@app.post("/clear-week/")
def clear_week(request: WeekClearRequest, db: Session = Depends(get_db)):
    """Очищает данные только за указанную неделю"""
    try:
        import calendar

        today = date.today()
        year = request.year or today.year
        month = request.month or today.month

        # Обрезаем конец недели по длине месяца (например, 31 сентября не бывает)
        last_day = calendar.monthrange(year, month)[1]
        end_day = min(request.end_day, last_day)

        start_date = date(year, month, request.start_day)
        end_date = date(year, month, end_day)

        deleted_plans = db.query(models.Plan).filter(
            models.Plan.date >= start_date,
            models.Plan.date <= end_date
        ).delete()

        deleted_facts = db.query(models.Fact).filter(
            models.Fact.date >= start_date,
            models.Fact.date <= end_date
        ).delete() if hasattr(models, 'Fact') else 0

        db.commit()

        return {
            "status": "success",
            "message": f"Очищена неделя {request.week_id + 1} ({start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}): {deleted_plans} планов, {deleted_facts} фактов"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при очистке: {str(e)}")


# ============================================================
# УДАЛЕНИЕ ДАННЫХ СОТРУДНИКА С ОПРЕДЕЛЕННОЙ НЕДЕЛИ
# ============================================================
class DeleteEmployeeFromRequest(BaseModel):
    employee_name: str
    date_from: date
    date_to: date


@app.post("/delete-employee-from/")
def delete_employee_from(request: DeleteEmployeeFromRequest, db: Session = Depends(get_db)):
    """Удаляет планы и факты сотрудника за период (обычно — с начала текущей недели до конца месяца).

    Сам сотрудник из справочника не удаляется — убираются только его данные
    (план и факт) в указанном диапазоне дат.
    """
    try:
        return service.delete_employee_from(
            db=db,
            employee_name=request.employee_name,
            date_from=request.date_from,
            date_to=request.date_to
        )
    except service.ServiceError as exc:
        # здесь общего except нет, поэтому код ответа сохраняем как есть
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
