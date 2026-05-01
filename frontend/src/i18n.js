import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import ar from './locales/ar.json';
import en from './locales/en.json';

i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        resources: {
            ar: {
                translation: ar
            },
            en: {
                translation: en
            }
        },
        detection: {
            order: ['localStorage'], // Only rely on localStorage for persistence
            caches: ['localStorage'],
            lookupLocalStorage: 'i18nextLng'
        },
        fallbackLng: ['ar', 'en'],
        lng: localStorage.getItem('i18nextLng') || 'ar', // Force Arabic if no stored preference
        returnNull: false,
        returnEmptyString: false,
    });

// T9.4: expose the i18n singleton on `window` so non-React modules
// (e.g. `services/apiClient.js`) can read the active language without
// importing react-i18next. The apiClient injects `Accept-Language`
// on every request based on this value.
if (typeof window !== 'undefined') {
    window.i18next = i18n;
}

export default i18n;
