import { useState } from 'react';
import axios from 'axios';
import { API_URL } from '../config';

const TIME_REGEX = /^([0-1][0-9]|2[0-3]):[0-5][0-9]$/;

// Логика редактирования ячеек таблицы: план / приход / уход / этап производства.
// Инкапсулирует состояние редактирования и все обработчики.
export default function useCellEditing({ onSaved, setUploadMessage }) {
    const [editingCell, setEditingCell] = useState(null);
    const [editValue, setEditValue] = useState('');
    const [saving, setSaving] = useState(false);
    const [editingField, setEditingField] = useState('');
    // Выделенный сотрудник хранится по ИМЕНИ, чтобы выделение не терялось
    // после перезагрузки данных (порядок строк может измениться).
    const [selectedEmployee, setSelectedEmployee] = useState(null);

    // Полный сброс — отмена редактирования (Escape)
    const resetEditing = () => {
        setEditingCell(null);
        setEditValue('');
        setEditingField('');
        setSelectedEmployee(null);
    };

    // Сброс только редактирования: выделение сотрудника сохраняется,
    // чтобы после сохранения было видно, кого редактировали
    const clearEditing = () => {
        setEditingCell(null);
        setEditValue('');
        setEditingField('');
    };

    const showMessage = (message) => {
        setUploadMessage(message);
        setTimeout(() => setUploadMessage(''), 3000);
    };

    const saveTime = async (employeeName, dateStr, field, value) => {
        setSaving(true);
        try {
            const response = await axios.post(`${API_URL}/update-time/`, {
                employee_name: employeeName,
                date: dateStr,
                field: field,
                value: value
            });

            if (response.data.status === 'success') {
                showMessage(`✅ Обновлено: ${employeeName} | ${dateStr} | ${field === 'start_time' ? 'Приход' : 'Уход'} = ${value}`);
                await onSaved();
            }
        } catch (err) {
            console.error('❌ Ошибка сохранения:', err);
            showMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
        }
        setSaving(false);
        clearEditing();
    };

    const saveProductionStage = async (employeeName, dateStr, value) => {
        setSaving(true);
        try {
            const response = await axios.post(`${API_URL}/update-production-stage/`, {
                employee_name: employeeName,
                date: dateStr,
                value: value
            });

            if (response.data.status === 'success') {
                showMessage(`✅ Обновлен этап: ${employeeName} | ${dateStr} = ${value || '(пусто)'}`);
                await onSaved();
            }
        } catch (err) {
            console.error('❌ Ошибка сохранения этапа:', err);
            showMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
        }
        setSaving(false);
        clearEditing();
    };

    const savePlan = async (employeeName, dateStr, value) => {
        setSaving(true);
        try {
            const response = await axios.post(`${API_URL}/update-plan/`, {
                employee_name: employeeName,
                date: dateStr,
                value: value
            });

            if (response.data.status === 'success') {
                showMessage(`✅ ${response.data.message || `Обновлен план: ${employeeName} | ${dateStr} = ${value || '(пусто)'}`}`);
                await onSaved();
            }
        } catch (err) {
            console.error('❌ Ошибка сохранения плана:', err);
            showMessage(`❌ Ошибка: ${err.response?.data?.detail || err.message}`);
        }
        setSaving(false);
        clearEditing();
    };

    const handleCellClick = (employeeName, date, field, currentValue) => {
        setSelectedEmployee(employeeName);
        setEditingCell({ employeeName, date });
        setEditingField(field);
        setEditValue(currentValue || '');
    };

    const handleEditChange = (e) => {
        let value = e.target.value;
        if (editingField === 'start_time' || editingField === 'end_time') {
            value = value.replace(/[^0-9:]/g, '');
            if (value.length === 2 && !value.includes(':')) {
                value = value + ':';
            }
            if (value.length === 5 && value.charAt(2) !== ':') {
                value = value.substring(0, 2) + ':' + value.substring(2);
            }
            if (value.length > 5) {
                value = value.substring(0, 5);
            }
        }
        setEditValue(value);
    };

    const handleStageChange = (e) => {
        setEditValue(e.target.value);
    };

    // Ввод плана (графика): без маски времени, как и этапы
    const handlePlanChange = (e) => {
        setEditValue(e.target.value);
    };

    // Выбор строки таблицы (без начала редактирования) — для кнопки удаления
    const handleRowSelect = (employeeName) => {
        setSelectedEmployee(employeeName);
    };

    const handleEditKeyDown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();

            if (editingField === 'production_stage') {
                saveProductionStage(
                    editingCell.employeeName,
                    editingCell.date,
                    editValue
                );
                return;
            }

            if (editingField === 'plan_type') {
                savePlan(
                    editingCell.employeeName,
                    editingCell.date,
                    editValue
                );
                return;
            }

            if (TIME_REGEX.test(editValue) || editValue === '') {
                saveTime(
                    editingCell.employeeName,
                    editingCell.date,
                    editingField,
                    editValue
                );
            } else {
                showMessage('❌ Неверный формат времени. Используйте HH:MM (например, 08:00)');
            }
        } else if (e.key === 'Escape') {
            resetEditing();
        }
    };

    const handleEditBlur = () => {
        if (!editingCell) return;

        if (editingField === 'production_stage') {
            saveProductionStage(
                editingCell.employeeName,
                editingCell.date,
                editValue
            );
            return;
        }

        if (editingField === 'plan_type') {
            savePlan(
                editingCell.employeeName,
                editingCell.date,
                editValue
            );
            return;
        }

        if (TIME_REGEX.test(editValue) || editValue === '') {
            saveTime(
                editingCell.employeeName,
                editingCell.date,
                editingField,
                editValue
            );
        } else {
            resetEditing();
            showMessage('❌ Неверный формат времени. Используйте HH:MM');
        }
    };

    return {
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
    };
}
