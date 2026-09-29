import React from 'react';
import { STATUS_COLORS } from '../constants';

// Легенда статусов и подсказки по редактированию
function Legend() {
    return (
        <div style={{
            marginTop: '2px',
            display: 'flex',
            gap: '6px',
            flexWrap: 'wrap',
            alignItems: 'center',
            fontSize: '9px',
            flexShrink: 0,
            padding: '2px 0',
            minHeight: '20px'
        }}>
            <span style={{ fontWeight: 'bold' }}>📌 Легенда:</span>
            {Object.entries(STATUS_COLORS).map(([status, color]) => (
                <span key={status} style={{ fontSize: '8px' }}>
                    <span style={{ background: color, padding: '1px 4px', borderRadius: '2px', border: '1px solid #ccc' }}>
                        {status}
                    </span>
                </span>
            ))}
            <span style={{ marginLeft: '6px', fontSize: '8px', color: '#666' }}>
                🖱️ Клик по времени или этапам для редактирования
            </span>
            <span style={{ marginLeft: '6px', fontSize: '8px', color: '#666' }}>
                <span style={{ background: '#fff9c4', padding: '1px 4px', borderRadius: '2px', border: '1px solid #ccc' }}>
                    🟡 Заполнено
                </span>
            </span>
            <span style={{ marginLeft: '6px', fontSize: '8px', color: '#1565c0' }}>
                <span style={{ background: '#e3f2fd', padding: '1px 4px', borderRadius: '2px', border: '2px solid #1565c0' }}>
                    🔵 Выделена
                </span>
            </span>
        </div>
    );
}

export default Legend;
