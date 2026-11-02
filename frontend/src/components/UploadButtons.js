import React from 'react';

// Кнопки загрузки файлов в верхней панели: Журнал, затем График
function UploadButtons({ uploading, onUpload }) {
    const buttonBase = {
        padding: '3px 12px',
        color: 'white',
        border: 'none',
        borderRadius: '4px',
        cursor: uploading ? 'not-allowed' : 'pointer',
        fontSize: '11px',
        display: 'inline-block',
        fontWeight: 'bold',
        whiteSpace: 'nowrap'
    };

    return (
        <div style={{
            display: 'flex',
            gap: '6px',
            flexShrink: 0
        }}>
            <label
                title="Загрузить журнал из СКУД (выгрузка tc-tmp*.xls)"
                style={{ ...buttonBase, background: uploading ? '#ccc' : '#ff9800' }}
            >
                📤 Журнал
                <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={(e) => onUpload(e, 'journal')}
                    disabled={uploading}
                    style={{ display: 'none' }}
                />
            </label>

            {/* Кнопка «График» убрана: загрузка графика — только на странице
                «График», где выбирается месяц и сразу обновляются лист и план */}
        </div>
    );
}

export default UploadButtons;
