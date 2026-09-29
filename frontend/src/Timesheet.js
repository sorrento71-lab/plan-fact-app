// Timesheet.js
import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API_URL } from './config';

// Месяц и год приходят из общей шапки (App) — здесь свой переключатель не нужен.
function Timesheet({ onBack, year, month, refreshToken }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [isExporting, setIsExporting] = useState(false);
    const [uploadMessage, setUploadMessage] = useState('');
    const [useTestData, setUseTestData] = useState(false);
    const [sortField, setSortField] = useState('employee_name');
    const [sortDirection, setSortDirection] = useState('asc');

    const monthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];

    // Тестовые данные для проверки отображения
    const getTestData = () => {
        const days = [];
        for (let d = 1; d <= 31; d++) {
            const dateStr = `2026-08-${String(d).padStart(2, '0')}`;
            // Для теста: 1-5 числа - явка с 11 часами
            if (d >= 1 && d <= 5) {
                days.push({
                    date: dateStr,
                    fact_hours: 11,
                    mark: 'Я'
                });
            }
            // 6-10 числа - отпуск
            else if (d >= 6 && d <= 10) {
                days.push({
                    date: dateStr,
                    plan_type: 'О',
                    fact_hours: 0
                });
            }
            // 11-15 числа - больничный
            else if (d >= 11 && d <= 15) {
                days.push({
                    date: dateStr,
                    plan_type: 'Б',
                    fact_hours: 0
                });
            }
            // 16-20 числа - явка с 8 часами
            else if (d >= 16 && d <= 20) {
                days.push({
                    date: dateStr,
                    fact_hours: 8,
                    mark: 'Я'
                });
            }
            // остальные - выходные
            else {
                days.push({
                    date: dateStr,
                    plan_type: 'В',
                    fact_hours: 0
                });
            }
        }

        return {
            period: {
                from: '2026-08-01',
                to: '2026-08-31'
            },
            employees: [
                {
                    employee_name: 'Кормановский Денис Евгеньевич',
                    tab_number: 'MTE1-00548',
                    days: days
                },
                {
                    employee_name: 'Агишев Даниил Денисович',
                    tab_number: 'MTE1-00540',
                    days: days.map(d => ({ ...d })) // копируем те же дни
                },
                {
                    employee_name: 'Кропанев Александр',
                    tab_number: 'MTE1-00487',
                    days: days.map(d => ({ ...d }))
                }
            ]
        };
    };

    const loadData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const monthNum = month + 1;
            const dateFrom = `${year}-${String(monthNum).padStart(2, '0')}-01`;
            const lastDay = new Date(year, monthNum, 0).getDate();
            const dateTo = `${year}-${String(monthNum).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;

            console.log('📊 Загрузка табеля:', dateFrom, 'до', dateTo);

            let responseData;
            try {
                const response = await axios.get(`${API_URL}/timesheet/`, {
                    params: { date_from: dateFrom, date_to: dateTo }
                });
                responseData = response.data;
                console.log('📊 Получены данные от API:', responseData);
            } catch (err) {
                console.warn('⚠️ Ошибка загрузки данных, используем тестовые:', err.message);
                responseData = getTestData();
                setUseTestData(true);
                setUploadMessage('⚠️ Используются тестовые данные (API недоступен)');
                setTimeout(() => setUploadMessage(''), 5000);
            }

            // Проверяем структуру данных
            if (responseData && responseData.employees) {
                console.log('📊 Количество сотрудников:', responseData.employees.length);
                if (responseData.employees.length > 0) {
                    console.log('📊 Первый сотрудник:', responseData.employees[0]);
                    console.log('📊 Дни первого сотрудника (первые 5):',
                        responseData.employees[0].days?.slice(0, 5));
                }
            } else {
                console.warn('⚠️ Неверная структура данных, используем тестовые');
                responseData = getTestData();
                setUseTestData(true);
            }

            setData(responseData);
        } catch (err) {
            console.error('❌ Ошибка загрузки табеля:', err);
            // В случае ошибки используем тестовые данные
            const testData = getTestData();
            setData(testData);
            setUseTestData(true);
            setUploadMessage('⚠️ Используются тестовые данные');
            setTimeout(() => setUploadMessage(''), 5000);
        }
        setLoading(false);
    }, [month, year]);

    useEffect(() => {
        loadData();
    }, [loadData, refreshToken]);

    const exportTimesheet = async () => {
        setIsExporting(true);
        setUploadMessage('⏳ Выгрузка табеля...');
        try {
            const monthNum = month + 1;
            const dateFrom = `${year}-${String(monthNum).padStart(2, '0')}-01`;
            const lastDay = new Date(year, monthNum, 0).getDate();
            const dateTo = `${year}-${String(monthNum).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;

            const response = await axios.get(`${API_URL}/export/timesheet/`, {
                params: {
                    date_from: dateFrom,
                    date_to: dateTo,
                    sort_field: sortField,
                    sort_direction: sortDirection
                },
                responseType: 'blob'
            });

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;

            const filename = `Табель_${monthNames[month]}_${year}.xlsx`;
            link.setAttribute('download', filename);
            document.body.appendChild(link);
            link.click();
            link.remove();

            setUploadMessage('✅ Табель выгружен');
            setTimeout(() => setUploadMessage(''), 3000);
        } catch (err) {
            console.error('❌ Ошибка выгрузки табеля:', err);
            setUploadMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
            setTimeout(() => setUploadMessage(''), 3000);
        }
        setIsExporting(false);
    };

    const isWeekend = (date) => {
        const day = date.getDay();
        return day === 0 || day === 6;
    };

    if (loading) return <div style={{ padding: '40px', textAlign: 'center' }}>🔄 Загрузка табеля...</div>;
    if (error) return <div style={{ padding: '40px', textAlign: 'center', color: 'red' }}>❌ Ошибка: {error}</div>;
    if (!data || !data.employees || data.employees.length === 0) {
        return (
            <div style={{ padding: '40px', textAlign: 'center' }}>
                <p>Нет данных для отображения табеля</p>
                <button
                    onClick={loadData}
                    style={{ padding: '10px 20px', background: '#1565c0', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                >
                    🔄 Обновить
                </button>
            </div>
        );
    }

    const { period, employees } = data;

    // Сортировка сотрудников (как на вкладке «План-Факт»)
    const toggleSort = (field) => {
        if (sortField === field) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
        } else {
            setSortField(field);
            setSortDirection('asc');
        }
    };

    const sortedEmployees = [...employees].sort((a, b) => {
        let valA = (a[sortField] || '').toString().toLowerCase();
        let valB = (b[sortField] || '').toString().toLowerCase();
        if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
        if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    // Получаем все дни месяца
    const allDays = [];
    const startDate = new Date(period.from);
    const endDate = new Date(period.to);
    for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
        allDays.push(new Date(d));
    }

    // Разделяем на первую и вторую половину
    const half1 = allDays.filter(d => d.getDate() <= 15);
    const half2 = allDays.filter(d => d.getDate() > 15);

    // Функция для получения данных по дню
    const getDayData = (dayDataMap, date) => {
        const dateStr = date.toISOString().split('T')[0];
        return dayDataMap[dateStr] || null;
    };

    // Форматирование часов
    const formatHours = (hours) => {
        if (!hours || hours === 0) return '';
        if (Number.isInteger(hours)) return String(hours);
        return String(Math.round(hours * 10) / 10);
    };

    // Получение кода для ячейки (первая строка)
    const getCode = (day) => {
        if (!day) return '';

        // Если есть фактические часы - явка
        if (day.fact_hours && day.fact_hours > 0) return 'я';

        // Если есть отметка "Я" - явка
        if (day.mark === 'Я') return 'я';

        // Плановые типы
        if (day.plan_type) {
            const upper = day.plan_type.toUpperCase();
            if (upper === 'Я') return 'я';
            if (upper === 'О') return 'О';
            if (upper === 'Б') return 'Б';
            // «В» — доп смена (с ноября 2026): в табеле Т-13 отдельного кода нет,
            // день показывается как явка. Выходной — пустая клетка (план «ВЫХ»).
            if (upper === 'В') return 'я';
            if (upper === 'ВЫХ') return '';
            if (upper === 'Б/С') return 'б/с';
            if (upper === 'Р') return 'Р';
            if (upper === 'К') return 'К';
            if (upper === 'ПР') return 'ПР';
        }

        return '';
    };

    // Получение часов для ячейки (вторая строка)
    const getHoursDisplay = (day) => {
        if (!day) return '';
        if (day.fact_hours && day.fact_hours > 0) {
            return formatHours(day.fact_hours);
        }
        return '';
    };

    // Проверка, есть ли явка
    const hasAttendance = (day) => {
        if (!day) return false;
        if (day.fact_hours && day.fact_hours > 0) return true;
        if (day.mark === 'Я') return true;
        if (day.plan_type) {
            const upper = day.plan_type.toUpperCase();
            // «Я» — основная смена, «В» — доп смена (с ноября 2026): обе считаются явкой
            if (upper === 'Я' || upper === 'В') return true;
        }
        return false;
    };

    // Стили кнопок панели действий
    const btnBase = {
        padding: '3px 10px', border: 'none', borderRadius: '4px',
        cursor: 'pointer', fontSize: '11px', fontWeight: 'bold', whiteSpace: 'nowrap'
    };
    const btnGray = { ...btnBase, background: '#6c757d', color: '#fff' };
    const btnBlue = { ...btnBase, background: '#1565c0', color: '#fff' };
    const btnExport = { ...btnBase, background: isExporting ? '#ccc' : '#e74c3c', color: '#fff' };
    const btnSort = (active) => ({
        ...btnBase, padding: '3px 8px', fontWeight: active ? 'bold' : 'normal',
        background: active ? '#1565c0' : '#f0f0f0', color: active ? '#fff' : '#333'
    });
    const sortMark = (field) => (sortField !== field ? '↕' : sortDirection === 'asc' ? '↑' : '↓');

    return (
        <div style={{
            padding: '10px',
            fontFamily: 'Arial, sans-serif',
            fontSize: '12px',
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            flex: 1
        }}>
            {uploadMessage && (
                <div style={{
                    padding: '4px 12px',
                    marginBottom: '8px',
                    background: uploadMessage.includes('✅') ? '#d4edda' : uploadMessage.includes('⚠️') ? '#fff3cd' : uploadMessage.includes('❌') ? '#f8d7da' : '#fff3cd',
                    borderRadius: '4px',
                    fontSize: '12px',
                    color: uploadMessage.includes('✅') ? '#155724' : uploadMessage.includes('⚠️') ? '#856404' : uploadMessage.includes('❌') ? '#721c24' : '#856404',
                    flexShrink: 0
                }}>
                    {uploadMessage}
                </div>
            )}

            {useTestData && (
                <div style={{
                    padding: '4px 12px',
                    marginBottom: '8px',
                    background: '#fff3cd',
                    borderRadius: '4px',
                    fontSize: '12px',
                    color: '#856404',
                    flexShrink: 0,
                    border: '1px solid #ffc107'
                }}>
                    ⚠️ Внимание: отображаются ТЕСТОВЫЕ данные. API не отвечает или данные не загружены.
                </div>
            )}

            {/* Единая строка действий: назад · сортировка · выгрузка · обновить */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '6px 12px',
                flexShrink: 0,
                padding: '4px 10px',
                marginBottom: '8px',
                background: '#fafbfc',
                border: '1px solid #dfe4ea',
                borderRadius: '6px'
            }}>
                <button onClick={onBack} style={btnGray}>◀ Назад</button>
                <span style={{ width: 1, height: 20, background: '#d7dde4' }} />

                <button onClick={() => toggleSort('employee_name')} style={btnSort(sortField === 'employee_name')}>
                    ФИО {sortMark('employee_name')}
                </button>
                <button onClick={() => toggleSort('tab_number')} style={btnSort(sortField === 'tab_number')}>
                    Таб. № {sortMark('tab_number')}
                </button>

                <span style={{ width: 1, height: 20, background: '#d7dde4' }} />

                <button onClick={exportTimesheet} disabled={isExporting} style={btnExport}
                        title="Выгрузить табель в формате XLSX">
                    {isExporting ? '⏳...' : '📥 Выгрузить табель (XLSX)'}
                </button>
                <button onClick={loadData} style={btnBlue}>🔄 Обновить данные</button>

                <span style={{ color: '#888', fontSize: '10px', marginLeft: 'auto' }}>
                    {monthNames[month]} {year} · Сотрудников: <b>{employees.length}</b>
                    {useTestData ? ' · ТЕСТОВЫЕ' : ''}
                </span>
            </div>

            {/* Таблица в стиле Excel с двумя строками на сотрудника */}
            <div style={{ overflow: 'auto', flex: 1, border: '1px solid #ccc', borderRadius: '4px' }}>
                <table border="1" cellPadding="0" cellSpacing="0" style={{
                    borderCollapse: 'collapse',
                    width: '100%',
                    fontSize: '11px',
                    border: '1px solid #999',
                    minWidth: '900px'
                }}>
                    <thead>
                        <tr style={{ background: '#d9d9d9', textAlign: 'center' }}>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '4px 2px',
                                width: '30px',
                                fontSize: '10px',
                                position: 'sticky',
                                top: 0,
                                background: '#d9d9d9',
                                zIndex: 2
                            }}>
                                №
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '4px 6px',
                                width: '200px',
                                textAlign: 'left',
                                fontSize: '10px',
                                position: 'sticky',
                                top: 0,
                                background: '#d9d9d9',
                                zIndex: 2
                            }}>
                                Фамилия, инициалы
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '4px 2px',
                                width: '70px',
                                fontSize: '10px',
                                position: 'sticky',
                                top: 0,
                                background: '#d9d9d9',
                                zIndex: 2
                            }}>
                                Таб. №
                            </th>
                            {/* Первая половина месяца (1-15) */}
                            {half1.map((d, idx) => {
                                const isWeekendDay = isWeekend(d);
                                return (
                                    <th key={idx} style={{
                                        border: '1px solid #999',
                                        padding: '2px 1px',
                                        minWidth: '22px',
                                        fontSize: '9px',
                                        background: isWeekendDay ? '#d4edda' : '#d9d9d9',
                                        position: 'sticky',
                                        top: 0,
                                        zIndex: 2
                                    }}>
                                        {d.getDate()}
                                    </th>
                                );
                            })}
                            <th style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '20px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}></th>
                            {/* Вторая половина месяца (16-конец) */}
                            {half2.map((d, idx) => {
                                const isWeekendDay = isWeekend(d);
                                return (
                                    <th key={idx} style={{
                                        border: '1px solid #999',
                                        padding: '2px 1px',
                                        minWidth: '22px',
                                        fontSize: '9px',
                                        background: isWeekendDay ? '#d4edda' : '#d9d9d9',
                                        position: 'sticky',
                                        top: 0,
                                        zIndex: 2
                                    }}>
                                        {d.getDate()}
                                    </th>
                                );
                            })}
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '40px',
                                fontSize: '9px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}>
                                Дни I
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '40px',
                                fontSize: '9px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}>
                                Часы I
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '40px',
                                fontSize: '9px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}>
                                Дни II
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '40px',
                                fontSize: '9px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}>
                                Часы II
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '40px',
                                fontSize: '9px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}>
                                Дни всего
                            </th>
                            <th rowSpan="2" style={{
                                border: '1px solid #999',
                                padding: '2px 4px',
                                minWidth: '40px',
                                fontSize: '9px',
                                background: '#d9d9d9',
                                position: 'sticky',
                                top: 0,
                                zIndex: 2
                            }}>
                                Часы всего
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {sortedEmployees.map((emp, empIdx) => {
                            // Создаем map для быстрого доступа к данным по дате
                            const dayDataMap = {};
                            if (emp.days) {
                                emp.days.forEach(day => {
                                    dayDataMap[day.date] = day;
                                });
                            }

                            // Получаем данные для каждой половины
                            const data1 = half1.map(d => getDayData(dayDataMap, d));
                            const data2 = half2.map(d => getDayData(dayDataMap, d));

                            // Коды явок (первая строка)
                            const codes1 = data1.map(d => getCode(d));
                            const codes2 = data2.map(d => getCode(d));

                            // Часы (вторая строка)
                            const hours1 = data1.map(d => getHoursDisplay(d));
                            const hours2 = data2.map(d => getHoursDisplay(d));

                            // Подсчет дней и часов для I половины
                            const days1 = data1.filter(d => hasAttendance(d)).length;
                            const sumHours1 = data1.reduce((sum, d) => sum + (d?.fact_hours || 0), 0);

                            // Подсчет дней и часов для II половины
                            const days2 = data2.filter(d => hasAttendance(d)).length;
                            const sumHours2 = data2.reduce((sum, d) => sum + (d?.fact_hours || 0), 0);

                            // Итоги
                            const daysTotal = days1 + days2;
                            const hoursTotal = sumHours1 + sumHours2;

                            return (
                                <React.Fragment key={empIdx}>
                                    {/* Строка 1: Коды явок */}
                                    <tr>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 2px',
                                            fontSize: '9px'
                                        }}>
                                            {empIdx + 1}
                                        </td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            whiteSpace: 'nowrap'
                                        }}>
                                            {emp.employee_name}
                                        </td>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 2px',
                                            fontSize: '9px'
                                        }}>
                                            {emp.tab_number || ''}
                                        </td>
                                        {codes1.map((val, idx) => {
                                            const day = half1[idx];
                                            const isWeekendDay = isWeekend(day);
                                            return (
                                                <td key={idx} style={{
                                                    textAlign: 'center',
                                                    border: '1px solid #999',
                                                    padding: '2px 1px',
                                                    fontSize: '9px',
                                                    background: isWeekendDay ? '#d4edda' : 'transparent'
                                                }}>
                                                    {val}
                                                </td>
                                            );
                                        })}
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            background: '#e8e8e8'
                                        }}></td>
                                        {codes2.map((val, idx) => {
                                            const day = half2[idx];
                                            const isWeekendDay = isWeekend(day);
                                            return (
                                                <td key={idx} style={{
                                                    textAlign: 'center',
                                                    border: '1px solid #999',
                                                    padding: '2px 1px',
                                                    fontSize: '9px',
                                                    background: isWeekendDay ? '#d4edda' : 'transparent'
                                                }}>
                                                    {val}
                                                </td>
                                            );
                                        })}
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            fontWeight: 'bold'
                                        }}>
                                            {days1}
                                        </td>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            fontWeight: 'bold'
                                        }}>
                                            {formatHours(sumHours1)}
                                        </td>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            fontWeight: 'bold'
                                        }}>
                                            {days2}
                                        </td>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            fontWeight: 'bold'
                                        }}>
                                            {formatHours(sumHours2)}
                                        </td>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            fontWeight: 'bold'
                                        }}>
                                            {daysTotal}
                                        </td>
                                        <td style={{
                                            textAlign: 'center',
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            fontSize: '9px',
                                            fontWeight: 'bold'
                                        }}>
                                            {formatHours(hoursTotal)}
                                        </td>
                                    </tr>
                                    {/* Строка 2: Часы */}
                                    <tr>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 2px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 2px'
                                        }}></td>
                                        {hours1.map((val, idx) => {
                                            const day = half1[idx];
                                            const isWeekendDay = isWeekend(day);
                                            return (
                                                <td key={idx} style={{
                                                    textAlign: 'center',
                                                    border: '1px solid #999',
                                                    padding: '2px 1px',
                                                    fontSize: '9px',
                                                    background: isWeekendDay ? '#d4edda' : 'transparent',
                                                    color: val ? '#000' : '#999'
                                                }}>
                                                    {val}
                                                </td>
                                            );
                                        })}
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px',
                                            background: '#e8e8e8'
                                        }}></td>
                                        {hours2.map((val, idx) => {
                                            const day = half2[idx];
                                            const isWeekendDay = isWeekend(day);
                                            return (
                                                <td key={idx} style={{
                                                    textAlign: 'center',
                                                    border: '1px solid #999',
                                                    padding: '2px 1px',
                                                    fontSize: '9px',
                                                    background: isWeekendDay ? '#d4edda' : 'transparent',
                                                    color: val ? '#000' : '#999'
                                                }}>
                                                    {val}
                                                </td>
                                            );
                                        })}
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                        <td style={{
                                            border: '1px solid #999',
                                            padding: '2px 4px'
                                        }}></td>
                                    </tr>
                                    {/* Разделитель между сотрудниками */}
                                    <tr style={{ height: '4px' }}>
                                        <td colSpan={3 + half1.length + 1 + half2.length + 6} style={{ border: 'none' }}></td>
                                    </tr>
                                </React.Fragment>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {/* Легенда */}
            <div style={{
                marginTop: '8px',
                padding: '6px 12px',
                background: '#f5f5f5',
                borderRadius: '4px',
                display: 'flex',
                gap: '12px',
                flexWrap: 'wrap',
                fontSize: '11px',
                border: '1px solid #ddd',
                flexShrink: 0
            }}>
                <span style={{ fontWeight: 'bold' }}>📋 Коды:</span>
                <span><strong>я</strong> — явка (часы внизу)</span>
                <span><strong>О</strong> — отпуск</span>
                <span><strong>Б</strong> — больничный</span>
                <span><strong>б/с</strong> — без содержания</span>
                <span><strong>Р</strong> — работа в выходной</span>
                <span><strong>К</strong> — командировка</span>
                <span><strong>ПР</strong> — простой</span>
                <span style={{ color: '#1565c0' }}>
                    план: <strong>Я</strong> — основная смена, <strong>В</strong> — доп смена
                    (обе показываются как «я»); выходной — пустая клетка
                </span>
                <span style={{ marginLeft: '10px' }}>
                    <span style={{ background: '#d4edda', padding: '1px 6px', borderRadius: '2px' }}> </span> — выходной день
                </span>
            </div>

            {/* Статистика */}
            <div style={{
                marginTop: '4px',
                display: 'flex',
                gap: '16px',
                flexWrap: 'wrap',
                fontSize: '11px',
                color: '#666',
                flexShrink: 0
            }}>
                <div>👥 Сотрудников: <strong>{employees.length}</strong></div>
                <div>📅 Дней: <strong>{allDays.length}</strong></div>
                <div>📅 I половина: <strong>{half1.length} дней</strong></div>
                <div>📅 II половина: <strong>{half2.length} дней</strong></div>
            </div>
        </div>
    );
}

export default Timesheet;