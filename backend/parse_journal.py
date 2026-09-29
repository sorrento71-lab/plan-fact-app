import pandas as pd
import re
import os
from datetime import datetime, date, time
from database import SessionLocal
import models


def parse_time_value(time_str: str):
    """
    Парсит время из строки формата "07:53 (7)"
    Возвращает объект time или None
    """
    if not time_str or time_str in ['', 'nan', 'None', '(нет)', 'нет']:
        return None

    clean_str = str(time_str).strip()

    # Убираем комментарии в скобках
    if '(' in clean_str:
        clean_str = clean_str.split('(')[0].strip()

    # Ищем время в формате HH:MM
    time_match = re.search(r'(\d{1,2}):(\d{2})', clean_str)
    if not time_match:
        return None

    hours = int(time_match.group(1))
    minutes = int(time_match.group(2))

    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None

    try:
        return time(hours, minutes)
    except:
        return None


def round_to_hour(time_val, is_start_time=True):
    """
    Округляет время по логике из макроса:
    - Приход: если между 6:00 и 8:00 → 8:00
    - Уход: округление до часа (>=30 минут → следующий час)
    """
    if time_val is None:
        return None

    hours = time_val.hour
    minutes = time_val.minute

    if is_start_time:
        # Если время между 6:00 и 8:00 → округляем до 8:00
        if 6 <= hours < 8:
            return time(8, 0)

    # Округление до часа (>= 30 минут → следующий час)
    if minutes >= 30:
        hours = hours + 1

    if hours >= 24:
        hours = 0

    return time(hours, 0)


def find_employee_by_name(db, name):
    """
    Находит сотрудника по имени с приоритетом:
    1. Точное совпадение полного имени
    2. Совпадение по фамилии + полному имени
    3. Совпадение по фамилии + первой букве имени
    4. Совпадение по фамилии
    """
    name = name.strip()
    if not name:
        return None

    # 1. Точное совпадение полного имени
    employee = db.query(models.Employee).filter_by(name=name).first()
    if employee:
        return employee

    # Разбиваем имя на части
    name_parts = name.split()
    if len(name_parts) < 2:
        # Если только одно слово — ищем по фамилии
        employees = db.query(models.Employee).filter(
            models.Employee.name.ilike(f'%{name}%')
        ).all()
        if len(employees) == 1:
            return employees[0]
        return None

    last_name = name_parts[0].lower()
    first_name = name_parts[1].lower() if len(name_parts) > 1 else ''
    first_letter = first_name[0] if first_name else ''

    all_employees = db.query(models.Employee).all()

    # 2. Ищем по фамилии + полному имени
    for emp in all_employees:
        emp_parts = emp.name.split()
        if len(emp_parts) < 2:
            continue
        emp_last = emp_parts[0].lower()
        emp_first = emp_parts[1].lower() if len(emp_parts) > 1 else ''

        if emp_last == last_name and emp_first == first_name:
            return emp

    # 3. Ищем по фамилии + первой букве имени
    candidates = []
    for emp in all_employees:
        emp_parts = emp.name.split()
        if len(emp_parts) < 2:
            continue
        emp_last = emp_parts[0].lower()
        emp_first = emp_parts[1].lower() if len(emp_parts) > 1 else ''

        if emp_last == last_name and emp_first.startswith(first_letter):
            candidates.append(emp)

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        # Если несколько кандидатов — пробуем точное совпадение полного имени
        for emp in candidates:
            if emp.name.lower() == name.lower():
                return emp
        # Возвращаем первого
        return candidates[0]

    # 4. Последняя попытка — по фамилии
    for emp in all_employees:
        emp_parts = emp.name.split()
        if len(emp_parts) < 2:
            continue
        emp_last = emp_parts[0].lower()
        if emp_last == last_name:
            return emp

    return None


