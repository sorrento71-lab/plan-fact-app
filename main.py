import openpyxl
import os
import sys

def get_file_path(prompt, default=None):
    """Запрашивает путь к файлу, проверяет существование и возвращает абсолютный путь."""
    while True:
        path = input(prompt).strip()
        if not path and default:
            path = default
        if path:
            if os.path.exists(path):
                return os.path.abspath(path)
            else:
                print(f"❌ Файл не найден: {path}. Попробуйте снова.")
        else:
            print("❌ Путь не может быть пустым. Попробуйте снова.")

def main():
    print("🔄 Конвертер табеля: из упрощённой формы (5) в полную Т-13\n")

    # Запрашиваем пути
    default_source = "Табель_Август_2026 (5).xlsx"
    default_template = "табель.xlsx"
    default_output = "Табель_преобразованный.xlsx"

    source_path = get_file_path(
        f"📂 Введите путь к исходному файлу (упрощённая форма) [по умолчанию: {default_source}]: ",
        default_source
    )

    template_path = get_file_path(
        f"📂 Введите путь к файлу-шаблону (полная форма Т-13) [по умолчанию: {default_template}]: ",
        default_template
    )

    output_path = input(f"💾 Введите имя выходного файла [по умолчанию: {default_output}]: ").strip()
    if not output_path:
        output_path = default_output
    if not output_path.endswith('.xlsx'):
        output_path += '.xlsx'

    print("\n⏳ Загрузка файлов...")

    try:
        # Открываем исходный файл
        src_wb = openpyxl.load_workbook(source_path)
        src_ws = src_wb.active
        print(f"✅ Исходный файл загружен: {source_path}")

        # Открываем шаблон
        tpl_wb = openpyxl.load_workbook(template_path)
        tpl_ws = tpl_wb.active
        print(f"✅ Шаблон загружен: {template_path}")

    except Exception as e:
        print(f"❌ Ошибка загрузки файлов: {e}")
        sys.exit(1)

    # Параметры структуры
    src_start_row = 21           # первая строка с данными в исходном файле
    src_rows_per_emp = 3         # строки на сотрудника: явки, часы, пустая
    tpl_start_row = 24           # первая строка для данных в шаблоне
    tpl_rows_per_emp = 4         # строки на сотрудника в полной форме

    emp_index = 0
    row = src_start_row

    print("\n⏳ Обработка данных...")

    while row <= src_ws.max_row:
        # Проверяем, что строка содержит данные (не пустая)
        if src_ws.cell(row, 1).value is None:
            row += 1
            continue

        # Чтение данных
        order = src_ws.cell(row, 1).value
        full_name = src_ws.cell(row, 2).value
        tab_num = src_ws.cell(row, 3).value

        # Проверяем, что есть имя (чтобы не обрабатывать случайные строки)
        if not full_name:
            row += 1
            continue

        # Явки 1-15 (строки row, колонки D=4 .. R=18)
        att_1_15 = [src_ws.cell(row, col).value for col in range(4, 19)]
        # Часы 1-15 (строка row+1, колонки D:R)
        hours_1_15 = [src_ws.cell(row+1, col).value for col in range(4, 19)]

        # Явки 16-31 (строка row, колонки T=20 .. AI=35) – в (5) именно так
        att_16_31 = [src_ws.cell(row, col).value for col in range(20, 36)]
        # Часы 16-31 (строка row+1, колонки T:AI)
        hours_16_31 = [src_ws.cell(row+1, col).value for col in range(20, 36)]

        # Запись в шаблон
        tpl_row = tpl_start_row + emp_index * tpl_rows_per_emp

        # Строка 1: №, ФИО, Таб.№ + явки 1-15
        tpl_ws.cell(tpl_row, 1).value = order
        tpl_ws.cell(tpl_row, 2).value = full_name
        tpl_ws.cell(tpl_row, 3).value = tab_num
        for i, val in enumerate(att_1_15, start=4):
            tpl_ws.cell(tpl_row, i).value = val

        # Строка 2: часы 1-15
        for i, val in enumerate(hours_1_15, start=4):
            tpl_ws.cell(tpl_row+1, i).value = val

        # Строка 3: явки 16-31 (в те же колонки D:R)
        for i, val in enumerate(att_16_31, start=4):
            tpl_ws.cell(tpl_row+2, i).value = val

        # Строка 4: часы 16-31 (в те же колонки D:R)
        for i, val in enumerate(hours_16_31, start=4):
            tpl_ws.cell(tpl_row+3, i).value = val

        # Итоговые колонки T:Y (20-25) оставляем пустыми – формулы сами посчитают
        # Блоки зарплаты и неявок не трогаем

        emp_index += 1
        row += src_rows_per_emp

    # Сохраняем результат
    try:
        tpl_wb.save(output_path)
        print(f"\n✅ Готово! Преобразовано {emp_index} сотрудников.")
        print(f"📁 Результат сохранён в: {os.path.abspath(output_path)}")
    except Exception as e:
        print(f"❌ Ошибка сохранения файла: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()