"""Проверка «Питания» и «Медосмотра» на кодах «Я»/«В» (ноябрь 2026) и старых кодах.

Работает на КОПИИ файла графика и на временной базе — рабочие данные не меняются.
В конце проверяются сами эндпоинты на реальных данных (только чтение).

Проверяется:
- питание: кто попадает в список (план «Я»/«В», факт; отпуск «О» исключается),
  и что выгрузка XLSX содержит тех же людей;
- медосмотр: смены «Я» и «В» попадают в список, отпуск/больничный — нет,
  служебные строки («вакансия») — нет, счётчики по сменам и дням, выгрузка DOCX;
- старые месяцы (октябрь) по-прежнему считают 11/9/8.
"""
import os
import shutil
import sys
from datetime import date
from io import BytesIO

sys.path.insert(0, r'C:\plan-fact-app\backend')

from docx import Document
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import medcheck_export as me
import models
import planfact_service as pf
import schedule_grid as sg

TMP = r'C:\plan-fact-app\.tmp\export-test'
os.makedirs(TMP, exist_ok=True)
TEST_XLSX = os.path.join(TMP, 'schedule.xlsx')
REAL_XLSX = sg.SCHEDULE_FILE

ok = []
fail = []


def check(name, condition, detail=''):
    (ok if condition else fail).append(name)
    print(f'  [{"OK" if condition else "ОШИБКА"}] {name}' + (f' — {detail}' if detail else ''))


# ---------------------------------------------------------------- тестовая база
engine = create_engine('sqlite:///:memory:')
models.Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
order = 0


def add_employee(name, position='Оператор'):
    global order
    order += 1
    emp = models.Employee(name=name, position=position, department='Участок', order=order)
    db.add(emp)
    return emp


fact_only = add_employee('Фактов Факт')
plan_ya = add_employee('Явкин Яков')
plan_ve = add_employee('Второй Виктор')
plan_otpusk = add_employee('Отпускной Олег')
plan_bolnichny = add_employee('Больничный Борис')
plan_empty = add_employee('Пустой Пётр')
# «б/с» в базе встречается в разном регистре — оба варианта не должны попадать
plan_bs = add_employee('БезСодержания Борис')
plan_bs_upper = add_employee('БезСодержанияВерх Влад')
plan_bs_short = add_employee('БезСодержанияКоротко Ким')
# подмены имён больше нет: Жажин должен выводиться как Жажин
plan_zhazhin = add_employee('Жажин Максим')
db.commit()

NOV = date(2026, 11, 5)
add_plan = lambda emp, day, value: db.add(models.Plan(employee_id=emp.id, date=day, plan_type=value))
add_plan(plan_ya, NOV, 'Я')
add_plan(plan_ve, NOV, 'В')
add_plan(plan_otpusk, NOV, 'О')
add_plan(plan_bolnichny, NOV, 'Б')
add_plan(plan_bs, NOV, 'б/с')
add_plan(plan_bs_upper, NOV, 'Б/С')
add_plan(plan_bs_short, NOV, 'БС')
add_plan(plan_zhazhin, NOV, 'Я')
db.add(models.Fact(employee_id=fact_only.id, date=NOV, fact_hours=11.0,
                   start_time='08:00', end_time='19:00'))
db.commit()

OCT = date(2026, 10, 5)
legacy_11 = add_employee('Старый Одиннадцать')
legacy_d = add_employee('Старый Доп')
db.commit()
add_plan(legacy_11, OCT, '11')
add_plan(legacy_d, OCT, 'Д')
db.commit()

print('=== ПИТАНИЕ: отбор людей (ноябрь, коды «Я»/«В») ===')
nov_names = [e['name'] for e in pf.collect_meal_employees(db, NOV)]
print('  список:', nov_names)
check('план «Я» попадает в питание', 'Явкин Яков' in nov_names)
check('план «В» (доп смена) попадает в питание', 'Второй Виктор' in nov_names)
check('факт без плана попадает в питание', 'Фактов Факт' in nov_names)
check('отпуск «О» исключён', 'Отпускной Олег' not in nov_names)
check('сотрудник без плана и факта не попадает', 'Пустой Пётр' not in nov_names)
check('план «б/с» исключён', 'БезСодержания Борис' not in nov_names)
check('план «Б/С» исключён', 'БезСодержанияВерх Влад' not in nov_names)
check('план «БС» исключён', 'БезСодержанияКоротко Ким' not in nov_names)
check('план «Б» (больничный) исключён', 'Больничный Борис' not in nov_names)
check('подмены имён нет: Жажин Максим попадает как есть', 'Жажин Максим' in nov_names)
check('Бочанова Руслана в списке нет', 'Бочанов Руслан' not in nov_names)

oct_names = [e['name'] for e in pf.collect_meal_employees(db, OCT)]
print('  октябрь, список:', oct_names)
check('старый код «11» по-прежнему попадает', 'Старый Одиннадцать' in oct_names)
check('старый код «Д» по-прежнему попадает', 'Старый Доп' in oct_names)