def find_timesheet_sheet(filepath):
    """
    Находит лист с табелем в файле
    """
    try:
        xl = pd.ExcelFile(filepath)
        sheet_names = xl.sheet_names
        print(f"📋 Найдены листы: {sheet_names}")

        for name in sheet_names:
            if 'ТАБЕЛЬ' in name.upper() or 'TABEL' in name.upper():
                return name

        for name in sheet_names:
            if name not in ['Лист1', 'Sheet1', 'Лист2', 'Sheet2', '']:
                try:
                    df = pd.read_excel(filepath, sheet_name=name, header=None, nrows=5)
                    if not df.empty and df.shape[1] > 3:
                        first_row = df.iloc[0].astype(str).str.lower()
                        if any('фио' in str(x) or 'фамилия' in str(x) or 'сотрудник' in str(x) for x in first_row):
                            return name
                except:
                    continue

        for name in sheet_names:
            if name not in ['Лист1', 'Sheet1', 'Лист2', 'Sheet2', '']:
                try:
                    df = pd.read_excel(filepath, sheet_name=name, header=None, nrows=5)
                    if not df.empty and df.shape[1] > 3:
                        return name
                except:
                    continue

        return sheet_names[0] if sheet_names else None

    except Exception as e:
        print(f"⚠️ Ошибка поиска листа: {e}")
        return None


def parse_journal_file(filepath: str, db=None):
    """Парсит файл журнала/табеля"""
    print(f"📂 Открываем файл: {filepath}")

    if not os.path.exists(filepath):
        return {"status": "error", "message": "File not found"}

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
        print("🔌 Создано новое подключение к БД")

    try:
        sheet_name = find_timesheet_sheet(filepath)
        if not sheet_name:
            return {"status": "error", "message": "Не найден подходящий лист с данными"}

        print(f"📄 Используем лист: {sheet_name}")

        print("📖 Читаем Excel...")
        df = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
        print(f"📊 Размер DataFrame: {df.shape}")

        if df.empty:
            return {"status": "error", "message": "Sheet is empty"}

        added = 0
        updated = 0

        format_type = 'unknown'

        for row_idx in range(min(20, len(df))):
            row_text = ' '.join([str(x).lower() for x in df.iloc[row_idx, :10] if pd.notna(x)])
            if 'табель' in row_text or 'Т-13' in row_text or 'Унифицированная форма' in row_text:
                format_type = 'timesheet'
                print("📋 Обнаружен формат ТАБЕЛЬ (Т-13)")
                break

        if format_type == 'unknown':
            format_type = 'journal'
            print("📋 Обнаружен формат ЖУРНАЛ")

        if format_type == 'timesheet':
            result = parse_timesheet_format(df, db, filepath, sheet_name)
        else:
            result = parse_journal_format(df, db)

        # Понятная подсказка, если в «Журнал» случайно загрузили файл графика
        # (в графике листы называются как «08.2026», «09.2026» и т.п.)
        if isinstance(result, dict) and result.get('status') == 'error':
            sheet_str = str(sheet_name or '')
            looks_like_schedule = bool(re.search(r'\d{1,2}\.\d{4}', sheet_str))
            if looks_like_schedule:
                print("⚠️ Похоже, загружен файл ГРАФИКА, а не журнала")
                result['message'] = (
                    f"Похоже, это файл графика (лист «{sheet_str}»), а не журнала. "
                    f"Загрузите график через кнопку «📤 График», журнал — через «📤 Журнал»."
                )

        db.commit()
        return result

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


def detect_month_year(filepath, sheet_name, df):
    """Определяет месяц и год журнала.

    Порядок: дата в имени листа (08.2026) → дата в шапке файла
    (01.08.2026 или «август 2026») → текущий месяц.
    """
    today = date.today()
    texts = [str(sheet_name or '')]
    texts += [' '.join(str(x) for x in df.iloc[i, :15] if pd.notna(x))
              for i in range(min(20, len(df)))]

    month_names = {
        'январь': 1, 'января': 1, 'февраль': 2, 'февраля': 2, 'март': 3, 'марта': 3,
        'апрель': 4, 'апреля': 4, 'май': 5, 'мая': 5, 'июнь': 6, 'июня': 6,
        'июль': 7, 'июля': 7, 'август': 8, 'августа': 8, 'сентябрь': 9, 'сентября': 9,
        'октябрь': 10, 'октября': 10, 'ноябрь': 11, 'ноября': 11, 'декабрь': 12, 'декабря': 12,
    }

    for text in texts:
        text_l = str(text).lower()
        # 1) полная дата: 01.08.2026
        m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text_l)
        if m:
            month, year = int(m.group(2)), int(m.group(3))
            if 1 <= month <= 12:
                print(f"📅 Месяц/год из даты в файле: {month}/{year}")
                return month, year
        # 2) месяц.год: 08.2026
        m = re.search(r'(?:^|\D)(\d{1,2})\.(\d{4})(?:\D|$)', text_l)
        if m:
            month, year = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12:
                print(f"📅 Месяц/год из листа: {month}/{year}")
                return month, year
        # 3) русское название месяца
        for ru_name, month in month_names.items():
            if ru_name in text_l:
                m = re.search(r'20\d{2}', text_l)
                year = int(m.group(0)) if m else today.year
                print(f"📅 Месяц/год из названия: {month}/{year}")
                return month, year

    print(f"⚠️ Месяц/год не определены, берём текущий: {today.month}/{today.year}")
    return today.month, today.year


