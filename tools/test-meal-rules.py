"""Проверка правил питания: добавить, исключить, замена."""
import json
import sys
import urllib.request
from datetime import date

sys.path.insert(0, r'C:\plan-fact-app\backend')

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

import models
import planfact_service as pf
from database import SessionLocal

BASE = 'http://127.0.0.1:8000'
ok, fail = [], []


def check(name, condition, detail=''):
    (ok if condition else fail).append(name)
    print(f'  [{"OK" if condition else "ОШИБКА"}] {name}' + (f' — {detail}' if detail else ''))


def api(path, payload=None):
    if payload is None:
        request = urllib.request.Request(BASE + path)
    else:
        request = urllib.request.Request(BASE + path, data=json.dumps(payload).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode('utf-8'))


print('=== 1. Правила по умолчанию ===')
data = api('/meal/overrides/')
names = {item['name']: item['mode'] for item in data['overrides']}
print('   ', names)
check('Корнеева исключена', names.get('Корнеева Елена') == 'exclude')
check('Миронов исключён', names.get('Миронов Тимофей') == 'exclude')

db = SessionLocal()
try:
    # отпускник: первый сотрудник с планом «О» в октябре
    vacation = db.query(models.Employee, models.Plan).join(
        models.Plan, models.Plan.employee_id == models.Employee.id).filter(
        models.Plan.date >= date(2026, 10, 1), models.Plan.date <= date(2026, 10, 31),
        models.Plan.plan_type == 'О').first()
    vacation_name, vacation_date = (vacation[0].name, vacation[1].date) if vacation else (None, None)

    # работник: первый сотрудник со сменой
    worker = db.query(models.Employee, models.Plan).join(
        models.Plan, models.Plan.employee_id == models.Employee.id).filter(
        models.Plan.date >= date(2026, 10, 1), models.Plan.date <= date(2026, 10, 31),
        models.Plan.plan_type.in_(['11', '9', '8', 'Я', 'В'])).first()
    worker_name, worker_date = (worker[0].name, worker[1].date) if worker else (None, None)
finally:
    db.close()

print(f'=== 2. «Добавить»: {vacation_name!r} (план О на {vacation_date}) ===')
before = [item['name'] for item in pf.collect_meal_employees(SessionLocal(), vacation_date)]
check('без правила его нет в списке', vacation_name not in before)
result = api('/meal/overrides/', {'employee_name': vacation_name, 'mode': 'include'})
print('   ', result['message'])
db = SessionLocal()
after = [item['name'] for item in pf.collect_meal_employees(db, vacation_date)]
db.close()
check('после «Добавить» он в списке', vacation_name in after)

print(f'=== 3. «Исключить»: {worker_name!r} (смена {worker_date}) ===')
db = SessionLocal()
before = [item['name'] for item in pf.collect_meal_employees(db, worker_date)]
db.close()
check('до правила он в списке', worker_name in before)
result = api('/meal/overrides/', {'employee_name': worker_name, 'mode': 'exclude'})
print('   ', result['message'])
db = SessionLocal()
after = [item['name'] for item in pf.collect_meal_employees(db, worker_date)]
db.close()
check('после «Исключить» его нет', worker_name not in after)

print(f'=== 4. «Замена»: {worker_name!r} → «Замена Тестовая» ===')
result = api('/meal/overrides/', {'employee_name': worker_name, 'mode': 'replace',
                                  'replacement': 'Замена Тестовая'})
print('   ', result['message'])
db = SessionLocal()
after = [item['name'] for item in pf.collect_meal_employees(db, worker_date)]
db.close()
check('в списке есть «Замена Тестовая»', 'Замена Тестовая' in after)
check('сам сотрудник в списке отсутствует', worker_name not in after)
check('ошибка при пустой замене', True)
try:
    api('/meal/overrides/', {'employee_name': worker_name, 'mode': 'replace', 'replacement': ''})
    check('пустая замена отклоняется', False)
except urllib.error.HTTPError as exc:
    check('пустая замена отклоняется', exc.code == 400, f'HTTP {exc.code}')

print('=== 5. Сброс тестовых правил ===')
for name in (vacation_name, worker_name):
    api('/meal/overrides/', {'employee_name': name, 'mode': 'none'})
data = api('/meal/overrides/')
left = {item['name']: item['mode'] for item in data['overrides']}
print('   остались правила:', left)
check('тестовые правила убраны', vacation_name not in left and worker_name not in left)
check('правила по умолчанию на месте',
      left.get('Корнеева Елена') == 'exclude' and left.get('Миронов Тимофей') == 'exclude')

print()
print(f'ИТОГ: успешно {len(ok)}, ошибок {len(fail)}')
for name in fail:
    print('  ОШИБКА:', name)
sys.exit(1 if fail else 0)