print('=== ПИТАНИЕ: выгрузка XLSX ===')
report = pf.build_meal_report(db, NOV, 'morning')
if isinstance(report, pf.ReportWarning):
    check('выгрузка питания сформирована', False, report.message)
else:
    ws = load_workbook(BytesIO(report.stream.getvalue())).worksheets[0]
    text = ' | '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    check('в файле есть «Я»-смена', 'Явкин Яков' in text)
    check('в файле есть «В»-смена', 'Второй Виктор' in text)
    check('в файле есть факт', 'Фактов Факт' in text)
    check('отпуска нет в файле', 'Отпускной Олег' not in text)
    check('«б/с» нет в файле', 'БезСодержания' not in text)
    check('больничного нет в файле', 'Больничный Борис' not in text)
    check('в файле Жажин (без подмены)', 'Жажин Максим' in text and 'Бочанов Руслан' not in text)

# ------------------------------------------------------- медосмотр на копии листа
shutil.copy2(REAL_XLSX, TEST_XLSX)
me.SCHEDULE_FILE = TEST_XLSX           # модуль импортировал имя по значению
sg.SCHEDULE_FILE = TEST_XLSX

wb = load_workbook(TEST_XLSX)
ws = wb['11.2026']
header_row, day_cols, _kept, max_row = sg._visible_layout(ws, 2026, 11)
named = [(r, str(ws.cell(r, 3).value).strip()) for r in range(header_row + 2, max_row + 1)
         if ws.cell(r, 3).value and str(ws.cell(r, 3).value).strip()]
people = [(r, name) for r, name in named if not sg._is_placeholder_name(name)]
vacancies = [(r, name) for r, name in named if sg._is_placeholder_name(name)]
day5 = next(c for c, d in day_cols.items() if d == 5)
day6 = next(c for c, d in day_cols.items() if d == 6)

ve_row, ve_name = people[0]            # будет «В»
ya_row, ya_name = people[1]            # будет «Я»
other_row, other_name = people[2]      # будет «О» (отпуск)
vac_row, vac_name = max(
    vacancies,
    key=lambda item: sum(1 for c in day_cols if ws.cell(item[0], c).value not in (None, '')),
)                                      # служебная строка со сменами — в список не должна попасть

ws.cell(ve_row, day5).value = 'В'      # доп смена
ws.cell(ya_row, day5).value = 'Я'      # основная смена
ws.cell(other_row, day5).value = 'О'   # отпуск — сменой не считается
ws.cell(other_row, day6).value = None  # пусто — тоже не считается
wb.save(TEST_XLSX)
print(f'=== МЕДОСМОТР: в копии листа {ve_name} — «В» 05.11, '
      f'{ya_name} — «Я» 05.11, {other_name} — «О» 05.11, '
      f'служебная строка {vac_name!r} — со сменами ===')

rows, error = me.collect_medcheck_rows(db, 2026, 11)
check('медосмотр за ноябрь собирается', error is None, error or '')
by_name = {row['name']: row for row in rows}
check('«В» попал в список медосмотра', ve_name in by_name)
check('у сотрудника с «В» есть код «В»', 'В' in (by_name.get(ve_name, {}).get('shifts') or []),
      str(by_name.get(ve_name, {}).get('shifts')))
check('у сотрудника с «Я» есть код «Я»', 'Я' in (by_name.get(ya_name, {}).get('shifts') or []),
      str(by_name.get(ya_name, {}).get('shifts')))
check('отпуск сменой не считается', 'О' not in (by_name.get(other_name, {}).get('shifts') or []))
check(f'служебная строка {vac_name!r} со сменами в список не попала', vac_name not in by_name,
      f'смен в строке: {sum(1 for c in day_cols if ws.cell(vac_row, c).value not in (None, ""))}')
check('служебные строки «вакансия» в список не попадают',
      not any('вакан' in row['name'].lower() for row in rows),
      str([r['name'] for r in rows if 'вакан' in r['name'].lower()]))

summary = me.medcheck_summary(db, 2026, 11)
print('  сводка за месяц:', {k: v for k, v in summary.items() if k in ('employees', 'by_shift')})
check('by_shift содержит «Я» и «В»', set(summary['by_shift']) == {'Я', 'В'}, str(summary['by_shift']))
check('в by_shift учтена «В»', summary['by_shift'].get('В', 0) >= 1)
check('by_shift «Я» = число людей с «Я»',
      summary['by_shift']['Я'] == sum(1 for r in rows if 'Я' in r['shifts']))
check('by_shift «В» = число людей с «В»',
      summary['by_shift']['В'] == sum(1 for r in rows if 'В' in r['shifts']))

summary_day = me.medcheck_summary(db, 2026, 11, day=5)
names_day = [r['name'] for r in summary_day['rows']]
check('за 05.11 в списке есть сотрудник с «В»', ve_name in names_day)
check('за 05.11 в списке есть сотрудник с «Я»', ya_name in names_day)
check('за 05.11 отпускник не попал', other_name not in names_day)

