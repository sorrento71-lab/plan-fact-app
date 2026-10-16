import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL } from './config';

function MealExport({ refreshToken }) {
    const [selectedDate, setSelectedDate] = useState('');
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');
    const [messageType, setMessageType] = useState('');
    const [showPreview, setShowPreview] = useState(false);
    const [previewData, setPreviewData] = useState(null);
    const [exporting, setExporting] = useState(false);

    // Правила питания (кнопки «Добавить», «Исключить», «Замена»)
    const [overrides, setOverrides] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [dialogMode, setDialogMode] = useState(null);   // include | exclude | replace
    const [dialogSearch, setDialogSearch] = useState('');
    const [replaceTarget, setReplaceTarget] = useState('');
    const [replaceValue, setReplaceValue] = useState('');
    const [savingRule, setSavingRule] = useState(false);

    // Планы, при которых сотрудник в питание не попадает:
    // «О» — отпуск, «Б» — больничный, «Б/С» — без сохранения заработной платы.
    const excludedPlanTypes = ['О', 'Б', 'Б/Л', 'БЛ', 'Б/С', 'БС'];

    const normalizeName = (value) => String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();

    const overridesMap = {};
    overrides.forEach((rule) => {
        if (rule && rule.name) overridesMap[normalizeName(rule.name)] = rule;
    });

    const loadOverrides = async () => {
        try {
            const response = await axios.get(`${API_URL}/meal/overrides/`);
            setOverrides(response.data.overrides || []);
        } catch (err) {
            console.error('Не удалось загрузить правила питания:', err);
        }
    };

    const loadEmployees = async () => {
        try {
            const response = await axios.get(`${API_URL}/employees`);
            setEmployees(response.data || []);
        } catch (err) {
            console.error('Не удалось загрузить список сотрудников:', err);
        }
    };

    useEffect(() => {
        loadOverrides();
        loadEmployees();
    }, []);

    const openDialog = (mode) => {
        setDialogMode(mode);
        setDialogSearch('');
        setReplaceTarget('');
        setReplaceValue('');
    };

    const closeDialog = () => {
        setDialogMode(null);
        setReplaceTarget('');
        setReplaceValue('');
    };

    const saveRule = async (name, mode, replacement = '') => {
        setSavingRule(true);
        try {
            const response = await axios.post(`${API_URL}/meal/overrides/`, {
                employee_name: name,
                mode,
                replacement
            });
            setOverrides(response.data.overrides || []);
            showMessage(`✅ ${response.data.message}`, 'success');
            setReplaceTarget('');
            setReplaceValue('');
            if (showPreview && selectedDate) {
                const list = await getEmployeesForDate(selectedDate);
                setPreviewData({ date: selectedDate, employees: list });
            }
        } catch (err) {
            showMessage(`❌ ${err.response?.data?.detail || err.message}`, 'error');
        }
        setSavingRule(false);
    };

    const ruleText = (rule) => {
        if (!rule) return '';
        if (rule.mode === 'include') return 'добавлен в питание';
        if (rule.mode === 'exclude') return 'исключён из питания';
        if (rule.mode === 'replace') return `замена: ${rule.replacement}`;
        return '';
    };

    const ruleColor = (rule) => {
        if (!rule) return '#9e9e9e';
        if (rule.mode === 'include') return '#2e7d32';
        if (rule.mode === 'exclude') return '#c62828';
        if (rule.mode === 'replace') return '#6a1b9a';
        return '#9e9e9e';
    };

    const ruleButtonStyle = (color) => ({
        padding: '5px 12px',
        background: color,
        color: '#fff',
        border: 'none',
        borderRadius: '4px',
        cursor: 'pointer',
        fontSize: '13px'
    });

    useEffect(() => {
        const today = new Date();
        const year = today.getFullYear();
        const month = String(today.getMonth() + 1).padStart(2, '0');
        const day = String(today.getDate()).padStart(2, '0');
        setSelectedDate(`${year}-${month}-${day}`);
    }, []);

    const showMessage = (text, type = 'success') => {
        setMessage(text);
        setMessageType(type);
        setTimeout(() => {
            setMessage('');
            setMessageType('');
        }, 5000);
    };

    const getEmployeesForDate = async (date) => {
        try {
            const response = await axios.get(`${API_URL}/plan-fact/`, {
                params: {
                    date_from: date,
                    date_to: date
                }
            });

            const employeesMap = {};
            response.data.forEach(row => {
                // Проверяем план: регистр и пробелы не важны («б/с» = «Б/С» = «БС»)
                const planType = row.plan_type ? row.plan_type.toUpperCase().replace(/[\s.]/g, '') : '';

                // Правило питания для сотрудника (кнопки «Добавить»/«Исключить»/«Замена»)
                const rule = overridesMap[normalizeName(row.employee_name)];
                const mode = rule ? rule.mode : '';

                // Отпуск, больничный и «б/с» в питание не попадают,
                // кроме сотрудников, добавленных кнопкой «Добавить»
                if (excludedPlanTypes.includes(planType) && mode !== 'include') {
                    return;
                }

                // Проверяем, есть ли данные для включения в список
                const hasPlan = planType && planType !== '';
                const hasFact = row.fact_hours > 0;
                const hasProductionStage = row.production_stage && row.production_stage.trim() !== '';

                if (!(hasPlan || hasFact || hasProductionStage)) {
                    return;
                }

                // Кнопка «Исключить»: не показываем даже при работе в графике
                if (mode === 'exclude') {
                    return;
                }

                // Кнопка «Замена»: вместо сотрудника показываем замену
                let displayName = row.employee_name;
                if (mode === 'replace' && rule.replacement) {
                    displayName = rule.replacement;
                }

                if (displayName && !employeesMap[displayName]) {
                    employeesMap[displayName] = {
                        name: displayName
                    };
                }
            });

            const employeesList = Object.values(employeesMap);
            employeesList.sort((a, b) => a.name.localeCompare(b.name, 'ru'));

            return employeesList;
        } catch (err) {
            console.error('❌ Ошибка получения данных:', err);
            return [];
        }
    };

    const handlePreview = async () => {
        if (!selectedDate) {
            showMessage('❌ Пожалуйста, выберите дату', 'error');
            return;
        }

        setLoading(true);
        setShowPreview(false);

        try {
            const employeesList = await getEmployeesForDate(selectedDate);

            if (employeesList.length === 0) {
                showMessage(`⚠️ Нет сотрудников с данными на ${selectedDate}`, 'warning');
                setPreviewData(null);
                setShowPreview(false);
            } else {
                setPreviewData({
                    date: selectedDate,
                    employees: employeesList
                });
                setShowPreview(true);
                showMessage(`✅ Найдено ${employeesList.length} сотрудников`, 'success');
            }
        } catch (err) {
            showMessage(`❌ Ошибка: ${err.message}`, 'error');
        }

        setLoading(false);
    };

    // Кнопка «Обновить» в общей шапке: перечитываем список, если он показан
    useEffect(() => {
        if (refreshToken && selectedDate && showPreview) {
            handlePreview();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [refreshToken]);

    const handleExport = async (mealType) => {
        if (!selectedDate) {
            showMessage('❌ Пожалуйста, выберите дату', 'error');
            return;
        }

        setExporting(true);
        const mealName = mealType === 'morning' ? 'Кафе утро (165 руб.)' : 'Кафе обед (460 руб.)';

        try {
            const response = await axios.post(`${API_URL}/export/meal/`, {
                date: selectedDate,
                meal_type: mealType
            }, {
                responseType: 'blob'
            });

            const contentType = response.headers['content-type'];
            if (contentType && contentType.includes('application/json')) {
                const text = await response.data.text();
                const data = JSON.parse(text);
                if (data.status === 'warning') {
                    showMessage(`⚠️ ${data.message}`, 'warning');
                    setExporting(false);
                    return;
                }
            }

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;

            const dateStr = selectedDate.replace(/-/g, '');
            const fileName = mealType === 'morning'
                ? `Кафе_утро_${dateStr}.xlsx`
                : `Кафе_обед_${dateStr}.xlsx`;

            link.setAttribute('download', fileName);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);

            showMessage(`✅ ${mealName} успешно выгружен`, 'success');
        } catch (err) {
            console.error('❌ Ошибка выгрузки:', err);
            showMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`, 'error');
        }

        setExporting(false);
    };

    const getMessageStyle = () => {
        const styles = {
            success: { background: '#d4edda', color: '#155724', border: '1px solid #c3e6cb' },
            error: { background: '#f8d7da', color: '#721c24', border: '1px solid #f5c6cb' },
            warning: { background: '#fff3cd', color: '#856404', border: '1px solid #ffc107' }
        };
        return styles[messageType] || styles.success;
    };

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            padding: '4px 0'
        }}>
            <h3 style={{ marginTop: 0, marginBottom: '12px', color: '#1565c0', fontSize: '20px' }}>🍽️ Выгрузка питания</h3>

            {message && (
                <div style={{
                    padding: '8px 15px',
                    borderRadius: '4px',
                    marginBottom: '12px',
                    ...getMessageStyle(),
                    fontSize: '14px'
                }}>
                    {message}
                </div>
            )}

            <div style={{
                display: 'flex',
                gap: '10px',
                alignItems: 'center',
                marginBottom: '12px',
                flexWrap: 'wrap',
                flexShrink: 0
            }}>
                <label style={{ fontWeight: 'bold', fontSize: '15px' }}>📅 Дата:</label>
                <input
                    type="date"
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    style={{
                        padding: '6px 12px',
                        border: '1px solid #ccc',
                        borderRadius: '4px',
                        fontSize: '15px'
                    }}
                />
                <button
                    onClick={handlePreview}
                    disabled={loading}
                    style={{
                        padding: '6px 20px',
                        background: loading ? '#ccc' : '#1565c0',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        fontSize: '15px',
                        opacity: loading ? 0.6 : 1
                    }}
                >
                    {loading ? '⏳ Загрузка...' : '🔍 Показать сотрудников'}
                </button>
            </div>

            {/* Правила питания: добавить, исключить, замена */}
            <div style={{
                display: 'flex',
                gap: '8px',
                alignItems: 'center',
                flexWrap: 'wrap',
                marginBottom: '12px',
                flexShrink: 0
            }}>
                <span style={{ color: '#555', fontSize: '13px' }}>Правила питания:</span>
                <button onClick={() => openDialog('include')}
                        title="Сотрудник будет попадать в список всегда, когда у него есть работа в графике"
                        style={ruleButtonStyle('#2e7d32')}>
                    ➕ Добавить
                </button>
                <button onClick={() => openDialog('exclude')}
                        title="Сотрудник не будет попадать в списки питания даже при работе в графике"
                        style={ruleButtonStyle('#c62828')}>
                    🚫 Исключить
                </button>
                <button onClick={() => openDialog('replace')}
                        title="Вместо сотрудника в список будет вписан другой"
                        style={ruleButtonStyle('#6a1b9a')}>
                    🔁 Замена
                </button>
                <span style={{ color: '#777', fontSize: '12px' }}>
                    добавлено: {overrides.filter(item => item.mode === 'include').length} ·
                    исключено: {overrides.filter(item => item.mode === 'exclude').length} ·
                    замен: {overrides.filter(item => item.mode === 'replace').length}
                </span>
            </div>

            {dialogMode && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0, 0, 0, 0.35)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000
                }}>
                    <div style={{
                        background: '#fff',
                        borderRadius: '8px',
                        width: '680px',
                        maxWidth: '95vw',
                        maxHeight: '85vh',
                        display: 'flex',
                        flexDirection: 'column',
                        padding: '16px',
                        boxShadow: '0 10px 30px rgba(0,0,0,0.25)'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <b style={{ fontSize: '16px' }}>
                                {dialogMode === 'include' && '➕ Добавить в питание'}
                                {dialogMode === 'exclude' && '🚫 Исключить из питания'}
                                {dialogMode === 'replace' && '🔁 Замена сотрудника'}
                            </b>
                            <button onClick={closeDialog} style={{
                                border: 'none', background: 'transparent', fontSize: '18px', cursor: 'pointer'
                            }}>✕</button>
                        </div>
                        <div style={{ color: '#666', fontSize: '12px', margin: '6px 0 10px' }}>
                            {dialogMode === 'include' && 'Выберите сотрудника — он будет попадать в список каждый раз, когда у него есть работа по графику.'}
                            {dialogMode === 'exclude' && 'Выберите сотрудника — он не будет попадать в списки питания даже при работе по графику.'}
                            {dialogMode === 'replace' && 'Выберите сотрудника и укажите, кто вписывается вместо него.'}
                        </div>
                        <input
                            placeholder="Поиск по ФИО…"
                            value={dialogSearch}
                            onChange={(e) => setDialogSearch(e.target.value)}
                            style={{
                                padding: '7px 10px', border: '1px solid #ccc', borderRadius: '4px', fontSize: '14px'
                            }}
                        />
                        <div style={{ overflowY: 'auto', marginTop: '10px', flex: 1, border: '1px solid #eee', borderRadius: '6px' }}>
                            {employees
                                .filter(emp => !dialogSearch || (emp.name || '').toLowerCase().includes(dialogSearch.toLowerCase()))
                                .map(emp => {
                                    const rule = overridesMap[normalizeName(emp.name)];
                                    const isReplacing = dialogMode === 'replace' && replaceTarget === emp.name;
                                    return (
                                        <div key={emp.id} style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '8px',
                                            padding: '6px 10px',
                                            borderBottom: '1px solid #f0f0f0'
                                        }}>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: '14px' }}>{emp.name}</div>
                                                <div style={{ fontSize: '11px', color: '#888' }}>
                                                    {[emp.department, emp.position].filter(Boolean).join(' · ')}
                                                </div>
                                            </div>
                                            {rule && (
                                                <span style={{ color: ruleColor(rule), fontSize: '12px', whiteSpace: 'nowrap' }}>
                                                    {ruleText(rule)}
                                                </span>
                                            )}
                                            {isReplacing ? (
                                                <>
                                                    <input
                                                        autoFocus
                                                        placeholder="ФИО замены"
                                                        value={replaceValue}
                                                        onChange={(e) => setReplaceValue(e.target.value)}
                                                        style={{
                                                            padding: '5px 8px', border: '1px solid #bbb',
                                                            borderRadius: '4px', fontSize: '13px', width: '190px'
                                                        }}
                                                    />
                                                    <button
                                                        onClick={() => saveRule(emp.name, 'replace', replaceValue)}
                                                        disabled={savingRule || !replaceValue.trim()}
                                                        style={ruleButtonStyle(replaceValue.trim() ? '#6a1b9a' : '#ccc')}
                                                    >
                                                        Сохранить
                                                    </button>
                                                </>
                                            ) : (
                                                <button
                                                    onClick={() => {
                                                        if (dialogMode === 'replace') {
                                                            setReplaceTarget(emp.name);
                                                            setReplaceValue(rule && rule.mode === 'replace' ? rule.replacement : '');
                                                        } else {
                                                            saveRule(emp.name, dialogMode);
                                                        }
                                                    }}
                                                    disabled={savingRule}
                                                    style={ruleButtonStyle(dialogMode === 'include' ? '#2e7d32' : dialogMode === 'exclude' ? '#c62828' : '#6a1b9a')}
                                                >
                                                    {dialogMode === 'include' ? 'Добавить' : dialogMode === 'exclude' ? 'Исключить' : 'Указать замену'}
                                                </button>
                                            )}
                                            {rule && (
                                                <button
                                                    onClick={() => saveRule(emp.name, 'none')}
                                                    disabled={savingRule}
                                                    title="Убрать правило"
                                                    style={{
                                                        border: '1px solid #ccc', background: '#fff', color: '#555',
                                                        borderRadius: '4px', padding: '4px 8px', cursor: 'pointer', fontSize: '13px'
                                                    }}
                                                >
                                                    ↺
                                                </button>
                                            )}
                                        </div>
                                    );
                                })}
                        </div>
                    </div>
                </div>
            )}

            {showPreview && previewData && (
                <div style={{
                    display: 'flex',
                    gap: '10px',
                    flexWrap: 'wrap',
                    marginBottom: '12px',
                    flexShrink: 0,
                    alignItems: 'center'
                }}>
                    <button
                        onClick={() => handleExport('morning')}
                        disabled={exporting}
                        style={{
                            padding: '8px 28px',
                            background: exporting ? '#ccc' : '#ff9800',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: exporting ? 'not-allowed' : 'pointer',
                            fontSize: '16px',
                            fontWeight: 'bold',
                            opacity: exporting ? 0.6 : 1,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px'
                        }}
                    >
                        <span>🌅</span> Кафе утро (165 руб.)
                    </button>

                    <button
                        onClick={() => handleExport('lunch')}
                        disabled={exporting}
                        style={{
                            padding: '8px 28px',
                            background: exporting ? '#ccc' : '#4caf50',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: exporting ? 'not-allowed' : 'pointer',
                            fontSize: '16px',
                            fontWeight: 'bold',
                            opacity: exporting ? 0.6 : 1,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px'
                        }}
                    >
                        <span>🍽️</span> Кафе обед (460 руб.)
                    </button>

                    <span style={{
                        fontSize: '16px',
                        color: '#666',
                        alignSelf: 'center',
                        marginLeft: '4px',
                        fontWeight: 'bold'
                    }}>
                        👥 {previewData.employees.length} чел.
                    </span>
                </div>
            )}

            {showPreview && previewData && (
                <div style={{
                    flex: 1,
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    padding: '12px 18px',
                    background: 'white',
                    overflow: 'auto',
                    minHeight: 0
                }}>
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: '6px 30px'
                    }}>
                        {previewData.employees.map((emp, idx) => (
                            <div key={idx} style={{
                                padding: '5px 0',
                                fontSize: '16px',
                                borderBottom: '1px solid #f0f0f0',
                                display: 'flex',
                                gap: '10px',
                                alignItems: 'center'
                            }}>
                                <span style={{
                                    color: '#999',
                                    minWidth: '35px',
                                    fontSize: '14px',
                                    fontWeight: '500'
                                }}>{idx + 1}.</span>
                                <span style={{ fontSize: '16px' }}>{emp.name}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {!showPreview && !loading && (
                <div style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#999',
                    fontSize: '17px',
                    border: '1px dashed #ddd',
                    borderRadius: '4px'
                }}>
                    Нажмите "Показать сотрудников" для отображения списка
                </div>
            )}
        </div>
    );
}

export default MealExport;