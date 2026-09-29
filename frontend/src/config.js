// src/config.js
const getApiUrl = () => {
    const hostname = window.location.hostname;

    // Если мы на удаленном сервере (не localhost)
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
        return `http://${hostname}:8000`;
    }
    return 'http://127.0.0.1:8000';
};

export const API_URL = getApiUrl();

console.log('🔧 Конфиг загружен. API_URL:', API_URL);