summary_days = me.medcheck_summary(db, 2026, 11, with_days=True)
check('счётчик по дням есть', 'by_day' in summary_days and bool(summary_days['by_day']))
check('за 05.11 в счётчике по дням столько же людей, сколько в списке за день',
      summary_days['by_day'].get(5) == len(names_day),
      f'by_day[5]={summary_days["by_day"].get(5)}, в списке {len(names_day)}')

print('=== МЕДОСМОТР: выгрузка DOCX ===')
stream, filename = me.build_medcheck_docx(db, 2026, 11)
if stream is None:
    check('документ медосмотра сформирован', False, filename)
else:
    doc = Document(BytesIO(stream.getvalue()))
    text = '\n'.join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    check('документ медосмотра сформирован', True, filename)
    check('в документе есть сотрудник с «В»', ve_name in text)
    check('в документе есть сотрудник с «Я»', ya_name in text)
    check('служебных строк в документе нет', 'вакан' not in text.lower())
    check('в документе период «на ноябрь 2026 г.»',
          'ноябрь 2026' in '\n'.join(p.text for p in doc.paragraphs))

stream_day, filename_day = me.build_medcheck_docx(db, 2026, 11, day=5)
if stream_day is None:
    check('документ за 05.11 сформирован', False, filename_day)
else:
    doc_day = Document(BytesIO(stream_day.getvalue()))
    text_day = '\n'.join(cell.text for table in doc_day.tables
                         for row in table.rows for cell in row.cells)
    check('документ за 05.11 сформирован', True, filename_day)
    check('в документе за 05.11 отпускника нет', other_name not in text_day)

print('=== МЕДОСМОТР: цифры в ноябрьском листе читаются как «Я» ===')
free_col = next((c for c, d in day_cols.items() if not ws.cell(other_row, c).value), None)
if free_col is None:
    check('нашлась пустая клетка для проверки цифры', False)
else:
    free_day = day_cols[free_col]
    before_days = me.medcheck_summary(db, 2026, 11, with_days=True)['by_day']
    wb2 = load_workbook(TEST_XLSX)
    wb2['11.2026'].cell(other_row, free_col).value = '11'   # старый код в ноябре
    wb2.save(TEST_XLSX)
    after_days = me.medcheck_summary(db, 2026, 11, with_days=True)['by_day']
    check(f'цифра «11» в листе {free_day:02d}.11 посчитана как смена',
          after_days.get(free_day, 0) == before_days.get(free_day, 0) + 1,
          f'было {before_days.get(free_day, 0)}, стало {after_days.get(free_day, 0)}')
    rows_digit, _err = me.collect_medcheck_rows(db, 2026, 11)
    person = next((row for row in rows_digit if row['name'] == other_name), None)
    check('в списке у этого человека код смены «Я» (а не «11»)',
          bool(person) and 'Я' in person['shifts'], str(person and person['shifts']))

print('=== СТАРЫЕ МЕСЯЦЫ (октябрь) ===')
oct_summary = me.medcheck_summary(db, 2026, 10)
print('  октябрь:', {k: v for k, v in oct_summary.items() if k in ('employees', 'by_shift')})
check('октябрь считает коды 11/9/8', set(oct_summary['by_shift']) == {'11', '9', '8'},
      str(oct_summary['by_shift']))
db.close()

# ------------------------------------------------- реальные данные: эндпоинты
me.SCHEDULE_FILE = sg.SCHEDULE_FILE = REAL_XLSX
print('=== РЕАЛЬНЫЕ ДАННЫЕ: эндпоинты (только чтение) ===')
import app as webapp
from database import SessionLocal

rdb = SessionLocal()
try:
    info = webapp.medcheck_info(db=rdb, year=2026, month=11)
    print('  /medcheck/summary/ 11.2026: людей', info['employees'], 'смены', info['by_shift'])
    check('эндпоинт медосмотра отвечает', info.get('status') == 'success')
    check('в ответе эндпоинта нет служебных строк',
          not any('вакан' in r['name'].lower() for r in info['rows']))

    resp = webapp.export_medcheck(db=rdb, year=2026, month=11)
    check('эндпоинт выгрузки медосмотра отдаёт DOCX',
          'wordprocessingml' in resp.media_type, resp.media_type)

    resp_meal = webapp.export_meal(
        request=webapp.ExportMealRequest(date='2026-11-05', meal_type='morning'), db=rdb)
    check('эндпоинт питания отдаёт XLSX',
          getattr(resp_meal, 'media_type', '').endswith('spreadsheetml.sheet'),
          getattr(resp_meal, 'media_type', type(resp_meal).__name__))

    resp_meal_oct = webapp.export_meal(
        request=webapp.ExportMealRequest(date='2026-10-05', meal_type='lunch'), db=rdb)
    check('питание за октябрь (старые коды) тоже выгружается',
          getattr(resp_meal_oct, 'media_type', '').endswith('spreadsheetml.sheet')
          or isinstance(resp_meal_oct, dict),
          getattr(resp_meal_oct, 'media_type', type(resp_meal_oct).__name__))
finally:
    rdb.close()

print()
print(f'ИТОГ: успешно {len(ok)}, ошибок {len(fail)}')
for name in fail:
    print('  ОШИБКА:', name)
