import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import { usesNewShiftScheme, shiftLegend } from '../constants';

// Вкладка «График»: таблица формы А3 в исходных цветах и структуре,
// с редактированием ячеек и сравнением с планом из базы данных.
const CMP_MARK = {
    diff: { boxShadow: 'inset 0 0 0 2px #d32f2f' },
    db_missing: { boxShadow: 'inset 0 0 0 2px #ff9800' },
    graf_missing: { boxShadow: 'inset 0 0 0 2px #1976d2' },
    no_employee: { boxShadow: 'inset 0 0 0 2px #9e9e9e' },
};

// Закреплённые колонки: 1 — участок, 2 — ФИО, 3 — должность
const COL_WIDTH = { 1: 104, 2: 164, 3: 116 };
const COL_LEFT = { 1: 0, 2: 104, 3: 268 };
// Служебные текстовые колонки (например «Изменения в графике»)
const EXTRA_COL_WIDTH = 150;

// Подсказки для редактируемых данных сотрудника
const EF_TITLE = {
    name: 'Кликните, чтобы изменить ФИО (Enter — сохранить, Esc — отмена)',
    position: 'Кликните, чтобы изменить должность',
    section: 'Кликните, чтобы изменить участок (для всей группы строк)'
};

function ScheduleView({ year, month, refreshToken, onPlanChanged }) {
    // С ноября 2026 смены обозначаются «Я» (основная) и «В» (доп смена)
    const newShiftScheme = usesNewShiftScheme(year, month + 1);
    const shiftCodes = shiftLegend(year, month + 1);
    const shiftCodesText = shiftCodes.map((item) => item.code).join('/');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [message, setMessage] = useState('');

    const [editing, setEditing] = useState(null);   // {r, c}
    const [editValue, setEditValue] = useState('');
    const [saving, setSaving] = useState(false);

    const [newEmp, setNewEmp] = useState({ name: '', position: '', section: '' });

    // Выбранная строка: {row, name}. Храним и номер строки, и ФИО —
    // иначе при одинаковых ФИО действия попадают не в ту строку
    const [selected, setSelected] = useState(null);

    // Окно подтверждения очистки: вопрос ждёт ответа 5 секунд
    const [clearAsk, setClearAsk] = useState(null);      // {plans, employees, notes}
    const [clearLeft, setClearLeft] = useState(0);       // секунд до автоотмены
    const [clearing, setClearing] = useState(false);

    // Окно создания листа за месяц
    const [createAsk, setCreateAsk] = useState(false);
    const [creating, setCreating] = useState(false);

    // Окно расстановки смен
    const [shiftAsk, setShiftAsk] = useState(null);
    const [shifting, setShifting] = useState(false);

    // Окно удаления сотрудника из графика
    const [deleteAsk, setDeleteAsk] = useState(false);
    const [deleting, setDeleting] = useState(false);

    // Загрузка файла графика прямо с этой страницы
    const [uploading, setUploading] = useState(false);

    // Выгрузка формы (actual — как есть, rhythm — только смены месяца по ритму)
    const [exporting, setExporting] = useState(null);

    const CLEAR_TIMEOUT = 5;

    // Защита от двойного сохранения: Enter сохраняет и снимает фокус,
    // поэтому blur после него уже не должен писать второй раз
    const handledRef = useRef(false);

    const load = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await axios.get(`${API_URL}/schedule/grid/`, {
                params: { year, month: month + 1 }
            });
            setData(response.data);
            // выделение держим по строке: если строки больше нет — снимаем,
            // если ФИО в строке изменилось — обновляем подпись
            setSelected((prev) => {
                if (!prev) return prev;
                const emp = response.data.employee_rows?.[String(prev.row)];
                if (!emp) return null;
                return emp.name === prev.name ? prev : { row: prev.row, name: emp.name };
            });
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
        setLoading(false);
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [year, month, refreshToken]);

    // Обратный отсчёт в окне очистки: без ответа за 5 секунд вопрос отменяется
    useEffect(() => {
        if (!clearAsk) return undefined;
        const timer = setInterval(() => {
            setClearLeft((left) => (left > 0 ? left - 1 : 0));
        }, 1000);
        return () => clearInterval(timer);
    }, [clearAsk]);

    // время на ответ вышло — вопрос снимается сам
    useEffect(() => {
        if (clearAsk && clearLeft === 0) setClearAsk(null);
    }, [clearLeft, clearAsk]);

    const showMessage = (text) => {
        setMessage(text);
        setTimeout(() => setMessage(''), 4000);
    };

    const saveCell = async (r, c, value, field) => {
        setSaving(true);
        try {
            // ФИО / должность / участок — отдельный эндпоинт (данные сотрудника)
            const response = field
                ? await axios.post(`${API_URL}/schedule/employee/update/`, {
                    row: r, field, value, year, month: month + 1
                })
                : await axios.post(`${API_URL}/schedule/cell/`, {
                    row: r, col: c, value, year, month: month + 1
                });
            showMessage(`✅ ${response.data.message}`);
            await load();
            if (onPlanChanged) onPlanChanged();   // обновить План-Факт
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setSaving(false);
        setEditing(null);
        setEditValue('');
    };

    // Списки для выпадающих полей: участки (колонка 1) и должности (колонка 3)
    // берём из самого графика, чтобы значения совпадали с файлом
    const gridOptions = (column) => {
        if (!data || !data.cells) return [];
        const values = data.cells
            .filter((cell) => cell.c === column && cell.v)
            .map((cell) => String(cell.v).trim())
            .filter(Boolean);
        return [...new Set(values)].sort((a, b) => a.localeCompare(b, 'ru'));
    };

    const addEmployee = async () => {
        if (!newEmp.name.trim()) {
            showMessage('❌ Укажите ФИО сотрудника');
            return;
        }
        setSaving(true);
        try {
            const response = await axios.post(`${API_URL}/schedule/employee/`, {
                name: newEmp.name.trim(),
                position: newEmp.position.trim(),
                section: newEmp.section.trim(),
                year, month: month + 1
            });
            showMessage(`✅ ${response.data.message}`);
            setNewEmp({ name: '', position: '', section: '' });
            await load();
            if (onPlanChanged) onPlanChanged();   // новый сотрудник сразу в План-Факте
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setSaving(false);
    };

    // --- Очистка плана за месяц с уточняющим вопросом ---
    const askClear = async () => {
        setClearing(true);
        try {
            const response = await axios.get(`${API_URL}/schedule/clear/summary/`, {
                params: { year, month: month + 1 }
            });
            setClearAsk(response.data);
            setClearLeft(CLEAR_TIMEOUT);
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setClearing(false);
    };

    const cancelClear = () => {
        setClearAsk(null);
        setClearLeft(0);
    };

    const confirmClear = async () => {
        setClearAsk(null);
        setClearLeft(0);
        setClearing(true);
        try {
            const response = await axios.post(`${API_URL}/schedule/clear/`, null, {
                params: { year, month: month + 1, clear_shifts: true, clear_plan: true, clear_notes: true }
            });
            showMessage(`✅ ${response.data.message}`);
            await load();
            if (onPlanChanged) onPlanChanged();   // план очищен — обновить План-Факт
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setClearing(false);
    };

    // --- Создание листа за выбранный месяц ---
    const confirmCreateSheet = async () => {
        setCreateAsk(false);
        setCreating(true);
        try {
            const response = await axios.post(`${API_URL}/schedule/create-sheet/`, null, {
                params: { year, month: month + 1 }
            });
            showMessage(`✅ ${response.data.message}`);
            await load();
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setCreating(false);
    };

    // --- Расстановка смен по ритму: код берётся из схемы месяца
    //     (до ноября 2026 — 11 — 2 через 2, 8 и 9 — 5 через 2;
    //      с ноября 2026 — «Я» основная смена, ритм подбирается по рисунку) ---
    const askShifts = async () => {
        setShifting(true);
        try {
            const response = await axios.get(`${API_URL}/schedule/shifts/summary/`, {
                params: { year, month: month + 1 }
            });
            setShiftAsk(response.data);
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setShifting(false);
    };

    const confirmShifts = async () => {
        setShiftAsk(null);
        setShifting(true);
        try {
            const response = await axios.post(`${API_URL}/schedule/shifts/fill/`, null, {
                params: { year, month: month + 1 }
            });
            showMessage(`✅ ${response.data.message}`);
            await load();
            if (onPlanChanged) onPlanChanged();
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setShifting(false);
    };

    // --- Выгрузка формы А3 (шапка утверждения, без колонки «Изменения») ---
    const downloadSchedule = async (mode) => {
        setExporting(mode);
        try {
            const response = await axios.get(`${API_URL}/export/schedule/`, {
                params: { year, month: month + 1, mode },
                responseType: 'blob'
            });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            const mm = String(month + 1).padStart(2, '0');
            link.href = url;
            link.setAttribute('download',
                `График_${mm}.${year}${mode === 'rhythm' ? '_ритмы' : ''}.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
            showMessage(`✅ Выгружено: ${mode === 'rhythm' ? `только ритмы ${shiftCodesText}` : 'график как есть'}`);
        } catch (err) {
            showMessage(`❌ Не удалось выгрузить: ${err.message}`);
        }
        setExporting(null);
    };

    // --- Автоматическая синхронизация: правки плана и смен идут в обе стороны,
    //     отдельные кнопки для переноса не нужны ---

    // --- Загрузка файла графика с этой страницы ---
    const uploadSchedule = async (event) => {
        const file = event.target.files && event.target.files[0];
        event.target.value = '';
        if (!file) return;

        setUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            const response = await axios.post(`${API_URL}/upload/schedule/`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
                // в файлах графика много месяцев: грузим лист того, что открыт в шапке
                params: { year, month: month + 1 }
            });
            showMessage(`✅ ${response.data.message}`);
            await load();
            if (onPlanChanged) onPlanChanged();
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setUploading(false);
    };

    // --- Удаление сотрудника из листа графика ---
    const confirmDeleteEmployee = async (row) => {
        setDeleteAsk(false);
        setDeleting(true);
        try {
            const response = await axios.post(`${API_URL}/schedule/employee/delete/`, {
                row, year, month: month + 1
            });
            showMessage(`✅ ${response.data.message}`);
            setSelected(null);
            await load();
            if (onPlanChanged) onPlanChanged();
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`);
        }
        setDeleting(false);
    };

    if (error) {
        return <div style={{ padding: '30px', textAlign: 'center', color: '#c62828' }}>❌ {error}</div>;
    }
    if (!data) {
        return <div style={{ padding: '30px', textAlign: 'center' }}>🔄 Загрузка графика…</div>;
    }

    // Раскладка: ячейки, объединения
    const cellMap = {};
    data.cells.forEach((c) => { cellMap[`${c.r}:${c.c}`] = c; });

    const mergeAt = {};
    const covered = new Set();
    data.merges.forEach((m) => {
        mergeAt[`${m.r}:${m.c}`] = m;
        for (let r = m.r; r < m.r + m.rows; r++) {
            for (let c = m.c; c < m.c + m.cols; c++) {
                if (!(r === m.r && c === m.c)) covered.add(`${r}:${c}`);
            }
        }
    });

    const dayCols = new Set(data.days.map((d) => d.col));
    // День по колонке: число, буква дня недели и признак выходного
    const dayByCol = {};
    data.days.forEach((d) => { dayByCol[d.col] = d; });
    const weekendFill = data.weekend_fill || '73A0B4';
    const rows = [];
    for (let r = 1; r <= data.max_row; r++) rows.push(r);
    const cols = [];
    for (let c = 1; c <= data.max_col; c++) cols.push(c);

    const stats = data.stats || {};

    // Совпадает ли лист файла с выбранным месяцем
    const wantedSheet = `${String(month + 1).padStart(2, '0')}.${year}`;
    const sheetMatches = String(data.sheet || '').trim() === wantedSheet;

    // Сотрудник строки (только строки с ФИО)
    const employeeAt = (r) => (data.employee_rows ? data.employee_rows[String(r)] : null);

    // Ширина колонки: закреплённые и служебные — фиксированные, дни — растягиваются
    const colWidthFor = (c) => {
        if (COL_WIDTH[c] !== undefined) return COL_WIDTH[c];
        if (dayCols.has(c)) return null;
        return EXTRA_COL_WIDTH;
    };

    // Выделение строки — по ФИО сотрудника, поэтому оно не сбрасывается
    // при перезагрузке данных (сохранение ячейки, добавление сотрудника)
    const selectRow = (r) => {
        const emp = employeeAt(r);
        if (emp) setSelected({ row: r, name: emp.name });
    };

    const startEdit = (r, c, value) => {
        if (saving) return;
        handledRef.current = false;
        setEditing({ r, c });
        setEditValue(value || '');
    };

    const onKeyDown = (e, r, c, field) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handledRef.current = true;
            saveCell(r, c, editValue, field);
        } else if (e.key === 'Escape') {
            handledRef.current = true;
            setEditing(null);
            setEditValue('');
        }
    };

    const onBlur = (r, c, field) => {
        if (handledRef.current) {
            handledRef.current = false;
            return;
        }
        saveCell(r, c, editValue, field);
    };

    // Цвет фона ячейки: цвет значения, иначе — подсветка выходного дня.
    // Выходной определяется календарём выбранного месяца, а не файлом.
    const cellBackground = (cell, day) => {
        if (cell.fill) return `#${cell.fill}`;
        if (day && day.weekend) return `#${weekendFill}`;
        return 'transparent';
    };

    const cellStyle = (cell, m, day) => {
        const style = {
            padding: '1px 3px',
            fontSize: '10px',
            lineHeight: 1.25,
            whiteSpace: 'nowrap',
            textAlign: 'center',
            verticalAlign: 'middle',
            backgroundColor: cellBackground(cell, day),
            color: cell.fc ? `#${cell.fc}` : '#222',
            fontWeight: cell.b || cell.v ? 'bold' : 'normal',
            fontStyle: cell.i ? 'italic' : 'normal',
            // Сотрудника нет в базе (или строка пустая) — ячейки без обрамления
            border: (() => {
                const rowInfo = employeeAt(cell.r);
                if (!rowInfo) return 'none';
                const rowName = (rowInfo.name || '').trim();
                if (!rowName || !rowInfo.in_db) return 'none';
                return '1px solid #e7eaee';
            })(),
        };
        if (cell.cmp && CMP_MARK[cell.cmp]) Object.assign(style, CMP_MARK[cell.cmp]);
        if (cell.editable) style.cursor = 'pointer';
        if (m && m.rows > 1) style.height = `${m.rows * 18}px`;
        return style;
    };

    const cellTitle = (cell) => {
        const hints = [];
        if (cell.ef) hints.push(EF_TITLE[cell.ef] || 'Кликните, чтобы изменить');
        else if (cell.editable) hints.push('Кликните для редактирования');
        if (cell.cmp === 'diff') hints.push(`График «${cell.v || '—'}» ≠ база «${cell.db || '—'}»`);
        else if (cell.cmp === 'db_missing') hints.push(`В графике «${cell.v}», в базе плана нет`);
        else if (cell.cmp === 'graf_missing') hints.push(`В базе «${cell.db}», в графике пусто`);
        else if (cell.cmp === 'no_employee') hints.push('Сотрудника нет в базе');
        return hints.join(' · ') || undefined;
    };

    const inputStyle = {
        width: '100%',
        border: 'none',
        background: 'transparent',
        textAlign: 'center',
        fontSize: 'inherit',
        fontWeight: 'bold',
        outline: 'none'
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', flex: 1, overflow: 'hidden' }}>
            {/* Панель инструментов */}
            <div style={{
                display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px 12px',
                flexShrink: 0, padding: '4px 10px', marginBottom: '4px',
                background: '#fafbfc', border: '1px solid #dfe4ea', borderRadius: '6px',
                fontSize: '11px', color: '#555'
            }}>
                <span>📅 График: <b>«{data.sheet}»</b></span>
                {!sheetMatches && (
                    <>
                        <span style={{ color: '#c62828', fontWeight: 'bold' }}
                              title={`В файле графика нет листа за ${wantedSheet}, поэтому показан лист «${data.sheet}» — данные в ячейках относятся к другому месяцу.`}>
                            ⚠️ листа за {wantedSheet} нет — показан «{data.sheet}»
                        </span>
                        <button
                            onClick={() => setCreateAsk(true)}
                            disabled={creating}
                            title={`Создать в файле графика пустой лист за ${wantedSheet}: та же форма, сотрудники и участки, дни ${data.month_days}, смены пустые`}
                            style={{
                                padding: '2px 10px', fontSize: '11px', fontWeight: 'bold',
                                background: creating ? '#ccc' : '#2e7d32', color: '#fff',
                                border: 'none', borderRadius: '4px',
                                cursor: creating ? 'not-allowed' : 'pointer'
                            }}
                        >
                            📄 Создать лист за {wantedSheet}
                        </button>
                    </>
                )}
                {sheetMatches && data.month_days > 0 && data.days_in_file < data.month_days && (
                    <span style={{ color: '#ef6c00' }}
                          title={`В файле ${data.days_in_file} колонок-дней, в выбранном месяце ${data.month_days}. Колонки для последних дней нужно добавить в файл графика.`}>
                        ⚠️ дней в файле: {data.days_in_file} из {data.month_days}
                    </span>
                )}
                <span style={{ width: 1, height: 18, background: '#d7dde4' }} />
                <span>Расхождений: <b style={{ color: stats.diff ? '#c62828' : '#2e7d32' }}>{stats.diff || 0}</b></span>
                <span>Нет плана в БД: <b style={{ color: '#ef6c00' }}>{stats.db_missing || 0}</b></span>
                <span>Совпадает: <b style={{ color: '#2e7d32' }}>{stats.ok || 0}</b></span>
                {loading && <span style={{ color: '#1565c0' }}>⏳ обновление…</span>}
                <label
                    title={`Загрузить график смен из файла Excel (форма А3). Будет взят лист за выбранный месяц — ${String(month + 1).padStart(2, '0')}.${year}; данные сразу попадут в лист графика и в план`}
                    style={{
                        marginLeft: 'auto', padding: '2px 10px', fontSize: '11px', fontWeight: 'bold',
                        background: uploading ? '#ccc' : '#2e7d32', color: '#fff',
                        borderRadius: '4px', display: 'inline-block', whiteSpace: 'nowrap',
                        cursor: uploading ? 'not-allowed' : 'pointer'
                    }}
                >
                    📤 Загрузить график
                    <input
                        type="file"
                        accept=".xlsx,.xls"
                        onChange={uploadSchedule}
                        disabled={uploading}
                        style={{ display: 'none' }}
                    />
                </label>
                <button
                    onClick={() => setDeleteAsk(true)}
                    disabled={!selected || deleting}
                    title={selected
                        ? `Удалить строку «${selected.name}» из листа графика (план и факты в базе останутся)`
                        : 'Сначала выберите строку сотрудника — кликните по ней в таблице'}
                    style={{
                        marginLeft: 'auto', padding: '2px 10px', fontSize: '11px', fontWeight: 'bold',
                        background: (!selected || deleting) ? '#ccc' : '#b71c1c', color: '#fff',
                        border: 'none', borderRadius: '4px',
                        cursor: (!selected || deleting) ? 'not-allowed' : 'pointer'
                    }}
                >
                    🗑️ Удалить из графика
                </button>
                <button
                    onClick={() => downloadSchedule('actual')}
                    disabled={!!exporting}
                    title="Выгрузить форму А3 с данными как есть (шапка утверждения, без колонки «Изменения в графике»)"
                    style={{
                        padding: '2px 10px', fontSize: '11px', fontWeight: 'bold',
                        background: exporting ? '#ccc' : '#00695c', color: '#fff',
                        border: 'none', borderRadius: '4px',
                        cursor: exporting ? 'not-allowed' : 'pointer'
                    }}
                >
                    📥 Как есть
                </button>
                <button
                    onClick={() => downloadSchedule('rhythm')}
                    disabled={!!exporting}
                    title={newShiftScheme
                        ? 'Выгрузить форму А3 только со сменами Я (основная) и В (доп) по ритму: 2 через 2 или 5 через 2 — по рисунку месяца'
                        : 'Выгрузить форму А3 только со сменами 11, 9, 8 по ритму (2 через 2 и 5 через 2)'}
                    style={{
                        padding: '2px 10px', fontSize: '11px', fontWeight: 'bold',
                        background: exporting ? '#ccc' : '#5e35b1', color: '#fff',
                        border: 'none', borderRadius: '4px',
                        cursor: exporting ? 'not-allowed' : 'pointer'
                    }}
                >
                    📥 Только ритмы
                </button>
                <button
                    onClick={askShifts}
                    disabled={shifting}
                    title={newShiftScheme
                        ? 'Расставить смены за выбранный месяц по ритму из графика: Я — основная смена, В — доп смена (заполняются только пустые дни)'
                        : 'Расставить смены за выбранный месяц по ритму из графика: 11 — 2 через 2, 9 и 8 — 5 через 2 (заполняются только пустые дни)'}
                    style={{
                        padding: '2px 10px', fontSize: '11px', fontWeight: 'bold',
                        background: shifting ? '#ccc' : '#0277bd', color: '#fff',
                        border: 'none', borderRadius: '4px',
                        cursor: shifting ? 'not-allowed' : 'pointer'
                    }}
                >
                    ⚙️ Расставить смены
                </button>
                <button
                    onClick={askClear}
                    disabled={clearing}
                    title="Очистить смены за выбранный месяц, план в базе и примечания (сотрудники и оформление останутся)"
                    style={{
                        padding: '2px 10px', fontSize: '11px',
                        background: clearing ? '#ccc' : '#c62828', color: '#fff',
                        border: 'none', borderRadius: '4px',
                        cursor: clearing ? 'not-allowed' : 'pointer', fontWeight: 'bold'
                    }}
                >
                    🧹 Очистить
                </button>
            </div>

            {/* Добавление сотрудника */}
            <div style={{
                display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px',
                flexShrink: 0, padding: '4px 10px', marginBottom: '4px',
                background: '#f2f7ff', border: '1px solid #cfe0f5', borderRadius: '6px', fontSize: '11px'
            }}>
                <span style={{ color: '#1565c0', fontWeight: 'bold' }}>➕ Новый сотрудник:</span>
                <input
                    placeholder="ФИО"
                    value={newEmp.name}
                    onChange={(e) => setNewEmp({ ...newEmp, name: e.target.value })}
                    style={{ padding: '3px 6px', border: '1px solid #c6cdd6', borderRadius: '3px', fontSize: '11px', width: '180px' }}
                />
                <select
                    value={newEmp.position}
                    onChange={(e) => setNewEmp({ ...newEmp, position: e.target.value })}
                    title="Должность — выберите из списка"
                    style={{ padding: '3px 6px', border: '1px solid #c6cdd6', borderRadius: '3px', fontSize: '11px', width: '160px' }}
                >
                    <option value="">Должность…</option>
                    {gridOptions(3).map((value) => (
                        <option key={value} value={value}>{value}</option>
                    ))}
                </select>
                <select
                    value={newEmp.section}
                    onChange={(e) => setNewEmp({ ...newEmp, section: e.target.value })}
                    title="Участок — сотрудник встанет в конец этого участка"
                    style={{ padding: '3px 6px', border: '1px solid #c6cdd6', borderRadius: '3px', fontSize: '11px', width: '180px' }}
                >
                    <option value="">Участок…</option>
                    {gridOptions(1).map((value) => (
                        <option key={value} value={value}>{value}</option>
                    ))}
                </select>
                <button
                    onClick={addEmployee}
                    disabled={saving}
                    style={{
                        padding: '3px 12px', background: saving ? '#ccc' : '#2e7d32', color: '#fff',
                        border: 'none', borderRadius: '4px', cursor: saving ? 'not-allowed' : 'pointer',
                        fontSize: '11px', fontWeight: 'bold'
                    }}
                >
                    ➕ Добавить в график и базу
                </button>
            </div>

            {message && (
                <div style={{
                    padding: '3px 10px', marginBottom: '4px', flexShrink: 0,
                    background: message.startsWith('✅') ? '#d4edda' : message.startsWith('❌') ? '#f8d7da' : '#fff3cd',
                    color: message.startsWith('✅') ? '#155724' : message.startsWith('❌') ? '#721c24' : '#856404',
                    borderRadius: '3px', fontSize: '11px'
                }}>
                    {message}
                </div>
            )}

            {/* Уточняющий вопрос перед удалением сотрудника из графика */}
            {deleteAsk && selected && (
                <div style={{
                    position: 'fixed', inset: 0, zIndex: 1000,
                    background: 'rgba(0,0,0,0.45)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                    <div style={{
                        width: '520px', maxWidth: '92vw', background: '#fff',
                        border: '2px solid #b71c1c', borderRadius: '8px',
                        padding: '16px 18px', boxShadow: '0 8px 30px rgba(0,0,0,0.35)'
                    }}>
                        <div style={{ fontSize: '15px', fontWeight: 'bold', color: '#b71c1c', marginBottom: '10px' }}>
                            🗑️ Удалить «{selected.name}» из графика {data.sheet}?
                        </div>
                        <div style={{ fontSize: '12px', color: '#333', lineHeight: 1.6 }}>
                            <div>• строка сотрудника будет удалена из листа <b>«{data.sheet}»</b>,
                                остальные строки сдвинутся вверх</div>
                            <div>• если он был в группе участка, объединение сохранится и название участка не потеряется</div>
                            <div style={{ marginTop: '8px', color: '#666' }}>
                                Сотрудник и его план в базе <b>останутся</b> — в План-Факте ничего не изменится.
                                Если нужно убрать и план, воспользуйтесь кнопкой «🗑️ Удалить (неделя)» на странице План-Факт.
                            </div>
                        </div>
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '10px',
                            marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #eee'
                        }}>
                            <button
                                onClick={() => confirmDeleteEmployee(selected.row)}
                                style={{
                                    padding: '7px 16px', background: '#b71c1c', color: '#fff',
                                    border: 'none', borderRadius: '4px', cursor: 'pointer',
                                    fontSize: '12px', fontWeight: 'bold'
                                }}
                            >
                                Да, удалить из графика
                            </button>
                            <button
                                onClick={() => setDeleteAsk(false)}
                                style={{
                                    padding: '7px 16px', background: '#f0f0f0', color: '#333',
                                    border: '1px solid #ccc', borderRadius: '4px',
                                    cursor: 'pointer', fontSize: '12px'
                                }}
                            >
                                Отмена
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Уточняющий вопрос перед расстановкой смен */}
            {shiftAsk && (
                <div style={{
                    position: 'fixed', inset: 0, zIndex: 1000,
                    background: 'rgba(0,0,0,0.45)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                    <div style={{
                        width: '560px', maxWidth: '92vw', background: '#fff',
                        border: '2px solid #0277bd', borderRadius: '8px',
                        padding: '16px 18px', boxShadow: '0 8px 30px rgba(0,0,0,0.35)'
                    }}>
                        <div style={{ fontSize: '15px', fontWeight: 'bold', color: '#0277bd', marginBottom: '10px' }}>
                            ⚙️ Расставить смены за {shiftAsk.target}?
                        </div>
                        <div style={{ fontSize: '12px', color: '#333', lineHeight: 1.6 }}>
                            <div>• ритм взят из листа <b>«{shiftAsk.source}»</b>:
                                {newShiftScheme
                                    ? <> <b>Я</b> — основная смена, ритм 2 через 2 или 5 через 2
                                        подбирается по рисунку месяца (у каждого свой сдвиг)</>
                                    : <> <b>11</b> — 2 через 2, <b>9</b> и <b>8</b> — 5 через 2
                                        (у каждого свой сдвиг)</>}</div>
                            <div>• будет заполнено <b>{shiftAsk.filled}</b> дней у <b>{shiftAsk.employees}</b> сотрудников:
                                {' '}{(shiftAsk.shift_codes && shiftAsk.shift_codes.length
                                    ? shiftAsk.shift_codes
                                    : shiftCodes
                                ).map((item) => `${item.code} — ${(shiftAsk.by_value || {})[item.code] || 0}`)
                                    .join(', ')}</div>
                            <div>• заполняются <b>только пустые дни</b>: уже проставленные смены, отпуска
                                и больничные не меняются</div>
                            <div>• смены сразу попадут в план базы и появятся в План-Факте</div>
                            {shiftAsk.skipped && shiftAsk.skipped.length > 0 && (
                                <div style={{ marginTop: '8px', color: '#ef6c00' }}>
                                    Пропущены (нет смен в «{shiftAsk.source}»): {shiftAsk.skipped.join(', ')}
                                </div>
                            )}
                        </div>
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '10px',
                            marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #eee'
                        }}>
                            <button
                                onClick={confirmShifts}
                                disabled={!shiftAsk.filled}
                                style={{
                                    padding: '7px 16px',
                                    background: shiftAsk.filled ? '#0277bd' : '#ccc', color: '#fff',
                                    border: 'none', borderRadius: '4px',
                                    cursor: shiftAsk.filled ? 'pointer' : 'not-allowed',
                                    fontSize: '12px', fontWeight: 'bold'
                                }}
                            >
                                Да, расставить
                            </button>
                            <button
                                onClick={() => setShiftAsk(null)}
                                style={{
                                    padding: '7px 16px', background: '#f0f0f0', color: '#333',
                                    border: '1px solid #ccc', borderRadius: '4px',
                                    cursor: 'pointer', fontSize: '12px'
                                }}
                            >
                                Отмена
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Уточняющий вопрос перед созданием листа за месяц */}
            {createAsk && (
                <div style={{
                    position: 'fixed', inset: 0, zIndex: 1000,
                    background: 'rgba(0,0,0,0.45)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                    <div style={{
                        width: '520px', maxWidth: '92vw', background: '#fff',
                        border: '2px solid #2e7d32', borderRadius: '8px',
                        padding: '16px 18px', boxShadow: '0 8px 30px rgba(0,0,0,0.35)'
                    }}>
                        <div style={{ fontSize: '15px', fontWeight: 'bold', color: '#2e7d32', marginBottom: '10px' }}>
                            📄 Создать лист за {wantedSheet}?
                        </div>
                        <div style={{ fontSize: '12px', color: '#333', lineHeight: 1.6 }}>
                            <div>• будет добавлен лист <b>«{wantedSheet}»</b> в файл графика: дней <b>{data.month_days}</b></div>
                            <div>• форма, сотрудники, участки, должности и параметры печати копируются с листа «{data.sheet}»</div>
                            <div>• смены и примечания в новом листе будут пустыми, буквы дней и выходные — по календарю ({wantedSheet})</div>
                            <div style={{ marginTop: '8px', color: '#666' }}>
                                Лист «{data.sheet}» и его данные не изменяются.
                            </div>
                        </div>
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '10px',
                            marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #eee'
                        }}>
                            <button
                                onClick={confirmCreateSheet}
                                style={{
                                    padding: '7px 16px', background: '#2e7d32', color: '#fff',
                                    border: 'none', borderRadius: '4px', cursor: 'pointer',
                                    fontSize: '12px', fontWeight: 'bold'
                                }}
                            >
                                Да, создать
                            </button>
                            <button
                                onClick={() => setCreateAsk(false)}
                                style={{
                                    padding: '7px 16px', background: '#f0f0f0', color: '#333',
                                    border: '1px solid #ccc', borderRadius: '4px',
                                    cursor: 'pointer', fontSize: '12px'
                                }}
                            >
                                Отмена
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Уточняющий вопрос перед очисткой: без ответа за 5 секунд отменяется */}
            {clearAsk && (
                <div style={{
                    position: 'fixed', inset: 0, zIndex: 1000,
                    background: 'rgba(0,0,0,0.45)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                    <div style={{
                        width: '520px', maxWidth: '92vw', background: '#fff',
                        border: '2px solid #c62828', borderRadius: '8px',
                        padding: '16px 18px', boxShadow: '0 8px 30px rgba(0,0,0,0.35)'
                    }}>
                        <div style={{ fontSize: '15px', fontWeight: 'bold', color: '#c62828', marginBottom: '10px' }}>
                            🧹 Очистить данные за {clearAsk.month}?
                        </div>
                        <div style={{ fontSize: '12px', color: '#333', lineHeight: 1.6 }}>
                            <div>• Смены в листе <b>«{clearAsk.sheet || clearAsk.month}»</b>:
                                будет очищено <b>{clearAsk.shifts}</b> дней
                                {clearAsk.sheet ? '' : ' (листа за этот месяц в файле нет)'}</div>
                            <div>• План в базе: будет удалено записей <b>{clearAsk.plans}</b>
                                {clearAsk.employees ? ` (по ${clearAsk.employees} сотрудникам)` : ''}</div>
                            <div>• Колонка «Изменения в графике»: значений <b>{clearAsk.notes}</b></div>
                            <div style={{ marginTop: '8px', color: '#666' }}>
                                Сотрудники, оформление и выходные остаются на месте — таблица
                                станет пустой, как новая форма.
                            </div>
                            <div style={{ marginTop: '8px', color: '#c62828', fontWeight: 'bold' }}>
                                Отменить это действие нельзя.
                            </div>
                        </div>
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '10px',
                            marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #eee'
                        }}>
                            <button
                                onClick={confirmClear}
                                style={{
                                    padding: '7px 16px', background: '#c62828', color: '#fff',
                                    border: 'none', borderRadius: '4px', cursor: 'pointer',
                                    fontSize: '12px', fontWeight: 'bold'
                                }}
                            >
                                Да, очистить
                            </button>
                            <button
                                onClick={cancelClear}
                                style={{
                                    padding: '7px 16px', background: '#f0f0f0', color: '#333',
                                    border: '1px solid #ccc', borderRadius: '4px',
                                    cursor: 'pointer', fontSize: '12px'
                                }}
                            >
                                Отмена
                            </button>
                            <span style={{ marginLeft: 'auto', fontSize: '11px', color: '#888' }}>
                                ответьте в течение <b style={{ color: '#c62828' }}>{clearLeft}</b> с,
                                иначе окно закроется
                            </span>
                        </div>
                    </div>
                </div>
            )}

            {/* Легенда */}
            <div style={{
                display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px 12px',
                flexShrink: 0, padding: '2px 10px', marginBottom: '4px', fontSize: '10px', color: '#555'
            }}>
                <span><b>Цвета графика:</b></span>
                {newShiftScheme ? (
                    <>
                        <span><span style={{ background: '#fff', padding: '1px 8px', border: '1px solid #bbb' }}>Я</span> основная смена</span>
                        <span><span style={{ background: '#FFFF00', padding: '1px 8px', border: '1px solid #bbb' }}>В</span> доп смена</span>
                    </>
                ) : (
                    <span><span style={{ background: '#FFFF00', padding: '1px 8px', border: '1px solid #bbb' }}>Д</span> дежурство</span>
                )}
                <span><span style={{ background: '#92D050', padding: '1px 8px', border: '1px solid #bbb' }}>О</span> отпуск</span>
                <span><span style={{ background: '#FF0000', padding: '1px 8px', border: '1px solid #bbb', color: '#fff' }}>Б</span> больничный</span>
                <span><span style={{ background: '#FFC000', padding: '1px 8px', border: '1px solid #bbb' }}>Б/С</span> б/с</span>
                <span><span style={{ background: '#73A0B4', padding: '1px 8px', border: '1px solid #bbb' }}>вых</span> выходной</span>
                <span style={{ color: '#1565c0' }}>
                    с ноября 2026: <b>Я</b> — основная смена, <b>В</b> — доп смена
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                    <b>Рамки сверки:</b>
                    <span style={{ boxShadow: 'inset 0 0 0 2px #d32f2f', padding: '1px 6px', border: '1px solid #eee' }}
                          title="В графике и в плане базы стоят разные значения">
                        расхождение с планом
                    </span>
                    <span style={{ boxShadow: 'inset 0 0 0 2px #ff9800', padding: '1px 6px', border: '1px solid #eee' }}
                          title="В графике смена есть, а плана в базе нет">
                        в графике есть, плана нет
                    </span>
                    <span style={{ boxShadow: 'inset 0 0 0 2px #1976d2', padding: '1px 6px', border: '1px solid #eee' }}
                          title="План в базе есть, а в графике день пустой">
                        план есть, в графике пусто
                    </span>
                </span>
                <span style={{ marginLeft: 'auto', color: '#888' }}>🖱️ клик по ячейке — редактирование: смены, ФИО, должность, участок (Enter — сохранить, Esc — отмена)</span>
                <span style={{ color: selected ? '#1565c0' : '#888', fontWeight: selected ? 'bold' : 'normal' }}>
                    {selected ? `Выбран: ${selected.name}` : 'клик по строке — выделить сотрудника'}
                </span>
                {selected && (
                    <button
                        onClick={() => setSelected(null)}
                        title="Снять выделение"
                        style={{
                            padding: '1px 8px', fontSize: '10px', cursor: 'pointer',
                            background: '#f0f0f0', border: '1px solid #ccc', borderRadius: '3px'
                        }}
                    >
                        ✖ снять
                    </button>
                )}
            </div>

            {/* Таблица */}
            <div style={{ flex: 1, overflow: 'auto', border: '1px solid #ccc', borderRadius: '4px', background: 'white' }}>
                <table style={{
                    borderCollapse: 'separate', borderSpacing: 0, fontSize: '10px',
                    tableLayout: 'fixed', width: '100%', minWidth: '980px'
                }}>
                    {/* Колонки: закреплённые и служебные — фиксированной ширины,
                        дни месяца растягиваются на всю ширину экрана */}
                    <colgroup>
                        {cols.map((c) => {
                            const w = colWidthFor(c);
                            return <col key={c} style={w ? { width: `${w}px` } : undefined} />;
                        })}
                    </colgroup>
                    <tbody>
                        {rows.map((r) => {
                            const emp = employeeAt(r);
                            const isRowSelected = !!(emp && selected && selected.row === r);

                            return (
                            <tr key={r} style={{
                                backgroundColor: isRowSelected ? '#e3f2fd' : 'transparent',
                                outline: isRowSelected ? '2px solid #1565c0' : 'none',
                                outlineOffset: isRowSelected ? '-1px' : '0'
                            }}>
                                {cols.map((c) => {
                                    const key = `${r}:${c}`;
                                    if (covered.has(key)) return null;

                                    const cell = cellMap[key] || {};
                                    const m = mergeAt[key];
                                    const day = dayByCol[c];
                                    const isEditing = editing && editing.r === r && editing.c === c;
                                    const isStickyCol = COL_WIDTH[c] !== undefined && r >= data.first_data_row;
                                    const isHeaderRow = r <= data.weekday_row;

                                    const style = cellStyle(cell, m, day);
                                    style.overflow = 'hidden';
                                    style.textOverflow = 'ellipsis';

                                    if (isHeaderRow) {
                                        style.position = 'sticky';
                                        style.top = r === 1 ? 0 : 18;
                                        style.background = cell.fill
                                            ? `#${cell.fill}`
                                            : (day && day.weekend ? `#${weekendFill}` : '#e9eef4');
                                        style.zIndex = 5;
                                    }
                                    if (isStickyCol) {
                                        style.position = 'sticky';
                                        style.left = `${COL_LEFT[c]}px`;
                                        style.background = cell.fill
                                            ? `#${cell.fill}`
                                            : (isRowSelected ? '#e3f2fd' : '#fff');
                                        style.zIndex = isHeaderRow ? 6 : 4;
                                    }

                                    const clickable = cell.editable && !isEditing;

                                    return (
                                        <td
                                            key={key}
                                            rowSpan={m && m.rows > 1 ? m.rows : undefined}
                                            colSpan={m && m.cols > 1 ? m.cols : undefined}
                                            style={style}
                                            title={cellTitle(cell) || (emp ? 'Кликните, чтобы выбрать сотрудника' : undefined)}
                                            onClick={emp ? () => {
                                                selectRow(r);
                                                if (clickable) startEdit(r, c, cell.v);
                                            } : undefined}
                                        >
                                            {isEditing ? (
                                                <input
                                                    type="text"
                                                    value={editValue}
                                                    autoFocus
                                                    onChange={(e) => setEditValue(e.target.value)}
                                                    onKeyDown={(e) => onKeyDown(e, r, c, cell.ef)}
                                                    onBlur={() => onBlur(r, c, cell.ef)}
                                                    disabled={saving}
                                                    style={inputStyle}
                                                />
                                            ) : (cell.v || '')}
                                        </td>
                                    );
                                })}
                            </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export default ScheduleView;
