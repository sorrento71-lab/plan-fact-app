// Общие константы и утилиты План-Факт

export const STATUS_COLORS = {
    'Совпадает': '#92d050',
    'Неполный день': '#ffff00',
    'Отсутствует': '#ff6b6b',
    'Неучтенная работа': '#ffa94d',
    'Явка в выходной': '#ffa94d',
    'Выходной': '#add8e6',
    'Нет данных': '#ffffff',
};

export const WEEK_LABELS = ['с 1 по 7', 'с 8 по 14', 'с 15 по 21', 'с 22 по 28', 'с 29 по 31'];

// Короткие подписи недель для компактной панели
export const WEEK_LABELS_SHORT = ['1–7', '8–14', '15–21', '22–28', '29–31'];

export const DAY_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

// Смена схемы обозначений смен. До ноября 2026 смена кодировалась длительностью
// (11 — 2 через 2, 9 и 8 — 5 через 2, доп. смена — «Д»), с ноября 2026 —
// «Я» основная смена и «В» доп смена. Бэкенд живёт по тем же правилам
// (backend/shift_codes.py), здесь — только подписи интерфейса.
export const SHIFT_SCHEME = {
    startYear: 2026,
    startMonth: 11,      // с какого месяца (1–12) действует схема «Я»/«В»
    main: 'Я',
    extra: 'В',
};

// true, если для месяца (month: 1–12) действует схема «Я»/«В»
export const usesNewShiftScheme = (year, month) => {
    const y = Number(year);
    const m = Number(month);
    if (!y || !m) return false;
    return y > SHIFT_SCHEME.startYear
        || (y === SHIFT_SCHEME.startYear && m >= SHIFT_SCHEME.startMonth);
};

// Пояснения к сменам месяца: с ноября 2026 — «Я»/«В», раньше — по длительности
export const shiftLegend = (year, month) => (usesNewShiftScheme(year, month)
    ? [
        { code: 'Я', text: 'основная смена', color: null },
        { code: 'В', text: 'доп смена', color: '#FFFF00' },
    ]
    : [
        { code: 'Д', text: 'дежурство', color: '#FFFF00' },
    ]);


export const MONTH_NAMES = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];

// Список доступных месяцев: последние 3 и будущие 3 относительно текущего
export const getMonths = () => {
    const months = [];
    const currentDate = new Date();
    const currentYear = currentDate.getFullYear();
    const currentMonth = currentDate.getMonth();

    for (let i = -3; i <= 3; i++) {
        let month = currentMonth + i;
        let year = currentYear;
        if (month < 0) {
            month += 12;
            year--;
        } else if (month > 11) {
            month -= 12;
            year++;
        }
        months.push({
            year: year,
            month: month,
            label: `${String(month + 1).padStart(2, '0')}.${year}`
        });
    }
    return months;
};