def parse_timesheet_format(df, db, filepath=None, sheet_name=None):
    """Парсит табель формата Т-13"""
    added = 0
    updated = 0

    header_row_idx = None
    for row_idx in range(0, min(30, len(df))):
        row_text = ' '.join([str(x).lower() for x in df.iloc[row_idx, 0:5] if pd.notna(x)])
        if 'фамилия' in row_text and 'инициалы' in row_text:
            header_row_idx = row_idx
            break

    if header_row_idx is None:
        for row_idx in range(0, min(30, len(df))):
            row_text = ' '.join([str(x).lower() for x in df.iloc[row_idx, 0:5] if pd.notna(x)])
            if 'сотрудник' in row_text or 'фио' in row_text:
                header_row_idx = row_idx
                break

    if header_row_idx is None:
        return {"status": "error", "message": "Не найдена строка с заголовками"}

    print(f"📋 Строка с заголовками: {header_row_idx}")

    col_employee = None
    col_tab_num = None

    for col_idx in range(min(10, len(df.columns))):
        val = str(df.iloc[header_row_idx, col_idx]).strip().lower() if pd.notna(
            df.iloc[header_row_idx, col_idx]) else ""

        if 'фамилия' in val or 'инициалы' in val or 'фио' in val:
            col_employee = col_idx
        elif 'табельный' in val or 'таб' in val:
            col_tab_num = col_idx

    if col_employee is None:
        col_employee = 1

    print(f"📍 Колонка сотрудников: {col_employee}, Табельный номер: {col_tab_num}")

    date_row_idx = None
    for row_idx in range(header_row_idx + 1, header_row_idx + 5):
        if row_idx >= len(df):
            break
        for col_idx in range(3, min(len(df.columns), 35)):
            val = df.iloc[row_idx, col_idx]
            if pd.notna(val):
                val_str = str(val).strip()
                if val_str.isdigit() and 1 <= int(val_str) <= 31:
                    date_row_idx = row_idx
                    break
        if date_row_idx is not None:
            break

    if date_row_idx is None:
        return {"status": "error", "message": "Не найдена строка с датами"}

    print(f"📅 Строка с датами: {date_row_idx}")

    date_cols = []
    date_nums = []
    for col_idx in range(3, min(len(df.columns), 35)):
        val = df.iloc[date_row_idx, col_idx]
        if pd.notna(val):
            val_str = str(val).strip()
            if val_str.isdigit():
                num = int(val_str)
                if 1 <= num <= 31:
                    date_cols.append(col_idx)
                    date_nums.append(num)

    print(f"📅 Найдено {len(date_cols)} колонок с датами")

    target_month, target_year = detect_month_year(filepath, sheet_name, df)
    print(f"📅 Целевой период: {target_month}/{target_year}")

    for row_idx in range(header_row_idx + 3, len(df)):
        emp_name = str(df.iloc[row_idx, col_employee]).strip() if col_employee < len(df.columns) else ""

        if not emp_name or emp_name in ['', 'nan', 'None', 'Итого', 'Всего', 'ИТОГО']:
            continue

        print(f"👤 Обработка: {emp_name}")

        # ИСПРАВЛЕНО: используем улучшенный поиск
        employee = find_employee_by_name(db, emp_name)

        if not employee:
            print(f"⚠️ Сотрудник не найден: {emp_name}")
            continue

        # Сохраняем табельный номер из журнала, если такая колонка есть
        if col_tab_num is not None and col_tab_num < len(df.columns):
            tab_val = df.iloc[row_idx, col_tab_num]
            if pd.notna(tab_val):
                tab_str = str(tab_val).strip()
                if tab_str and tab_str.lower() != 'nan' and employee.tab_number != tab_str:
                    employee.tab_number = tab_str
                    print(f"🆔 Табельный номер {employee.name}: {tab_str}")

        for idx, col_idx in enumerate(date_cols):
            if col_idx + 1 >= len(df.columns):
                continue

            day_num = date_nums[idx] if idx < len(date_nums) else None
            if not day_num:
                continue

            try:
                target_date = date(target_year, target_month, day_num)
            except ValueError:
                continue

            mark_val = df.iloc[row_idx, col_idx] if col_idx < len(df.columns) else None
            is_present = False
            if pd.notna(mark_val):
                mark_str = str(mark_val).strip().upper()
                if mark_str == 'Я':
                    is_present = True

            hours_val = df.iloc[row_idx, col_idx + 1] if col_idx + 1 < len(df.columns) else None
            fact_hours = 0
            if pd.notna(hours_val):
                try:
                    if isinstance(hours_val, (int, float)):
                        fact_hours = float(hours_val)
                    elif isinstance(hours_val, str):
                        hours_str = hours_val.strip().replace(',', '.')
                        if hours_str.isdigit() or hours_str.replace('.', '').isdigit():
                            fact_hours = float(hours_str)
                except:
                    pass

            if is_present and fact_hours == 0:
                fact_hours = 11.0

            if not is_present and fact_hours == 0:
                continue

            existing = db.query(models.Fact).filter(
                models.Fact.employee_id == employee.id,
                models.Fact.date == target_date
            ).first()

            start_time = "08:00" if is_present or fact_hours > 0 else ""
            end_time = ""
            if fact_hours > 0:
                start_min = 8 * 60
                end_min = start_min + int(fact_hours * 60)
                end_hour = end_min // 60
                end_minute = end_min % 60
                if end_hour >= 24:
                    end_hour -= 24
                end_time = f"{end_hour:02d}:{end_minute:02d}"

            if existing:
                if (existing.fact_hours != fact_hours or
                        existing.start_time != start_time or
                        existing.end_time != end_time):
                    existing.fact_hours = fact_hours
                    existing.start_time = start_time
                    existing.end_time = end_time
                    updated += 1
                    print(f"  🔄 Обновлен: {target_date} | {fact_hours}ч")
            else:
                fact = models.Fact(
                    employee_id=employee.id,
                    date=target_date,
                    start_time=start_time,
                    end_time=end_time,
                    fact_hours=fact_hours
                )
                db.add(fact)
                added += 1
                print(f"  ✅ Добавлен: {target_date} | {fact_hours}ч")

    print(f"\n✅ Табель обработан")
    print(f"   Добавлено: {added}")
    print(f"   Обновлено: {updated}")

    return {
        "status": "success",
        "added": added,
        "updated": updated
    }


