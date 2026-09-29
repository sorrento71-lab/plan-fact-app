import React from 'react';

const TABS = [
    { id: 'planfact', label: '📊 План-Факт', activeColor: '#1565c0', borderColor: '#0d47a1' },
    { id: 'timesheet', label: '📋 Табель', activeColor: '#e74c3c', borderColor: '#c0392b' },
    { id: 'meal', label: '🍽️ Питание', activeColor: '#9c27b0', borderColor: '#6a1b9a' },
    { id: 'schedule', label: '📅 График', activeColor: '#00838f', borderColor: '#006064' },
    { id: 'medcheck', label: '🩺 Медосмотр', activeColor: '#00897b', borderColor: '#00695c' },
];

// Вкладки страниц: План-Факт / Табель / Питание / График / Медосмотр
function PageTabs({ activePage, onNavigate }) {
    return (
        <div style={{
            display: 'flex',
            gap: '2px',
            flexShrink: 0,
            background: '#f0f2f5',
            borderRadius: '5px',
            padding: '2px'
        }}>
            {TABS.map((tab) => {
                const isActive = activePage === tab.id;
                return (
                    <button
                        key={tab.id}
                        onClick={() => onNavigate(tab.id)}
                        style={{
                            padding: '4px 14px',
                            background: isActive ? tab.activeColor : 'transparent',
                            color: isActive ? 'white' : '#333',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '12px',
                            fontWeight: isActive ? 'bold' : 'normal',
                            whiteSpace: 'nowrap'
                        }}
                    >
                        {tab.label}
                    </button>
                );
            })}
        </div>
    );
}

export default PageTabs;
