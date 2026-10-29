import pandas as pd
from datetime import date
import re
import os
from sqlalchemy import and_, or_
from database import SessionLocal
import models
import shift_codes


def parse_month_year_from_sheet(sheet_name: str):
    sheet_name = sheet_name.strip()
    pattern = r'(\d{2})\.(\d{4})'
    match = re.search(pattern, sheet_name)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        return (year, month)
    return None


def get_latest_sheet(sheet_names):
    latest_date = None
    latest_sheet = None

    for sheet_name in sheet_names:
        if sheet_name in ['Лист1', 'Лист2', 'Sheet1', 'Sheet2']:
            continue

        month_year = parse_month_year_from_sheet(sheet_name)
        if month_year:
            year, month = month_year
            try:
                sheet_date = date(year, month, 1)
                if latest_date is None or sheet_date > latest_date:
                    latest_date = sheet_date
                    latest_sheet = sheet_name
            except ValueError:
                continue

    return latest_sheet


def find_sheet_for_month(sheet_names, year, month):
    """Лист ровно за указанный месяц.

    Имена листов в файлах бывают с лишними пробелами («10.2026 »),
    поэтому сравниваем без них.
    """
    if not year or not month:
        return None
    wanted = f'{int(month):02d}.{int(year)}'
    for sheet_name in sheet_names:
        if str(sheet_name).strip() == wanted:
            return sheet_name
    return None


def normalize_plan_type(value: str, day=None) -> str:
    """Код плана из файла.

    `day` — дата записи: с ноября 2026 коды смен приводятся к схеме «Я»/«В»
    (11/9/8 — основная смена, «Д» — доп смена), см. shift_codes.
    """
    result = _normalize_plan_type_raw(value)
    if not result:
        return result
    return shift_codes.canonical(result, day)


def _normalize_plan_type_raw(value: str) -> str:
    if pd.isna(value):
        return None

    value = str(value).strip().lower()

    if not value or value in ['nan', 'none', '']:
        return None

    if '(' in value:
        value = value.split('(')[0].strip()

    if 'б/с' in value:
        return 'б/с'

    if value.isdigit():
        return value

    if value in ['д', 'доп', 'доп смена', 'д.смена']:
        return 'Д'

    if value in ['о', 'отп', 'отпуск', 'от']:
        return 'О'

    if value in ['б', 'бол', 'больничный', 'б/л']:
        return 'Б'

    if value in ['б/с', 'бс', 'без сохранения']:
        return 'б/с'

    if value in ['п', 'пер', 'перенос']:
        return 'п'

    if value in ['в', 'вых', 'выходной']:
        return 'В'

    return value.upper()

def delete_existing_data_for_month(db, year: int, month: int):
    """Удаляет все записи плана и сотрудников за указанный месяц"""

    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1)
    else:
        last_day = date(year, month + 1, 1)

    print(f"🗑️ Удаляем данные за период с {first_day} по {last_day}")

    # Удаляем записи плана за этот месяц
    plan_deleted = db.query(models.Plan).filter(
        models.Plan.date >= first_day,
        models.Plan.date < last_day
    ).delete()
    print(f"🗑️ Удалено записей плана: {plan_deleted}")

    # Находим сотрудников, у которых нет планов в другие месяцы
    # и удаляем их
    employees_deleted = 0

    # Получаем ID всех сотрудников, у которых есть планы в другие месяцы
    employees_with_other_plans = db.query(models.Plan.employee_id).filter(
        ~and_(
            models.Plan.date >= first_day,
            models.Plan.date < last_day
        )
    ).distinct().all()

    employee_ids_with_other_plans = [e[0] for e in employees_with_other_plans]

    # Получаем всех сотрудников
    all_employees = db.query(models.Employee).all()

    for emp in all_employees:
        # Если сотрудник не имеет планов в другие месяцы, удаляем его
        if emp.id not in employee_ids_with_other_plans:
            db.delete(emp)
            employees_deleted += 1

    db.flush()
    print(f"🗑️ Удалено сотрудников: {employees_deleted}")

    return plan_deleted, employees_deleted


