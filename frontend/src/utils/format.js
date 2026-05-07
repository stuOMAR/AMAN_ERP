/**
 * AMAN ERP - Global Formatting Utilities
 */

import { getCurrency, getUser } from './auth';

/**
 * Formats a number according to the company's decimal precision setting.
 * @param {number|string} value - The number to format.
 * @param {number} [overridePrecision] - Optional override for precision.
 * @returns {string} Formatted number.
 */
export const formatNumber = (value, overridePrecision = null) => {
    const user = getUser();
    const precision = overridePrecision !== null ? overridePrecision : (user?.decimal_places !== undefined ? user.decimal_places : 2);

    // T10.2 #256: ``parseFloat`` silently truncates precision for values
    // beyond ~15 significant digits (Number.MAX_SAFE_INTEGER = 2^53-1).
    // Backend can emit BigInt-shaped strings for monetary fields with
    // many digits; in that case render via ``Intl.NumberFormat`` on the
    // BigInt path so we don't drop digits.
    if (typeof value === "string" && /^-?\d{16,}(\.\d+)?$/.test(value.trim())) {
        try {
            const [intPart, fracPart = ""] = value.trim().split(".");
            const formattedInt = new Intl.NumberFormat().format(BigInt(intPart));
            const frac = (fracPart + "0".repeat(precision)).slice(0, precision);
            return precision > 0 ? `${formattedInt}.${frac}` : formattedInt;
        } catch {
            // fall through to parseFloat path
        }
    }

    const num = parseFloat(value);
    if (isNaN(num)) return '0';

    return num.toLocaleString(undefined, {
        minimumFractionDigits: precision,
        maximumFractionDigits: precision,
    });
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
    return (1 / Math.pow(10, precision)).toFixed(precision);
};
