"""Готовит «пустые копии» файлов с данными для публичного репозитория.

Что делает:
1. копирует форму и вычищает данные: убирает строки с ФИО и всё, что в них
   (смены, часы, дни) — оформление, объединения, шапка и подписи остаются;
2. убирает имена из служебных ячеек (например «____Р.А.Бочанов» -> «____»);
3. создаёт пустую базу со схемой;
4. проверяет результат: если где-то осталось ФИО — скрипт падает с ошибкой.

Результат — в папке samples/, рабочие файлы не меняются.
"""
import os
import re
import shutil
import sys

sys.path.insert(0, r'C:\plan-fact-app\backend')

from openpyxl import load_workbook
from sqlalchemy import create_engine

import models

ROOT = r'C:\plan-fact-app'
SAMPLES = os.path.join(ROOT, 'samples')

# «Иванов Иван» и «Иванов Иван Иванович»
NAME_FULL = re.compile(r'^[А-ЯЁ][а-яё\-]{2,}\s+[А-ЯЁ][а-яё\-]{2,}(\s+[А-ЯЁ][а-яё\-]{2,})?$')
# «И.И.Иванов» и «____Р.А.Бочанов» — инициалы с фамилией
NAME_INITIALS = re.compile(r'[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё\-]{2,}')


def is_person(value):
    """ФИО целиком («Иванов Иван») — по таким строкам определяется область данных."""
    if not isinstance(value, str):
        return False
    return bool(NAME_FULL.match(' '.join(value.split())))


def has_person(value):
    """ФИО или фамилия с инициалами («____Р.А.Бочанов») — такие ячейки вычищаем."""
    if not isinstance(value, str):
        return False
    text = ' '.join(value.split())
    return bool(NAME_FULL.match(text) or NAME_INITIALS.search(text))


def clear_rows(ws, first_row, last_row):
    """Очищает значения строк (оформление и объединения остаются)."""
    cleared = 0
    for row in ws.iter_rows(min_row=first_row, max_row=last_row):
        for cell in row:
            if cell.value is None:
                continue
            try:
                cell.value = None
                cleared += 1
            except AttributeError:
                pass          # MergedCell
    return cleared


def clean_workbook(src, dst):
    shutil.copy2(src, dst)
    wb = load_workbook(dst)
    report = []
    for ws in wb.worksheets:
        name_rows = []
        for row in ws.iter_rows():
            for cell in row:
                if is_person(cell.value):
                    name_rows.append(cell.row)
                    break
        if name_rows:
            # шапку (первые строки формы) не трогаем, даже если в ней есть ФИО
            start = max(5, min(name_rows))
            end = max(name_rows)
            cleared = clear_rows(ws, start, end)
            # одиночные ФИО выше области данных — точечно
            for row in ws.iter_rows(min_row=1, max_row=start - 1):
                for cell in row:
                    if is_person(cell.value):
                        cell.value = None
                        cleared += 1
            report.append(f'{ws.title}: очищено {cleared} значений в строках {start}–{end}')
        # фамилии с инициалами в шапке и подписях — оставляем только подчёркивания
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and has_person(cell.value):
                    text = cell.value
                    cell.value = re.sub(NAME_INITIALS, '', text).replace('  ', ' ').strip(' ,')
                    if not cell.value:
                        cell.value = re.sub(r'[^_]', '', text) or None
    wb.save(dst)
    return report


def verify(path):
    """Возвращает список оставшихся ФИО (должен быть пустым)."""
    left = []
    wb = load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for value in row:
                if has_person(value):
                    left.append(f'{ws.title}: {value[:40]}')
    return left


def make_empty_db(path):
    if os.path.exists(path):
        os.remove(path)
    engine = create_engine(f'sqlite:///{path}')
    models.Base.metadata.create_all(engine)
    engine.dispose()


def main():
    os.makedirs(SAMPLES, exist_ok=True)
    tasks = [
        (r'ГРАФИК_ФОРМА A3.xlsx', r'ГРАФИК_ФОРМА A3.xlsx'),
        (r'backend\табель.xlsx', r'табель.xlsx'),
        (r'план-факт август2026.xlsx', r'план-факт август2026.xlsx'),
    ]

    problems = []
    for src_rel, dst_name in tasks:
        src = os.path.join(ROOT, src_rel)
        dst = os.path.join(SAMPLES, dst_name)
        if not os.path.exists(src):
            print(f'[пропуск] нет файла {src_rel}')
            continue
        report = clean_workbook(src, dst)
        left = verify(dst)
        print(f'[ок] {dst_name}')
        for line in report:
            print(f'      {line}')
        if left:
            problems.append((dst_name, left))
            print(f'      ОСТАЛИСЬ ФИО: {left[:3]}')
        else:
            print('      проверка: ФИО не осталось')

    db_sample = os.path.join(SAMPLES, 'plan_fact.db')
    make_empty_db(db_sample)
    print(f'[ок] plan_fact.db — пустая база со схемой '
          f'({os.path.getsize(db_sample)} байт)')

    # заодно проверяем формы, которые уходят в репозиторий как есть
    for rel in (r'Приложение Б.docx', r'backend\Питание.xlsx'):
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f'[пропуск] нет файла {rel}')
            continue
        if rel.endswith('.docx'):
            from docx import Document
            text = '\n'.join(p.text for p in Document(path).paragraphs)
            text += '\n'.join(c.text for t in Document(path).tables for r in t.rows for c in r.cells)
            found = NAME_INITIALS.findall(text) or [v for v in text.split('\n') if NAME_FULL.match(v.strip())]
            print(f'[проверка] {rel}: {"ФИО ЕСТЬ — " + str(found[:3]) if found else "ФИО нет"}')
        else:
            left = verify(path)
            print(f'[проверка] {rel}: {"ФИО ЕСТЬ — " + str(left[:3]) if left else "ФИО нет"}')

    if problems:
        print('\nВНИМАНИЕ: в пустых копиях остались ФИО:')
        for name, left in problems:
            print(f'  {name}: {left[:5]}')
        sys.exit(1)
    print('\nготово: пустые копии в samples/, ФИО в них нет')


if __name__ == '__main__':
    main()
