"""Проверка загрузки графика: берётся лист выбранного месяца.

Работает на временной базе и копии файла графика — рабочие данные не меняются.
"""
import os
import shutil
import sys
from datetime import date

# Windows-консоль по умолчанию cp1251: эмодзи в логах парсера роняют вывод
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

sys.path.insert(0, r'C:\plan-fact-app\backend')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import parse_schedule as ps
from schedule_grid import SCHEDULE_FILE

TMP = r'C:\plan-fact-app\.tmp\upload-test'
os.makedirs(TMP, exist_ok=True)
TEST_XLSX = os.path.join(TMP, 'schedule.xlsx')
shutil.copy2(SCHEDULE_FILE, TEST_XLSX)

engine = create_engine('sqlite:///:memory:')
models.Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

ok, fail = [], []


def check(name, condition, detail=''):
    (ok if condition else fail).append(name)
    print(f'  [{"OK" if condition else "ОШИБКА"}] {name}' + (f' — {detail}' if detail else ''))


print('=== 1. Запрос листа за октябрь 2026 ===')
res = ps.parse_schedule_file(TEST_XLSX, db, year=2026, month=10)
print('   ', {k: v for k, v in res.items() if k != 'message'})
check('обработан лист 10.2026', str(res.get('sheet_processed', '')).strip() == '10.2026',
      repr(res.get('sheet_processed')))
october = db.query(models.Plan).filter(
    models.Plan.date >= date(2026, 10, 1), models.Plan.date <= date(2026, 10, 31)).count()
check('в плане появились записи за октябрь', october > 0, f'записей: {october}')
check('сотрудники найдены', res.get('employees_found', 0) > 0,
      f'найдено: {res.get("employees_found")}')

print('=== 2. Листа за запрошенный месяц в файле нет ===')
res2 = ps.parse_schedule_file(TEST_XLSX, db, year=2027, month=1)
print('   ', res2.get('message', res2))
check('вернулась понятная ошибка', res2.get('status') == 'error')
check('в ошибке есть запрошенный месяц', '01.2027' in str(res2.get('message', '')))
check('в ошибке перечислены листы файла', '10.2026' in str(res2.get('message', '')))

print('=== 3. Без указания месяца — прежнее поведение (самый новый лист) ===')
xl = ps.pd.ExcelFile(TEST_XLSX)
expected_latest = ps.get_latest_sheet(xl.sheet_names)
res3 = ps.parse_schedule_file(TEST_XLSX, db)
print('   ', {k: v for k, v in res3.items() if k != 'message'})
check('файл разобран', res3.get('status') == 'success')
check('выбран самый новый лист файла', res3.get('sheet_processed') == expected_latest,
      f'{res3.get("sheet_processed")!r} == {expected_latest!r}')

print('=== 4. Октябрьский лист не затронул другие месяцы ===')
november = db.query(models.Plan).filter(
    models.Plan.date >= date(2026, 11, 1), models.Plan.date <= date(2026, 11, 30)).count()
december = db.query(models.Plan).filter(
    models.Plan.date >= date(2026, 12, 1), models.Plan.date <= date(2026, 12, 31)).count()
print(f'    планов: октябрь — {october}, ноябрь — {november}, декабрь — {december}')

db.close()
shutil.rmtree(TMP, ignore_errors=True)
print()
print(f'ИТОГ: успешно {len(ok)}, ошибок {len(fail)}')
for name in fail:
    print('  ОШИБКА:', name)
sys.exit(1 if fail else 0)
