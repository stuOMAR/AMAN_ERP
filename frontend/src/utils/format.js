/**
 * AMAN ERP - Global Formatting Utilities
 */

import { getCurrency, getUser } from './auth';

const normalizeDecimalString = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const raw = String(value).trim();
    if (!/^-?\d+(\.\d+)?$/.test(raw)) return raw || null;

    const negative = raw.startsWith('-');
    const unsigned = negative ? raw.slice(1) : raw;
    const [intPart, fracPart = ''] = unsigned.split('.');
    const cleanedInt = intPart.replace(/^0+(?=\d)/, '') || '0';
    return `${negative ? '-' : ''}${cleanedInt}${fracPart ? `.${fracPart}` : ''}`;
};

/**
 * Formats a decimal string according to the company's decimal precision.
 * Backend calculations are already rounded; this helper only pads/trims and
 * groups digits without converting money to a JavaScript number.
 * @param {number|string} value - Decimal value to format.
 * @param {number} [overridePrecision] - Optional display precision.
 * @returns {string} Formatted number.
 */
export const formatNumber = (value, overridePrecision = null) => {
    const user = getUser();
    const precision = overridePrecision !== null ? overridePrecision : (user?.decimal_places !== undefined ? user.decimal_places : 2);
    const normalized = normalizeDecimalString(value);
    if (normalized === null) return '0';
    if (!/^-?\d+(\.\d+)?$/.test(normalized)) return normalized;

    const negative = normalized.startsWith('-');
    const unsigned = negative ? normalized.slice(1) : normalized;
    const [intPart, fracPart = ''] = unsigned.split('.');
    const groupedInt = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    const fraction = precision > 0 ? `.${(fracPart + '0'.repeat(precision)).slice(0, precision)}` : '';
    return `${negative ? '-' : ''}${groupedInt}${fraction}`;
};

/**
 * Formats a currency value with the currency symbol.
 * @param {number|string} value - The amount.
 * @param {string} [currency] - Optional currency code.
 * @returns {string} Formatted currency.
 */
export const formatCurrency = (value, currency = null) => {
    const curr = currency || getCurrency() || '';
    return `${formatNumber(value)} ${curr}`;
};

/**
 * Gets the numeric step value for inputs based on decimal precision.
 * @returns {string} Step value (e.g., "0.01", "0.0001").
 */
export const getStep = () => {
    const user = getUser();
    const precision = user?.decimal_places !== undefined ? user.decimal_places : 2;
    if (precision <= 0) return "1";
    return `0.${'0'.repeat(Math.max(precision - 1, 0))}1`;
};