def get_or_create_employee(db, name: str, position: str, department: str):
    """Получает существующего сотрудника или создает нового"""

    # Проверяем, существует ли сотрудник с таким именем
    employee = db.query(models.Employee).filter_by(name=name).first()

    if employee:
        # Обновляем данные сотрудника (если изменились)
        if employee.position != position:
            employee.position = position
        if employee.department != department:
            employee.department = department
        return employee, False
    else:
        # Создаем нового сотрудника
        max_order = db.query(models.Employee).count()
        employee = models.Employee(
            name=name,
            position=position,
            department=department,
            order=max_order + 1
        )
        db.add(employee)
        db.flush()  # Получаем ID
        return employee, True


def parse_schedule_file(filepath: str, db=None, year=None, month=None):
    """Загружает план из файла графика.

    year и month задают лист: если они переданы, берётся лист ровно за этот
    месяц (и возвращается понятная ошибка, если такого листа в файле нет).
    Без них поведение прежнее — берётся самый новый лист файла.
    """
    print(f"📂 Открываем файл: {filepath}")

    if not os.path.exists(filepath):
        return {"status": "error", "message": "File not found"}

    print(f"📏 Размер файла: {os.path.getsize(filepath)} байт")

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
        print("🔌 Создано новое подключение к БД")

    try:
        total_employees = 0
        total_records = 0

        print("📖 Читаем Excel...")
        xl = pd.ExcelFile(filepath)
        all_sheets = xl.sheet_names
        print(f"📋 Найдено листов: {all_sheets}")

        # Лист выбираем по месяцу, который сейчас открыт в приложении:
        # в файлах графика обычно лежит много месяцев, и «самый новый лист»
        # приводил к загрузке не того месяца (например, ноября вместо октября).
        if year and month:
            latest_sheet = find_sheet_for_month(all_sheets, year, month)
            if not latest_sheet:
                available = ', '.join(str(name).strip() for name in all_sheets if str(name).strip())
                return {"status": "error",
                        "message": f"В файле нет листа за {int(month):02d}.{int(year)}. "
                                   f"Выберите в шапке месяц, который есть в файле, "
                                   f"или загрузите другой файл. Листы в файле: {available}"}
            print(f"📄 Лист выбранного месяца: {latest_sheet}")
        else:
            latest_sheet = get_latest_sheet(all_sheets)
            if not latest_sheet:
                return {"status": "error", "message": "No valid sheets found"}
            print(f"📄 Выбран самый новый лист: {latest_sheet}")

        month_year = parse_month_year_from_sheet(latest_sheet)
        if not month_year:
            return {"status": "error", "message": f"Cannot parse date from {latest_sheet}"}

        target_year, target_month = month_year
        print(f"📅 Месяц: {target_month}, Год: {target_year}")

        # Старые планы за месяц удаляем НЕ здесь, а по каждому сотруднику из файла:
        # так данные тех, кого нет в загруженном файле, не пропадают
        plan_deleted, employees_deleted = 0, 0

        # Читаем лист
        df = pd.read_excel(filepath, sheet_name=latest_sheet, header=None)
        print(f"📊 Размер DataFrame: {df.shape}")

        if df.empty:
            return {"status": "error", "message": "Sheet is empty"}

        # ============================================================
        # НАХОДИМ СТРОКУ С ДАТАМИ
        # ============================================================
        date_row_idx = None
        for row_idx in range(0, min(10, len(df))):
            for col_idx in range(4, min(len(df.columns), 60)):
                val = df.iloc[row_idx, col_idx] if len(df) > row_idx else None
                if pd.notna(val):
                    val_str = str(val).strip()
                    if val_str.isdigit() and 1 <= int(val_str) <= 31:
                        date_row_idx = row_idx
                        break
            if date_row_idx is not None:
                break

        if date_row_idx is None:
            return {"status": "error", "message": "No date row found"}

        print(f"📅 Строка с датами: {date_row_idx}")

        # Собираем колонки с датами
        date_cols = []
        for col_idx in range(4, min(len(df.columns), 60)):
            val = df.iloc[date_row_idx, col_idx] if len(df) > date_row_idx else None
            if pd.notna(val):
                val_str = str(val).strip()
                if val_str.isdigit() and 1 <= int(val_str) <= 31:
                    date_cols.append(col_idx)

        print(f"📅 Найдено колонок с датами: {len(date_cols)}")

        if len(date_cols) == 0:
            return {"status": "error", "message": "No date columns found"}

        # ============================================================
        # НАХОДИМ СТРОКУ С СОТРУДНИКАМИ
        # ============================================================
        # Заголовок «Сотрудник» в разных файлах стоит по-разному: в строке с
        # датами, отдельной строкой ниже, бывает в верхнем регистре. Если его
        # не найти, начинали перебор на строку позже и теряли первого человека.
        employee_row_idx = None
        for row_idx in range(date_row_idx, min(date_row_idx + 10, len(df))):
            for col_idx in (0, 1, 2):
                if col_idx >= len(df.columns) or len(df) <= row_idx:
                    continue
                value = df.iloc[row_idx, col_idx]
                text = str(value).strip().lower() if pd.notna(value) else ""
                if text in ['сотрудник', 'cотрудник', 'фио']:
                    employee_row_idx = row_idx
                    break
            if employee_row_idx is not None:
                break

        if employee_row_idx is None:
            # заголовка нет — начинаем со строки сразу под датами
            employee_row_idx = date_row_idx + 1

        print(f"📋 Строка с сотрудниками: {employee_row_idx}")

        # Находим всех сотрудников
        skip_words = ['сотрудник', 'cотрудник', 'фио', 'участки', 'участок',
                      'должность', 'итого', 'всего', 'nan', '']
        name_rows = []
        for i in range(employee_row_idx + 1, len(df)):
            val_c = str(df.iloc[i, 2]).strip() if pd.notna(df.iloc[i, 2]) else ""
            val_b = str(df.iloc[i, 1]).strip() if pd.notna(df.iloc[i, 1]) else ""

            if val_c and val_c.lower() not in skip_words:
                name_rows.append((i, 2, val_c))
            elif val_b and val_b.lower() not in skip_words:
                if not val_c or val_c.lower() in skip_words:
                    name_rows.append((i, 1, val_b))

        print(f"👤 Найдено сотрудников: {len(name_rows)}")

        if not name_rows:
            return {"status": "error", "message": "No employees found"}

        # ============================================================
        # ОСНОВНОЙ ЦИКЛ
        # ============================================================
        current_department = ""
        employees_found = 0

        KNOWN_DEPARTMENTS = [
            'Участок сборки крышек',
            'Участок сборки вентиляторов',
            'Участок сбоки ТО',
            'МО',
            'ЧПУ',
            'Склад',
            'Исп.уч.',
            'МЕХ',
            'Мастер',
            'СУ'
        ]

        for row_idx, name_col, emp_name in name_rows:
            emp_name = emp_name.strip()

            if not emp_name or emp_name.lower() in skip_words:
                continue

            # строки-легенды («Я-(основная смена )», «В- (Доп.смена )») — не люди
            if 'смена' in emp_name.casefold() and ('(' in emp_name or ')' in emp_name):
                print(f"  ⏭️ Пропущена служебная строка: {emp_name}")
                continue

            position = str(df.iloc[row_idx, 3]).strip() if pd.notna(df.iloc[row_idx, 3]) else ""

            department = ""

            val_b = str(df.iloc[row_idx, 1]).strip() if pd.notna(df.iloc[row_idx, 1]) else ""
            if val_b and val_b not in ['', 'nan']:
                for dept in KNOWN_DEPARTMENTS:
                    if dept.lower() in val_b.lower():
                        current_department = dept
                        department = dept
                        break

                if not department and len(val_b) > 3 and not any(c.isdigit() for c in val_b):
                    if ' ' not in val_b or len(val_b) < 10:
                        if val_b.upper() not in ['УЧАСТКИ', 'УЧАСТОК', 'СОТРУДНИК', 'ДОЛЖНОСТЬ']:
                            current_department = val_b
                            department = val_b

            if not department:
                val_a = str(df.iloc[row_idx, 0]).strip() if pd.notna(df.iloc[row_idx, 0]) else ""
                if val_a and val_a not in ['', 'nan']:
                    for dept in KNOWN_DEPARTMENTS:
                        if dept.lower() in val_a.lower():
                            current_department = dept
                            department = dept
                            break

                    if not department and len(val_a) > 3 and not any(c.isdigit() for c in val_a):
                        if ' ' not in val_a:
                            current_department = val_a
                            department = val_a

            if not department:
                department = current_department

            print(f"👤 {emp_name} | {department} | {position}")
            employees_found += 1

            # ПОЛУЧАЕМ ИЛИ СОЗДАЕМ СОТРУДНИКА
            employee, is_new = get_or_create_employee(db, emp_name, position, department)

            # заменяем план только этому сотруднику (за месяц из файла)
            month_start = date(target_year, target_month, 1)
            if target_month == 12:
                month_end = date(target_year + 1, 1, 1)
            else:
                month_end = date(target_year, target_month + 1, 1)
            removed = db.query(models.Plan).filter(
                models.Plan.employee_id == employee.id,
                models.Plan.date >= month_start,
                models.Plan.date < month_end
            ).delete()
            plan_deleted += removed
            if removed:
                print(f"  🗑️ Заменяем план за месяц: удалено {removed} записей")

            if is_new:
                total_employees += 1
                print(f"  ✅ Новый сотрудник добавлен (order: {employee.order})")
            else:
                print(f"  ♻️ Существующий сотрудник обновлен")

            records_added = 0
            for col_idx in date_cols:
                if col_idx >= len(df.columns):
                    continue

                day_num = df.iloc[date_row_idx, col_idx]
                if pd.isna(day_num):
                    continue

                try:
                    day_num = int(day_num)
                except:
                    continue

                try:
                    target_date = date(target_year, target_month, day_num)
                except ValueError:
                    continue

                plan_val = df.iloc[row_idx, col_idx] if col_idx < len(df.columns) else None

                if pd.isna(plan_val):
                    continue

                plan_str = str(plan_val).strip()

                if not plan_str or plan_str == '0' or plan_str == 'nan':
                    continue

                # Строка ниже может быть «Вн. совм. …» — её смены относятся
                # к этому же сотруднику и тоже попадают в план
                try:
                    if row_idx + 1 < len(df) and col_idx < len(df.columns):
                        vn_val = df.iloc[row_idx + 1, col_idx]
                        vn_mark = df.iloc[row_idx + 1, 3] if len(df.columns) > 3 else None
                        if (vn_mark is not None and not pd.isna(vn_mark)
                                and 'совм' in str(vn_mark).lower()
                                and vn_val is not None and not pd.isna(vn_val)):
                            vn_str = str(vn_val).strip()
                            if vn_str and vn_str != '0' and vn_str != 'nan':
                                plan_str = vn_str
                except Exception:
                    pass

                plan_type = normalize_plan_type(plan_str, target_date)

                if not plan_type:
                    continue

                # Проверяем, существует ли уже такой план
                existing_plan = db.query(models.Plan).filter(
                    models.Plan.employee_id == employee.id,
                    models.Plan.date == target_date
                ).first()

                if existing_plan:
                    if existing_plan.plan_type != plan_type:
                        existing_plan.plan_type = plan_type
                        records_added += 1
                else:
                    plan = models.Plan(
                        employee_id=employee.id,
                        date=target_date,
                        plan_type=plan_type
                    )
                    db.add(plan)
                    total_records += 1
                    records_added += 1

            if records_added > 0:
                print(f"  📝 Добавлено/обновлено записей плана: {records_added}")

        db.commit()
        print(f"\n✅ Лист {latest_sheet} обработан")
        print(f"   Найдено сотрудников: {employees_found}")
        print(f"   Добавлено/обновлено сотрудников: {total_employees}")
        print(f"   Добавлено записей плана: {total_records}")
        print(f"   Дней обработано: {len(date_cols)}")

        return {
            "status": "success",
            "employees": total_employees,
            "employees_found": employees_found,
            "records": total_records,
            "days": len(date_cols),
            "sheet_processed": latest_sheet,
            "deleted_plans": plan_deleted,
            "deleted_employees": employees_deleted
        }

    except Exception as e:
        import traceback
        print(f"❌ ОШИБКА: {e}")
        print(traceback.format_exc())
        if db:
            db.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        if close_db and db:
            db.close()
            print("🔌 Подключение к БД закрыто")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = input("Введите путь к файлу ГРАФИК_ФОРМА A3.xlsx: ")

    result = parse_schedule_file(filepath)
    print(f"\n✅ Результат: {result}")
