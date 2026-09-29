import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL } from './config';

// Страница «Медосмотр»: выбор даты как в «Питании», список людей со сменами
// этого месяца (до ноября 2026 — 11/9/8, с ноября 2026 — «Я» и «В») на эту дату
// (или за весь месяц) и выгрузка списка в файл (Приложение Б).
function MedCheckExport({ year, month, refreshToken }) {
    const [selectedDate, setSelectedDate] = useState('');
    const [wholeMonth, setWholeMonth] = useState(false);
    const [info, setInfo] = useState(null);
    const [loading, setLoading] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [message, setMessage] = useState('');
    const [messageType, setMessageType] = useState('success');

    const showMessage = (text, type = 'success') => {
        setMessage(text);
        setMessageType(type);
        setTimeout(() => {
            setMessage('');
            setMessageType('');
        }, 6000);
    };

    // дата по умолчанию — сегодня; при смене месяца в шапке переходим на 1-е число
    useEffect(() => {
        const now = new Date();
        if (now.getFullYear() === year && now.getMonth() === month && !selectedDate) {
            setSelectedDate(`${year}-${String(month + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`);
        } else if (!selectedDate || Number(selectedDate.slice(0, 4)) !== year || Number(selectedDate.slice(5, 7)) !== month + 1) {
            setSelectedDate(`${year}-${String(month + 1).padStart(2, '0')}-01`);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [year, month]);

    const dateParts = selectedDate
        ? selectedDate.split('-').map(Number)
        : [year, month + 1, 1];
    const [selYear, selMonth, selDay] = dateParts;
    const dateLabel = selectedDate
        ? `${String(selDay).padStart(2, '0')}.${String(selMonth).padStart(2, '0')}.${selYear}`
        : '';
    const monthLabel = `${String(selMonth).padStart(2, '0')}.${selYear}`;

    const loadInfo = async () => {
        if (!selectedDate) return;
        setLoading(true);
        try {
            const params = { year: selYear, month: selMonth };
            if (!wholeMonth) params.day = selDay;
            const response = await axios.get(`${API_URL}/medcheck/summary/`, { params });
            setInfo(response.data);
        } catch (err) {
            setInfo(null);
            showMessage(`⚠️ ${err.response?.data?.detail || err.message}`, 'warning');
        }
        setLoading(false);
    };

    useEffect(() => {
        loadInfo();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedDate, wholeMonth, refreshToken]);

    const handleExport = async () => {
        if (!selectedDate) {
            showMessage('❌ Выберите дату', 'error');
            return;
        }
        setExporting(true);
        try {
            const params = { year: selYear, month: selMonth };
            if (!wholeMonth) params.day = selDay;
            const response = await axios.get(`${API_URL}/export/medcheck/`, {
                params,
                responseType: 'blob'
            });

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            const suffix = wholeMonth ? '' : `_${String(selDay).padStart(2, '0')}`;
            link.setAttribute('download', `Медосмотр_${monthLabel}${suffix}.docx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);

            showMessage(`✅ Список выгружен: ${wholeMonth ? monthLabel : dateLabel}`, 'success');
        } catch (err) {
            let detail = err.response?.data?.detail;
            if (err.response?.data instanceof Blob) {
                try {
                    detail = JSON.parse(await err.response.data.text()).detail;
                } catch (e) {
                    detail = null;
                }
            }
            showMessage(`❌ ${detail || err.message}`, 'error');
        }
        setExporting(false);
    };

    const messageStyle = {
        success: { background: '#d4edda', color: '#155724', border: '1px solid #c3e6cb' },
        error: { background: '#f8d7da', color: '#721c24', border: '1px solid #f5c6cb' },
        warning: { background: '#fff3cd', color: '#856404', border: '1px solid #ffc107' }
    }[messageType] || {};

    const total = info ? info.employees : 0;
    const hasData = !!(info && info.rows && info.rows.length);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '4px 0' }}>
            <h3 style={{ marginTop: 0, marginBottom: '12px', color: '#00838f', fontSize: '20px' }}>
                🩺 Выгрузка медосмотра
            </h3>

            {message && (
                <div style={{ padding: '8px 15px', borderRadius: '4px', marginBottom: '12px', fontSize: '14px', ...messageStyle }}>
                    {message}
                </div>
            )}

            <div style={{
                display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap',
                marginBottom: '12px', flexShrink: 0, fontSize: '15px'
            }}>
                <label style={{ fontWeight: 'bold' }}>📅 Дата:</label>
                <input
                    type="date"
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    style={{ padding: '6px 12px', border: '1px solid #ccc', borderRadius: '4px', fontSize: '15px' }}
                />
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={wholeMonth}
                        onChange={(e) => setWholeMonth(e.target.checked)}
                        style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                    весь месяц
                </label>
                {loading
                    ? <span style={{ color: '#1565c0' }}>⏳ считаю…</span>
                    : <span>В списке: <b>{total}</b> чел.
                        {hasData && ` (${Object.entries(info.by_shift || {})
                            .map(([code, count]) => `${code} — ${count}`)
                            .join(', ')})`}
                      </span>}
            </div>

            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', flexShrink: 0, marginBottom: '12px' }}>
                <button
                    onClick={handleExport}
                    disabled={exporting || !hasData}
                    title="Сформировать график прохождения медицинских осмотров (Приложение Б) по текущему списку"
                    style={{
                        padding: '10px 30px',
                        background: (exporting || !hasData) ? '#ccc' : '#00838f',
                        color: 'white', border: 'none', borderRadius: '6px',
                        cursor: (exporting || !hasData) ? 'not-allowed' : 'pointer',
                        fontSize: '16px', fontWeight: 'bold'
                    }}
                >
                    {exporting ? '⏳ Формирую документ…'
                        : `📄 Выгрузить список ${wholeMonth ? `за ${monthLabel}` : `на ${dateLabel}`}`}
                </button>
            </div>

            <div style={{
                flex: 1, padding: '12px 18px', background: 'white',
                border: '1px solid #ddd', borderRadius: '4px', overflow: 'auto', minHeight: 0
            }}>
                {hasData ? (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 30px' }}>
                        {info.rows.map((row, idx) => (
                            <div key={idx} style={{
                                display: 'flex', gap: '10px', alignItems: 'center',
                                padding: '5px 0', fontSize: '15px', borderBottom: '1px solid #f0f0f0'
                            }}>
                                <span style={{ color: '#999', minWidth: '35px', fontSize: '14px' }}>{idx + 1}.</span>
                                <span>{row.name}</span>
                                <span style={{ color: '#888', fontSize: '13px' }}>{row.position}</span>
                                <span style={{ color: '#00838f', fontSize: '13px', marginLeft: 'auto' }}>
                                    {row.shifts.join('/')}{wholeMonth ? ` · ${row.days} дн.` : ''}
                                </span>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div style={{ color: '#999', fontSize: '16px' }}>
                        {loading ? 'Считаю…'
                            : `Список пуст: ${wholeMonth ? `за ${monthLabel}` : `на ${dateLabel}`} в графике нет смен 11, 9 или 8`}
                    </div>
                )}
            </div>
        </div>
    );
}

export default MedCheckExport;
