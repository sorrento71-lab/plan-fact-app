import React from 'react';

// Цветная строка-уведомление (успех / ошибка / предупреждение)
function MessageBar({ message }) {
    if (!message) return null;

    const isSuccess = message.includes('✅');
    const isError = message.includes('❌');

    return (
        <div style={{
            padding: '2px 8px',
            marginBottom: '3px',
            background: isSuccess ? '#d4edda' : isError ? '#f8d7da' : '#fff3cd',
            borderRadius: '3px',
            fontSize: '11px',
            color: isSuccess ? '#155724' : isError ? '#721c24' : '#856404',
            flexShrink: 0
        }}>
            {message}
        </div>
    );
}

export default MessageBar;
