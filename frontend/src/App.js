import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL } from './config';
import { WEEK_LABELS, WEEK_LABELS_SHORT, getMonths } from './constants';
import useCellEditing from './hooks/useCellEditing';
import Header from './components/Header';
import MonthSelector from './components/MonthSelector';
import PlanFactTable from './components/PlanFactTable';
import Legend from './components/Legend';
import MealExport from './MealExport';
import Timesheet from './Timesheet';
import ScheduleView from './components/ScheduleView';
import MedCheckExport from './MedCheckExport';

const PAGE_STYLE = {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    width: '100%',
    padding: '4px 10px',
    overflow: 'hidden',
    background: 'white'
};

function App() {
    const [activePage, setActivePage] = useState('planfact');
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [currentWeek, setCurrentWeek] = useState(0);

    // Выбранный месяц
    const [selectedMonth, setSelectedMonth] = useState(() => {
        const now = new Date();
        return {
            year: now.getFullYear(),
            month: now.getMonth()
        };
    });

    const [exporting, setExporting] = useState(false);
    const [uploadMessage, setUploadMessage] = useState('');

    const [sortField, setSortField] = useState('name');
    const [sortDirection, setSortDirection] = useState('asc');

    const [uploading, setUploading] = useState(false);
    const [uploadStatus, setUploadStatus] = useState('');

    // Счётчик для кнопки «Обновить» в общей верхней панели
    const [refreshToken, setRefreshToken] = useState(0);

    // Загрузка данных план-факт за выбранный месяц
    const loadData = async () => {
        setLoading(true);
        setError(null);
        try {
            const month = String(selectedMonth.month + 1).padStart(2, '0');
            const year = selectedMonth.year;
            const url = `${API_URL}/plan-fact/?year=${year}&month=${month}`;
            console.log('📊 Загрузка данных из:', url);
            const response = await axios.get(url);
            console.log('📊 Получено записей:', response.data.length);
            setData(response.data);
        } catch (err) {
            console.error('❌ Ошибка:', err);
            setError(err.message);
        }
        setLoading(false);
    };

    useEffect(() => {
        loadData();
    }, [selectedMonth, refreshToken]); // Перезагружаем при смене месяца и по кнопке «Обновить»

    const handleRefresh = () => {
        setRefreshToken((t) => t + 1);
    };

    // Логика редактирования ячеек (приход/уход/этап)
    const {
        editingCell,
        editValue,
        saving,
        editingField,
        selectedEmployee,
        resetEditing,
        handleCellClick,
        handleEditChange,
        handleStageChange,
        handlePlanChange,
        handleRowSelect,
        handleEditKeyDown,
        handleEditBlur
    } = useCellEditing({ onSaved: loadData, setUploadMessage });

    // Переключение месяца стрелками ◀ ▶
    const changeMonth = (direction) => {
        let newMonth = selectedMonth.month + direction;
        let newYear = selectedMonth.year;
        if (newMonth < 0) {
            newMonth = 11;
            newYear--;
        } else if (newMonth > 11) {
            newMonth = 0;
            newYear++;
        }
        setSelectedMonth({ year: newYear, month: newMonth });
        setCurrentWeek(0); // Сбрасываем неделю при смене месяца
    };

    // Выбор месяца из выпадающего списка (month — 1-based из value)
    const handleSelectMonth = (year, month) => {
        setSelectedMonth({ year, month: month - 1 });
        setCurrentWeek(0);
    };

    const handleFileUpload = async (event, type) => {
        const file = event.target.files[0];
        if (!file) return;

        setUploading(true);
        setUploadStatus(`⏳ Загрузка ${type}...`);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const endpoint = type === 'schedule' ? '/upload/schedule/' : '/upload/journal/';
            const response = await axios.post(`${API_URL}${endpoint}`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });

            if (response.data.status === 'success') {
                setUploadStatus(`✅ ${response.data.message}`);
                setTimeout(() => setUploadStatus(''), 5000);
                await loadData();
            } else {
                setUploadStatus(`❌ Ошибка: ${response.data.message || 'Неизвестная ошибка'}`);
            }
        } catch (err) {
            console.error('❌ Ошибка загрузки:', err);
            setUploadStatus(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
        }

        setUploading(false);
        event.target.value = '';
    };

    const getWeekNumber = (dateStr) => {
        if (!dateStr) return 0;
        const day = new Date(dateStr).getDate();
        if (day <= 7) return 0;
        if (day <= 14) return 1;
        if (day <= 21) return 2;
        if (day <= 28) return 3;
        return 4;
    };

    // Группировка записей по неделям
    const weekData = {};
    WEEK_LABELS.forEach((_, idx) => { weekData[idx] = []; });

    data.forEach(row => {
        const weekIdx = getWeekNumber(row.date);
        if (weekData[weekIdx]) {
            weekData[weekIdx].push(row);
        }
    });

    const currentData = weekData[currentWeek] || [];

    // Группировка по сотрудникам для текущей недели
    const employeesMap = {};
    currentData.forEach(row => {
        const key = row.employee_name;
        if (!employeesMap[key]) {
            employeesMap[key] = {
                name: row.employee_name,
                department: row.department,
                position: row.position,
                days: {}
            };
        }
        employeesMap[key].days[row.date] = {
            plan: row.plan_type,
            plan_hours: row.plan_hours,
            fact: row.fact_hours,
            status: row.status,
            start_time: row.start_time || '',
            end_time: row.end_time || '',
            production_stage: row.production_stage || ''
        };
    });

    const sortEmployees = (employeesList, field, direction) => {
        return [...employeesList].sort((a, b) => {
            let valA = (a[field] || '').toLowerCase();
            let valB = (b[field] || '').toLowerCase();

            if (valA < valB) return direction === 'asc' ? -1 : 1;
            if (valA > valB) return direction === 'asc' ? 1 : -1;
            return 0;
        });
    };

    let employees = sortEmployees(Object.values(employeesMap), sortField, sortDirection);

    const dates = [...new Set(currentData.filter(r => r.date).map(r => r.date))].sort();

    const toggleSort = (field) => {
        if (sortField === field) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
        } else {
            setSortField(field);
            setSortDirection('asc');
        }
    };

    // Удаление данных сотрудника с начала текущей недели до конца месяца
    const daysInMonth = new Date(selectedMonth.year, selectedMonth.month + 1, 0).getDate();
    const weekStartDay = Math.min(1 + currentWeek * 7, daysInMonth);

    const handleDeleteEmployee = async () => {
        if (!selectedEmployee) {
            setUploadMessage('⚠️ Сначала выберите сотрудника — кликните по его строке в таблице');
            setTimeout(() => setUploadMessage(''), 3000);
            return;
        }

        const mm = String(selectedMonth.month + 1).padStart(2, '0');
        const dateFrom = `${selectedMonth.year}-${mm}-${String(weekStartDay).padStart(2, '0')}`;
        const dateTo = `${selectedMonth.year}-${mm}-${String(daysInMonth).padStart(2, '0')}`;

        if (!window.confirm(
            `Удалить данные сотрудника «${selectedEmployee}»?\n\n` +
            `Период: с ${dateFrom} (неделя «${WEEK_LABELS[currentWeek]}») по ${dateTo} (конец месяца).\n` +
            `Будут удалены все планы и факты за этот период. Отменить нельзя.`
        )) return;

        try {
            const response = await axios.post(`${API_URL}/delete-employee-from/`, {
                employee_name: selectedEmployee,
                date_from: dateFrom,
                date_to: dateTo
            });

            if (response.data.status === 'success') {
                setUploadMessage(`✅ ${response.data.message}`);
                setTimeout(() => setUploadMessage(''), 5000);
                resetEditing();
                await loadData();
            }
        } catch (err) {
            console.error('❌ Ошибка удаления:', err);
            setUploadMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
            setTimeout(() => setUploadMessage(''), 3000);
        }
    };

    // Выгрузка недели (кнопки пока не привязаны в интерфейсе)
    const exportWeekly = async (weekId) => {
        setExporting(true);
        setUploadMessage(`⏳ Выгрузка недели ${WEEK_LABELS[weekId]}...`);
        try {
            const response = await axios.get(`${API_URL}/export/weekly/?week_id=${weekId}`, {
                responseType: 'blob'
            });

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            const weekLabel = WEEK_LABELS[weekId].replace(/\s/g, '_');
            link.setAttribute('download', `План-Факт_неделя_${weekLabel}.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();

            setUploadMessage(`✅ Выгружена неделя ${WEEK_LABELS[weekId]}`);
            setTimeout(() => setUploadMessage(''), 3000);
        } catch (err) {
            console.error('❌ Ошибка выгрузки:', err);
            setUploadMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
            setTimeout(() => setUploadMessage(''), 3000);
        }
        setExporting(false);
    };

    // Выгрузка месячного отчета (кнопки пока не привязаны в интерфейсе)
    const exportMonthly = async () => {
        setExporting(true);
        setUploadMessage('⏳ Выгрузка месячного отчета...');
        try {
            const month = String(selectedMonth.month + 1).padStart(2, '0');
            const response = await axios.get(`${API_URL}/export/monthly/?year=${selectedMonth.year}&month=${month}`, {
                responseType: 'blob'
            });

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `План-Факт_${selectedMonth.year}_${month}.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();

            setUploadMessage('✅ Месячный отчет выгружен');
            setTimeout(() => setUploadMessage(''), 3000);
        } catch (err) {
            console.error('❌ Ошибка выгрузки:', err);
            setUploadMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
            setTimeout(() => setUploadMessage(''), 3000);
        }
        setExporting(false);
    };

    const daysCount = dates.length;
    const colWidth = daysCount <= 7 ? 45 : (daysCount <= 14 ? 32 : 24);
    const tableFontSize = daysCount <= 7 ? 11 : (daysCount <= 14 ? 10 : 9);

    // Общие пропсы шапки для всех страниц
    const headerProps = {
        selectedMonth,
        recordCount: data.length,
        onStepMonth: changeMonth,
        onSelectMonth: handleSelectMonth,
        onRefresh: handleRefresh,
        uploading,
        onUpload: handleFileUpload,
        uploadMessage,
        uploadStatus,
        activePage,
        onNavigate: setActivePage
    };

    // Страница табеля (месяц — общий из шапки)
    if (activePage === 'timesheet') {
        return (
            <div style={PAGE_STYLE}>
                <Header {...headerProps} />
                <div style={{ flex: 1, overflow: 'hidden' }}>
                    <Timesheet
                        onBack={() => setActivePage('planfact')}
                        year={selectedMonth.year}
                        month={selectedMonth.month}
                        refreshToken={refreshToken}
                    />
                </div>
            </div>
        );
    }

    // Страница питания
    if (activePage === 'meal') {
        return (
            <div style={PAGE_STYLE}>
                <Header {...headerProps} />
                <div style={{ flex: 1, overflow: 'auto', padding: '10px 0' }}>
                    <MealExport refreshToken={refreshToken} />
                </div>
            </div>
        );
    }

    // Страница графика (форма А3) со сравнением с планом из БД
    if (activePage === 'schedule') {
        return (
            <div style={PAGE_STYLE}>
                <Header {...headerProps} />
                <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
                    <ScheduleView
                        year={selectedMonth.year}
                        month={selectedMonth.month}
                        refreshToken={refreshToken}
                        onPlanChanged={loadData}
                    />
                </div>
            </div>
        );
    }

    // Страница медосмотра (месяц — общий из шапки)
    if (activePage === 'medcheck') {
        return (
            <div style={PAGE_STYLE}>
                <Header {...headerProps} />
                <div style={{ flex: 1, overflow: 'auto', padding: '10px 0' }}>
                    <MedCheckExport
                        year={selectedMonth.year}
                        month={selectedMonth.month}
                        refreshToken={refreshToken}
                    />
                </div>
            </div>
        );
    }

    // План-Факт (основная страница)
    // Экран загрузки показываем только при первой загрузке: при обновлении
    // таблица остаётся на месте (иначе сбрасывалась прокрутка и выделение).
    if (loading && data.length === 0) return <div style={{ padding: '40px', textAlign: 'center' }}>🔄 Загрузка данных...</div>;
    if (error) return <div style={{ padding: '40px', textAlign: 'center', color: 'red' }}>❌ Ошибка: {error}</div>;
    if (data.length === 0) return (
        <div style={{ padding: '40px', textAlign: 'center' }}>
            <div style={{ fontSize: '16px', marginBottom: '10px' }}>📭 Нет данных за выбранный месяц</div>
            <div style={{ fontSize: '14px', color: '#666' }}>
                <MonthSelector
                    selectedMonth={selectedMonth}
                    onStepMonth={changeMonth}
                    onSelectMonth={handleSelectMonth}
                    recordCount={data.length}
                />
                <p style={{ marginTop: '20px' }}>
                    Загрузите график или переключитесь на другой месяц
                </p>
                <p style={{ fontSize: '12px', color: '#999' }}>
                    Доступные месяцы: {getMonths().map(m => m.label).join(', ')}
                </p>
            </div>
        </div>
    );

    // Стили кнопок единой панели действий
    const toolBtn = (active) => ({
        padding: '2px 9px',
        background: active ? '#1565c0' : '#f0f0f0',
        color: active ? 'white' : '#333',
        border: 'none',
        borderRadius: '4px',
        cursor: 'pointer',
        fontSize: '11px',
        fontWeight: active ? 'bold' : 'normal',
        whiteSpace: 'nowrap'
    });
    const sortIcon = (field) => (sortField !== field ? '↕' : sortDirection === 'asc' ? '↑' : '↓');

    return (
        <div style={PAGE_STYLE}>
            <Header {...headerProps} />

            {/* Единая строка действий страницы: сортировка · недели · выгрузки · удаление */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '6px 12px',
                flexShrink: 0,
                padding: '4px 10px',
                marginBottom: '4px',
                background: '#fafbfc',
                border: '1px solid #dfe4ea',
                borderRadius: '6px'
            }}>
                <span style={{ color: '#666', fontSize: '10px' }}>Сортировка:</span>
                <button onClick={() => toggleSort('name')} style={toolBtn(sortField === 'name')}>
                    ФИО {sortIcon('name')}
                </button>
                <button onClick={() => toggleSort('position')} style={toolBtn(sortField === 'position')}>
                    Должность {sortIcon('position')}
                </button>

                <span style={{ width: 1, height: 20, background: '#d7dde4' }} />

                {WEEK_LABELS_SHORT.map((label, idx) => (
                    <button key={idx} onClick={() => setCurrentWeek(idx)} style={toolBtn(currentWeek === idx)}
                            title={WEEK_LABELS[idx]}>
                        {label} ({weekData[idx]?.length || 0})
                    </button>
                ))}

                <span style={{ width: 1, height: 20, background: '#d7dde4' }} />

                <button
                    onClick={() => exportWeekly(currentWeek)}
                    disabled={exporting}
                    title="Выгрузить текущую неделю в Excel"
                    style={{ ...toolBtn(false), background: exporting ? '#ccc' : '#1565c0', color: '#fff' }}
                >
                    📥 Неделя
                </button>
                <button
                    onClick={exportMonthly}
                    disabled={exporting}
                    title="Выгрузить весь месяц в Excel"
                    style={{ ...toolBtn(false), background: exporting ? '#ccc' : '#00695c', color: '#fff' }}
                >
                    📥 Месяц
                </button>

                <span style={{ width: 1, height: 20, background: '#d7dde4' }} />

                <button
                    onClick={handleDeleteEmployee}
                    disabled={!selectedEmployee}
                    title="Удалить планы и факты сотрудника с текущей недели до конца месяца"
                    style={{ ...toolBtn(false), background: selectedEmployee ? '#d32f2f' : '#ccc', color: '#fff' }}
                >
                    🗑️ Удалить ({WEEK_LABELS_SHORT[currentWeek]})
                </button>

                <span style={{ color: '#888', fontSize: '10px' }}>
                    {selectedEmployee ? `Выбран: ${selectedEmployee}` : 'Выберите строку для удаления'}
                </span>
                <span style={{ color: '#888', fontSize: '10px', marginLeft: 'auto' }}>
                    {loading && <span style={{ color: '#1565c0' }}>⏳ обновление… </span>}
                    Всего: <b>{data.length}</b>
                </span>
            </div>

            <PlanFactTable
                employees={employees}
                dates={dates}
                colWidth={colWidth}
                tableFontSize={tableFontSize}
                selectedEmployee={selectedEmployee}
                editingCell={editingCell}
                editingField={editingField}
                editValue={editValue}
                saving={saving}
                onCellClick={handleCellClick}
                onRowSelect={handleRowSelect}
                onTimeChange={handleEditChange}
                onStageChange={handleStageChange}
                onPlanChange={handlePlanChange}
                onEditKeyDown={handleEditKeyDown}
                onEditBlur={handleEditBlur}
            />

            <Legend />
        </div>
    );
}

export default App;
