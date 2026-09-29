import React from 'react';
import { getMonths, MONTH_NAMES } from '../constants';

// Переключатель месяца: ◀ [месяц] ▶ (+ счётчик записей, если не compact)
function MonthSelector({ selectedMonth, onStepMonth, onSelectMonth, recordCount, compact }) {
    const months = getMonths();

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: compact ? '6px' : '8px',
            flexShrink: 0
        }}>
            {!compact && (
                <span style={{ fontSize: '11px', fontWeight: 'bold', color: '#333' }}>
                    📅 Месяц:
                </span>
            )}
            <button
                onClick={() => onStepMonth(-1)}
                style={{
                    padding: compact ? '2px 9px' : '2px 10px',
                    background: '#fff',
                    border: '1px solid #c6cdd6',
                    borderRadius: '3px',
                    cursor: 'pointer',
                    fontSize: '13px'
                }}
            >
                ◀
            </button>
            <select
                value={`${selectedMonth.year}-${String(selectedMonth.month + 1).padStart(2, '0')}`}
                onChange={(e) => {
                    const [year, month] = e.target.value.split('-').map(Number);
                    onSelectMonth(year, month);
                }}
                style={{
                    padding: compact ? '2px 6px' : '3px 8px',
                    borderRadius: '3px',
                    border: '1px solid #c6cdd6',
                    fontSize: '13px',
                    fontWeight: 'bold',
                    background: '#f5f7fa',
                    color: '#1565c0'
                }}
            >
                {months.map((m) => (
                    <option key={`${m.year}-${m.month}`} value={`${m.year}-${String(m.month + 1).padStart(2, '0')}`}>
                        {MONTH_NAMES[m.month]} {m.year}
                    </option>
                ))}
            </select>
            <button
                onClick={() => onStepMonth(1)}
                style={{
                    padding: compact ? '2px 9px' : '2px 10px',
                    background: '#fff',
                    border: '1px solid #c6cdd6',
                    borderRadius: '3px',
                    cursor: 'pointer',
                    fontSize: '13px'
                }}
            >
                ▶
            </button>
            {!compact && (
                <span style={{ fontSize: '10px', color: '#666', marginLeft: '5px' }}>
                    {recordCount > 0 ? `(${recordCount} записей)` : '(нет данных)'}
                </span>
            )}
        </div>
    );
}

export default MonthSelector;
