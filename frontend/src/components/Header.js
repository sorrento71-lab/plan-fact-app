import React from 'react';
import MonthSelector from './MonthSelector';
import UploadButtons from './UploadButtons';
import MessageBar from './MessageBar';
import PageTabs from './PageTabs';

// Единая верхняя панель (общая для всех страниц):
// слева — выбор месяца и вкладки (План-Факт / Табель / Питание),
// справа — загрузка «Журнал / График» и кнопка «Обновить».
function Header({
    selectedMonth,
    recordCount,
    onStepMonth,
    onSelectMonth,
    onRefresh,
    uploading,
    onUpload,
    uploadMessage,
    uploadStatus,
    activePage,
    onNavigate
}) {
    return (
        <div style={{
            flexShrink: 0,
            marginBottom: '4px',
            background: 'white',
            border: '1px solid #d7dde4',
            borderRadius: '6px',
            padding: '5px 10px'
        }}>
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '14px',
                flexWrap: 'wrap'
            }}>
                <MonthSelector
                    compact
                    selectedMonth={selectedMonth}
                    onStepMonth={onStepMonth}
                    onSelectMonth={onSelectMonth}
                    recordCount={recordCount}
                />

                <PageTabs activePage={activePage} onNavigate={onNavigate} />

                <div style={{
                    marginLeft: 'auto',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    flexWrap: 'wrap'
                }}>
                    <UploadButtons uploading={uploading} onUpload={onUpload} />
                    <button
                        onClick={onRefresh}
                        style={{
                            padding: '4px 12px',
                            background: '#1565c0',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '11px',
                            fontWeight: 'bold',
                            whiteSpace: 'nowrap'
                        }}
                    >
                        🔄 Обновить
                    </button>
                </div>
            </div>

            <MessageBar message={uploadMessage} />
            <MessageBar message={uploadStatus} />
        </div>
    );
}

export default Header;
