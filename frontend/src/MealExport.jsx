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

    // Список сотрудников для исключения
    const excludedEmployees = ['Корнеева Елена'];
    // Планы, при которых сотрудник в питание не попадает:
    // «О» — отпуск, «Б» — больничный, «Б/С» — без сохранения заработной платы.
    const excludedPlanTypes = ['О', 'Б', 'Б/Л', 'БЛ', 'Б/С', 'БС'];

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

                // Исключаем отпуск («О») и «б/с» — те же правила, что в выгрузке
                if (excludedPlanTypes.includes(planType)) {
                    return; // пропускаем этого сотрудника
                }

                // Проверяем, есть ли данные для включения в список
                const hasPlan = planType && planType !== '';
                const hasFact = row.fact_hours > 0;
                const hasProductionStage = row.production_stage && row.production_stage.trim() !== '';

                // Проверяем, не исключен ли сотрудник по имени
                const isExcluded = excludedEmployees.some(name =>
                    row.employee_name && row.employee_name.includes(name)
                );

                if ((hasPlan || hasFact || hasProductionStage) && !isExcluded) {
                    // ФИО выводим как в справочнике — подмены имён больше нет
                    const displayName = row.employee_name;
                    if (!employeesMap[displayName]) {
                        employeesMap[displayName] = {
                            name: displayName
                        };
                    }
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