def parse_journal_format(df, db):
    """Парсит обычный журнал (старый формат)"""
    added = 0
    updated = 0

    header_row_idx = None
    for row_idx in range(0, min(20, len(df))):
        row_text = ' '.join([str(x).lower() for x in df.iloc[row_idx, 0:6] if pd.notna(x)])
        if 'дата' in row_text and ('фио' in row_text or 'сотрудник' in row_text):
            header_row_idx = row_idx
            break

    if header_row_idx is None:
        return {"status": "error", "message": "Не найдена строка с заголовками (Дата, ФИО)"}

    print(f"📋 Строка с заголовками: {header_row_idx}")

    col_map = {}
    for col_idx in range(min(10, len(df.columns))):
        val = str(df.iloc[header_row_idx, col_idx]).strip().lower() if pd.notna(
            df.iloc[header_row_idx, col_idx]) else ""

        if 'дата' in val:
            col_map['date'] = col_idx
        elif 'фио' in val or 'сотрудник' in val:
            col_map['employee'] = col_idx
        elif 'табельный' in val or 'таб' in val:
            col_map['tab'] = col_idx
        elif 'отдел' in val:
            col_map['department'] = col_idx
        elif 'события' in val or 'время' in val:
            col_map['events'] = col_idx

    print(f"📍 Найденные колонки: {col_map}")

    if 'date' not in col_map:
        col_map['date'] = 0

    if 'employee' not in col_map:
        col_map['employee'] = 2

    for row_idx in range(header_row_idx + 1, len(df)):
        date_val = df.iloc[row_idx, col_map['date']] if col_map['date'] < len(df.columns) else None
        emp_val = df.iloc[row_idx, col_map['employee']] if col_map['employee'] < len(df.columns) else None

        if pd.isna(date_val) and pd.isna(emp_val):
            continue

        if pd.isna(date_val):
            continue

        try:
            if isinstance(date_val, datetime):
                target_date = date_val.date()
            elif isinstance(date_val, date):
                target_date = date_val
            else:
                target_date = pd.to_datetime(date_val).date()
        except:
            continue

        emp_name = str(emp_val).strip() if pd.notna(emp_val) else ""

        if not emp_name or emp_name in ['', 'nan', 'None', 'Итого', 'Всего']:
            continue

        # ИСПРАВЛЕНО: используем улучшенный поиск
        employee = find_employee_by_name(db, emp_name)

        if not employee:
            print(f"⚠️ Сотрудник не найден: {emp_name}")
            continue

        # Сохраняем табельный номер из журнала, если такая колонка есть
        if 'tab' in col_map and col_map['tab'] < len(df.columns):
            tab_val = df.iloc[row_idx, col_map['tab']]
            if pd.notna(tab_val):
                tab_str = str(tab_val).strip()
                if tab_str and tab_str.lower() != 'nan' and employee.tab_number != tab_str:
                    employee.tab_number = tab_str
                    print(f"🆔 Табельный номер {employee.name}: {tab_str}")

        start_time = None
        end_time = None
        fact_hours = 0

        if 'events' in col_map:
            events_val = str(df.iloc[row_idx, col_map['events']]).strip() if pd.notna(
                df.iloc[row_idx, col_map['events']]) else ""

            if col_map['events'] + 1 < len(df.columns):
                events_val2 = str(df.iloc[row_idx, col_map['events'] + 1]).strip() if pd.notna(
                    df.iloc[row_idx, col_map['events'] + 1]) else ""
            else:
                events_val2 = ""

            start_time = parse_time_value(events_val)
            end_time = parse_time_value(events_val2)

            if not end_time and events_val and '—' in events_val:
                parts = events_val.split('—')
                if len(parts) >= 2:
                    start_time = parse_time_value(parts[0])
                    end_time = parse_time_value(parts[1])

        if start_time:
            rounded_start = round_to_hour(start_time, is_start_time=True)
            if rounded_start:
                start_time = rounded_start

        if end_time:
            end_hour = end_time.hour - 1
            end_min = end_time.minute
            if end_hour < 0:
                end_hour = 23
            try:
                end_time_minus_hour = time(end_hour, end_min)
                rounded_end = round_to_hour(end_time_minus_hour, is_start_time=False)
                if rounded_end:
                    end_time = rounded_end
            except:
                pass

        if start_time and end_time:
            try:
                start_min = start_time.hour * 60 + start_time.minute
                end_min = end_time.hour * 60 + end_time.minute
                if end_min < start_min:
                    end_min += 24 * 60
                diff_min = end_min - start_min
                fact_hours = round(diff_min / 60, 2)
            except:
                pass

        start_str = start_time.strftime("%H:%M") if start_time else ""
        end_str = end_time.strftime("%H:%M") if end_time else ""

        existing = db.query(models.Fact).filter(
            models.Fact.employee_id == employee.id,
            models.Fact.date == target_date
        ).first()

        if existing:
            if (existing.start_time != start_str or
                    existing.end_time != end_str or
                    existing.fact_hours != fact_hours):
                existing.start_time = start_str
                existing.end_time = end_str
                existing.fact_hours = fact_hours
                updated += 1
                print(f"🔄 Обновлен: {emp_name} | {target_date} | {start_str} - {end_str} | {fact_hours}ч")
        else:
            fact = models.Fact(
                employee_id=employee.id,
                date=target_date,
                start_time=start_str,
                end_time=end_str,
                fact_hours=fact_hours
            )
            db.add(fact)
            added += 1
            print(f"✅ Добавлен: {emp_name} | {target_date} | {start_str} - {end_str} | {fact_hours}ч")

    print(f"\n✅ Журнал обработан")
    print(f"   Добавлено: {added}")
    print(f"   Обновлено: {updated}")

    return {
        "status": "success",
        "added": added,
        "updated": updated
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = input("Введите путь к файлу: ")

    result = parse_journal_file(filepath)
    print(f"\n✅ Результат: {result}")