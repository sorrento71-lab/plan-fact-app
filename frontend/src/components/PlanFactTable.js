import React, { useEffect, useRef } from 'react';
import { STATUS_COLORS, DAY_NAMES } from '../constants';

// Основная таблица план-факт: колонки № / ФИО / Должность и по 5 ячеек на день
// (План, Приход, Уход, Факт, Этапы) с редактированием времени и этапов по клику.
function PlanFactTable({
    employees,
    dates,
    colWidth,
    tableFontSize,
    selectedEmployee,
    editingCell,
    editingField,
    editValue,
    saving,
    onCellClick,
    onRowSelect,
    onTimeChange,
    onStageChange,
    onPlanChange,
    onEditKeyDown,
    onEditBlur
}) {
    const getStatusColor = (status) => STATUS_COLORS[status] || '#ffffff';

    // Прокрутка к выделенному сотруднику: если его строка вне видимой области —
    // подкручиваем к ней (если видна, прокрутка не трогается)
    const selectedRowRef = useRef(null);
    useEffect(() => {
        if (selectedEmployee && selectedRowRef.current) {
            selectedRowRef.current.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }, [selectedEmployee]);

    return (
        <div style={{
            flex: 1,
            overflow: 'auto',
            border: '1px solid #ddd',
            borderRadius: '4px',
            minHeight: 0
        }}>
            <table border="1" cellPadding="1" style={{
                borderCollapse: 'collapse',
                width: '100%',
                fontSize: `${tableFontSize}px`,
                tableLayout: 'fixed'
            }}>
                <thead>
                    <tr style={{ background: '#1565c0', color: 'white', position: 'sticky', top: 0, zIndex: 3 }}>
                        <th rowSpan="3" style={{
                            padding: '2px 2px',
                            minWidth: '24px',
                            width: '24px',
                            textAlign: 'center',
                            fontSize: '9px',
                            border: '1px solid #0d47a1',
                            position: 'sticky',
                            left: 0,
                            background: '#1565c0',
                            zIndex: 4
                        }}>
                            №
                        </th>
                        <th rowSpan="3" style={{
                            padding: '2px 4px',
                            minWidth: '100px',
                            width: '120px',
                            textAlign: 'left',
                            fontSize: '9px',
                            border: '1px solid #0d47a1',
                            position: 'sticky',
                            left: '24px',
                            background: '#1565c0',
                            zIndex: 4
                        }}>
                            ФИО
                        </th>
                        <th rowSpan="3" style={{
                            padding: '2px 4px',
                            minWidth: '70px',
                            width: '90px',
                            textAlign: 'left',
                            fontSize: '9px',
                            border: '1px solid #0d47a1',
                            position: 'sticky',
                            left: '124px',
                            background: '#1565c0',
                            zIndex: 4
                        }}>
                            Должность
                        </th>
                        {dates.map(date => {
                            const d = new Date(date);
                            const dayIndex = d.getDay() === 0 ? 6 : d.getDay() - 1;
                            return (
                                <th key={date} colSpan="5" style={{
                                    padding: '1px 1px',
                                    minWidth: `${colWidth * 5}px`,
                                    width: `${colWidth * 5}px`,
                                    textAlign: 'center',
                                    fontSize: `${Math.max(8, tableFontSize - 0)}px`,
                                    border: '1px solid #0d47a1'
                                }}>
                                    <div style={{ fontSize: `${Math.max(8, tableFontSize - 0)}px` }}>{d.getDate()}</div>
                                    <div style={{ fontSize: `${Math.max(7, tableFontSize - 1)}px`, fontWeight: 'normal' }}>
                                        {DAY_NAMES[dayIndex]}
                                    </div>
                                </th>
                            );
                        })}
                    </tr>
                    <tr style={{
                        background: '#e3f2fd',
                        color: '#0d47a1',
                        position: 'sticky',
                        top: '34px',
                        zIndex: 2,
                        fontSize: '7px',
                        fontWeight: 'bold'
                    }}>
                        {dates.map((date, idx) => (
                            <React.Fragment key={`subheader-${idx}`}>
                                <th style={{
                                    padding: '1px 1px',
                                    textAlign: 'center',
                                    border: '1px solid #90caf9',
                                    minWidth: `${colWidth}px`,
                                    width: `${colWidth}px`,
                                    fontSize: '7px'
                                }}>
                                    План
                                </th>
                                <th style={{
                                    padding: '1px 1px',
                                    textAlign: 'center',
                                    border: '1px solid #90caf9',
                                    minWidth: `${colWidth}px`,
                                    width: `${colWidth}px`,
                                    background: '#e8f0fe',
                                    fontSize: '7px'
                                }}>
                                    Приход
                                </th>
                                <th style={{
                                    padding: '1px 1px',
                                    textAlign: 'center',
                                    border: '1px solid #90caf9',
                                    minWidth: `${colWidth}px`,
                                    width: `${colWidth}px`,
                                    background: '#e8f0fe',
                                    fontSize: '7px'
                                }}>
                                    Уход
                                </th>
                                <th style={{
                                    padding: '1px 1px',
                                    textAlign: 'center',
                                    border: '1px solid #90caf9',
                                    minWidth: `${colWidth}px`,
                                    width: `${colWidth}px`,
                                    background: '#f5f5f5',
                                    fontSize: '7px'
                                }}>
                                    Факт
                                </th>
                                <th style={{
                                    padding: '1px 1px',
                                    textAlign: 'center',
                                    border: '1px solid #90caf9',
                                    minWidth: `${colWidth}px`,
                                    width: `${colWidth}px`,
                                    background: '#fce4ec',
                                    fontSize: '7px',
                                    color: '#c62828'
                                }}>
                                    Этапы
                                </th>
                            </React.Fragment>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {employees.map((emp, rowIndex) => {
                        const isRowSelected = selectedEmployee === emp.name;

                        return (
                            <tr key={rowIndex} ref={isRowSelected ? selectedRowRef : null} style={{
                                backgroundColor: isRowSelected ? '#e3f2fd' : 'transparent',
                                outline: isRowSelected ? '2px solid #1565c0' : 'none',
                                outlineOffset: isRowSelected ? '-1px' : '0'
                            }}>
                                <td
                                    onClick={() => onRowSelect(emp.name)}
                                    title="Кликните, чтобы выбрать сотрудника"
                                    style={{
                                        textAlign: 'center',
                                        padding: '1px 1px',
                                        fontSize: `${Math.max(8, tableFontSize - 0)}px`,
                                        border: '1px solid #ddd',
                                        position: 'sticky',
                                        left: 0,
                                        background: isRowSelected ? '#e3f2fd' : 'white',
                                        zIndex: 1,
                                        borderRight: isRowSelected ? '2px solid #1565c0' : '1px solid #ddd',
                                        cursor: 'pointer'
                                    }}
                                >
                                    {rowIndex + 1}
                                </td>
                                <td
                                    onClick={() => onRowSelect(emp.name)}
                                    title="Кликните, чтобы выбрать сотрудника"
                                    style={{
                                        padding: '1px 3px',
                                        fontSize: `${Math.max(8, tableFontSize - 0)}px`,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        border: '1px solid #ddd',
                                        position: 'sticky',
                                        left: '24px',
                                        background: isRowSelected ? '#e3f2fd' : 'white',
                                        zIndex: 1,
                                        borderRight: isRowSelected ? '2px solid #1565c0' : '1px solid #ddd',
                                        cursor: 'pointer'
                                    }}
                                >
                                    <strong>{emp.name}</strong>
                                </td>
                                <td
                                    onClick={() => onRowSelect(emp.name)}
                                    title="Кликните, чтобы выбрать сотрудника"
                                    style={{
                                        padding: '1px 3px',
                                        fontSize: `${Math.max(7, tableFontSize - 1)}px`,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        border: '1px solid #ddd',
                                        position: 'sticky',
                                        left: '124px',
                                        background: isRowSelected ? '#e3f2fd' : 'white',
                                        zIndex: 1,
                                        borderRight: isRowSelected ? '2px solid #1565c0' : '1px solid #ddd',
                                        cursor: 'pointer'
                                    }}
                                >
                                    {emp.position}
                                </td>
                                {dates.map(date => {
                                    const dayData = emp.days[date];
                                    const plan = dayData?.plan || '';
                                    const fact_hours = dayData?.fact || 0;
                                    const start_time = dayData?.start_time || '';
                                    const end_time = dayData?.end_time || '';
                                    const production_stage = dayData?.production_stage || '';
                                    const status = dayData?.status || 'Нет данных';
                                    const bgColor = getStatusColor(status);
                                    const textColor = status === 'Отсутствует' ? 'white' : '#333';

                                    const isEditingStart = editingCell &&
                                        editingCell.employeeName === emp.name &&
                                        editingCell.date === date &&
                                        editingField === 'start_time';

                                    const isEditingEnd = editingCell &&
                                        editingCell.employeeName === emp.name &&
                                        editingCell.date === date &&
                                        editingField === 'end_time';

                                    const isEditingStage = editingCell &&
                                        editingCell.employeeName === emp.name &&
                                        editingCell.date === date &&
                                        editingField === 'production_stage';

                                    const isEditingPlan = editingCell &&
                                        editingCell.employeeName === emp.name &&
                                        editingCell.date === date &&
                                        editingField === 'plan_type';

                                    const cellBorderStyle = isRowSelected ? '2px solid #1565c0' : '1px solid #ddd';

                                    return (
                                        <React.Fragment key={date}>
                                            <td
                                                style={{
                                                    textAlign: 'center',
                                                    backgroundColor: isEditingPlan ? '#fff9c4' : bgColor,
                                                    color: textColor,
                                                    padding: '1px 1px',
                                                    fontWeight: plan ? 'bold' : 'normal',
                                                    fontSize: `${Math.max(7, tableFontSize - 1)}px`,
                                                    border: cellBorderStyle,
                                                    minWidth: `${colWidth}px`,
                                                    width: `${colWidth}px`,
                                                    cursor: 'pointer'
                                                }}
                                                onClick={() => onCellClick(emp.name, date, 'plan_type', plan)}
                                                title="Кликните для редактирования плана (график)"
                                            >
                                                {isEditingPlan ? (
                                                    <input
                                                        type="text"
                                                        value={editValue}
                                                        onChange={onPlanChange}
                                                        onKeyDown={onEditKeyDown}
                                                        onBlur={onEditBlur}
                                                        autoFocus
                                                        placeholder="—"
                                                        style={{
                                                            width: '100%',
                                                            border: 'none',
                                                            background: 'transparent',
                                                            textAlign: 'center',
                                                            fontSize: 'inherit',
                                                            fontWeight: 'bold',
                                                            outline: 'none',
                                                            color: '#333'
                                                        }}
                                                        disabled={saving}
                                                    />
                                                ) : (
                                                    plan
                                                )}
                                            </td>
                                            <td
                                                style={{
                                                    textAlign: 'center',
                                                    padding: '1px 1px',
                                                    fontSize: `${Math.max(6, tableFontSize - 2)}px`,
                                                    border: cellBorderStyle,
                                                    backgroundColor: isEditingStart ? '#fff9c4' : (start_time ? '#e8f5e9' : 'transparent'),
                                                    minWidth: `${colWidth}px`,
                                                    width: `${colWidth}px`,
                                                    cursor: 'pointer'
                                                }}
                                                onClick={() => onCellClick(emp.name, date, 'start_time', start_time)}
                                                title="Кликните для редактирования прихода"
                                            >
                                                {isEditingStart ? (
                                                    <input
                                                        type="text"
                                                        value={editValue}
                                                        onChange={onTimeChange}
                                                        onKeyDown={onEditKeyDown}
                                                        onBlur={onEditBlur}
                                                        autoFocus
                                                        placeholder="__:__"
                                                        style={{
                                                            width: '100%',
                                                            border: 'none',
                                                            background: 'transparent',
                                                            textAlign: 'center',
                                                            fontSize: 'inherit',
                                                            fontWeight: 'bold',
                                                            outline: 'none',
                                                            color: '#1a237e'
                                                        }}
                                                        disabled={saving}
                                                    />
                                                ) : (
                                                    start_time
                                                )}
                                            </td>
                                            <td
                                                style={{
                                                    textAlign: 'center',
                                                    padding: '1px 1px',
                                                    fontSize: `${Math.max(6, tableFontSize - 2)}px`,
                                                    border: cellBorderStyle,
                                                    backgroundColor: isEditingEnd ? '#fff9c4' : (end_time ? '#fff3e0' : 'transparent'),
                                                    minWidth: `${colWidth}px`,
                                                    width: `${colWidth}px`,
                                                    cursor: 'pointer'
                                                }}
                                                onClick={() => onCellClick(emp.name, date, 'end_time', end_time)}
                                                title="Кликните для редактирования ухода"
                                            >
                                                {isEditingEnd ? (
                                                    <input
                                                        type="text"
                                                        value={editValue}
                                                        onChange={onTimeChange}
                                                        onKeyDown={onEditKeyDown}
                                                        onBlur={onEditBlur}
                                                        autoFocus
                                                        placeholder="__:__"
                                                        style={{
                                                            width: '100%',
                                                            border: 'none',
                                                            background: 'transparent',
                                                            textAlign: 'center',
                                                            fontSize: 'inherit',
                                                            fontWeight: 'bold',
                                                            outline: 'none',
                                                            color: '#1a237e'
                                                        }}
                                                        disabled={saving}
                                                    />
                                                ) : (
                                                    end_time
                                                )}
                                            </td>
                                            <td style={{
                                                textAlign: 'center',
                                                padding: '1px 1px',
                                                fontSize: `${Math.max(7, tableFontSize - 1)}px`,
                                                fontWeight: fact_hours > 0 ? 'bold' : 'normal',
                                                border: cellBorderStyle,
                                                backgroundColor: fact_hours > 0 ? '#e3f2fd' : '#f5f5f5',
                                                minWidth: `${colWidth}px`,
                                                width: `${colWidth}px`
                                            }}>
                                                {fact_hours > 0 ? `${fact_hours}ч` : ''}
                                            </td>
                                            <td
                                                style={{
                                                    textAlign: 'center',
                                                    padding: '1px 1px',
                                                    fontSize: `${Math.max(6, tableFontSize - 2)}px`,
                                                    border: cellBorderStyle,
                                                    backgroundColor: isEditingStage ? '#fff9c4' : (production_stage ? '#fff9c4' : 'transparent'),
                                                    minWidth: `${colWidth}px`,
                                                    width: `${colWidth}px`,
                                                    cursor: 'pointer',
                                                    color: production_stage ? '#333' : '#999'
                                                }}
                                                onClick={() => onCellClick(emp.name, date, 'production_stage', production_stage)}
                                                title="Кликните для редактирования этапов производства"
                                            >
                                                {isEditingStage ? (
                                                    <input
                                                        type="text"
                                                        value={editValue}
                                                        onChange={onStageChange}
                                                        onKeyDown={onEditKeyDown}
                                                        onBlur={onEditBlur}
                                                        autoFocus
                                                        placeholder="..."
                                                        style={{
                                                            width: '100%',
                                                            border: 'none',
                                                            background: 'transparent',
                                                            textAlign: 'center',
                                                            fontSize: 'inherit',
                                                            fontWeight: 'bold',
                                                            outline: 'none',
                                                            color: '#333'
                                                        }}
                                                        disabled={saving}
                                                    />
                                                ) : (
                                                    production_stage || '—'
                                                )}
                                            </td>
                                        </React.Fragment>
                                    );
                                })}
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

export default PlanFactTable;
