/**
 * Shared Axios instance with interceptors.
 * All service files import `api` from here.
 */
import axios from 'axios'
import { toastEmitter } from '../utils/toastEmitter'
import { requestManager } from '../utils/requestManager'
import { getToken as memGetToken, setToken as memSetToken, clearToken as memClearToken } from '../utils/tokenStore'

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || '/api',
    headers: {
        'Content-Type': 'application/json'
    },
    // TASK-030: send cookies on same-origin/CORS requests so the HttpOnly
    // refresh-token cookie and the readable csrf_token cookie are attached.
    withCredentials: true
})

// TASK-030: CSRF — read the `csrf_token` cookie on every mutating request
// and echo it in the `X-CSRF-Token` header (double-submit pattern).
function readCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/[.$?*|{}()[\]\\/+^]/g, '\\$&') + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
}

const MUTATING_METHODS = new Set(['post', 'put', 'patch', 'delete']);

// --- Token Refresh Mutex ---
// Prevents multiple concurrent 401s from each trying to refresh (and rotate/blacklist) the token.
// The first 401 triggers a refresh; subsequent 401s wait for the same promise.
let isRefreshing = false;
let refreshSubscribers = [];

function onRefreshed(newToken) {
    refreshSubscribers.forEach(cb => cb(newToken));
    refreshSubscribers = [];
}

function onRefreshFailed() {
    refreshSubscribers.forEach(cb => cb(null));
    refreshSubscribers = [];
}

function subscribeTokenRefresh(cb) {
    return new Promise((resolve) => {
        refreshSubscribers.push((token) => {
            resolve(cb(token));
        });
    });
}

// Decode JWT payload (client-side only, no signature verification needed).
function getTokenExpiry(token) {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return typeof payload.exp === 'number' ? payload.exp * 1000 : null;
    } catch {
        return null;
    }
}

// Proactively refresh the access token before it expires.
// Returns the new token string, or null if refresh failed.
async function proactiveRefresh() {
    // SEC-C4b: refresh token lives in the HttpOnly cookie. We rely on
    // withCredentials=true to send it; the server picks it from the cookie.
    // localStorage no longer stores a refresh token.
    if (isRefreshing) {
        return new Promise((resolve) => {
            refreshSubscribers.push((token) => resolve(token));
        });
    }

    isRefreshing = true;
    try {
        const refreshRes = await axios.post(
            `${api.defaults.baseURL}/auth/refresh`,
            {},
            { withCredentials: true }
        );
        const newToken = refreshRes.data?.access_token;
        if (newToken) {
            memSetToken(newToken);
            onRefreshed(newToken);
            window.dispatchEvent(new Event('token_refreshed'));
            return newToken;
        }
    } catch {
        onRefreshFailed();
    } finally {
        isRefreshing = false;
    }
    return null;
}

// --- Request Interceptor ---
// Add auth token + AbortController to requests.
// Proactively refresh the token if it expires within 60 seconds.
api.interceptors.request.use(async (config) => {
    // Skip proactive refresh for the refresh endpoint itself to avoid infinite loops
    if (config.url?.includes('/auth/refresh') || config._isRetry) {
        return config;
    }

    let token = memGetToken();
    if (token) {
        const expiry = getTokenExpiry(token);
        const now = Date.now();
        // Refresh proactively if the token expires within 60 seconds
        if (expiry !== null && expiry - now < 60_000) {
            const newToken = await proactiveRefresh();
            if (newToken) token = newToken;
        }
        config.headers.Authorization = `Bearer ${token}`;
    }

    // TASK-030: attach CSRF header on mutating requests. Safe no-op when the
    // cookie is missing (anonymous or pure-Bearer clients) — the backend
    // middleware only enforces when a cookie is present on the request.
    const method = (config.method || 'get').toLowerCase();
    if (MUTATING_METHODS.has(method)) {
        const csrf = readCookie('csrf_token');
        if (csrf) {
            config.headers['X-CSRF-Token'] = csrf;
        }
    }

    // T9.4: forward the user's UI language to the backend so that
    // `utils/i18n.http_error()` / `i18n_message()` resolve error messages
    // in the correct locale (uses `backend/locales/errors.{ar,en}.json`).
    // We read i18next first (authoritative) and fall back to localStorage
    // and finally to the <html lang> attribute. The backend normalizes
    // 'ar-SA' / 'en-US' to 'ar' / 'en' automatically.
    if (!config.headers['Accept-Language']) {
        let lang = null;
        try {
            // Lazy access — i18next attaches itself globally once initialized.
            lang = (typeof window !== 'undefined' && window.i18next?.language) || null;
        } catch { /* ignore */ }
        if (!lang) {
            try { lang = localStorage.getItem('i18nextLng'); } catch { /* ignore */ }
        }
        if (!lang && typeof document !== 'undefined') {
            lang = document.documentElement?.lang || null;
        }
        if (lang) {
            config.headers['Accept-Language'] = lang;
        }
    }

    // Auto-attach AbortController unless request already has a signal or opts out
    if (!config.signal && !config.skipAbort) {
        const controller = requestManager.createController()
        config.signal = controller.signal
        config._abortController = controller
    }
    return config
})

// Handle API responses — clean up AbortControllers + auto token refresh
api.interceptors.response.use(
    (response) => {
        // Clean up tracked controller on success
        if (response.config._abortController) {
            requestManager.removeController(response.config._abortController)
        }
        return response
    },
    async (error) => {
        // Clean up tracked controller on error
        if (error.config?._abortController) {
            requestManager.removeController(error.config._abortController)
        }
        // Silently ignore aborted/canceled requests (page navigation)
        if (axios.isCancel(error) || error.code === 'ERR_CANCELED') {
            return Promise.reject(error)
        }
        // Option to skip global toast for specific requests
        const skipToast = error.config?.skipGlobalToast;
        const originalRequest = error.config;

        // --- 429 Rate Limit: Retry with backoff ---
        if (error.response?.status === 429 && !originalRequest._retryCount) {
            originalRequest._retryCount = 1;
            const retryAfter = parseInt(error.response.headers['retry-after'], 10);
            const delay = (retryAfter && retryAfter > 0) ? retryAfter * 1000 : 2000;
            await new Promise(resolve => setTimeout(resolve, delay));
            return api(originalRequest);
        }

        // --- Auto Token Refresh — Fallback (reactive, in case proactive missed) ---
        if (error.response?.status === 401 && !originalRequest._isRetry) {
            originalRequest._isRetry = true;

            // If a refresh is already in progress, queue this request to retry after it completes
            if (isRefreshing) {
                return subscribeTokenRefresh((newToken) => {
                    if (newToken) {
                        originalRequest.headers.Authorization = `Bearer ${newToken}`;
                        return api(originalRequest);
                    }
                    return Promise.reject(error);
                });
            }

            const newToken = await proactiveRefresh();
            if (newToken) {
                originalRequest.headers.Authorization = `Bearer ${newToken}`;
                return api(originalRequest);
            }

            // Refresh failed — clear session and redirect to login
            memClearToken();
            localStorage.removeItem('token'); // purge any legacy value
            localStorage.removeItem('refresh_token'); // purge any legacy value
            localStorage.removeItem('user');
            localStorage.removeItem('company_id');
            window.location.href = '/login';
            return Promise.reject(error);
        }

        if (!skipToast && error.response) {
            const status = error.response.status;
            const detail = error.response.data?.detail;
            const lang = localStorage.getItem('i18nextLng') || 'ar';

            let message = '';
            let type = 'error';

            if (status === 403) {
                message = lang === 'ar'
                    ? 'ليس لديك صلاحية للقيام بهذا الإجراء'
                    : 'You do not have permission to perform this action';
                type = 'warning';
            } else if (status >= 400 && status < 500) {
                if (typeof detail === 'string') {
                    message = detail;
                } else if (Array.isArray(detail)) {
                    message = detail.map(d => d.msg).join(', ');
                } else {
                    message = lang === 'ar'
                        ? 'يرجى مراجعة البيانات المدخلة'
                        : 'Please check your input';
                }
            } else if (status >= 500) {
                message = lang === 'ar'
                    ? 'حدث خطأ في النظام، يرجى المحاولة لاحقاً'
                    : 'A system error occurred, please try again later';
            }

            if (message) {
                toastEmitter.emit(message, type);
            }
        }
        return Promise.reject(error);
    }
);

/**
 * Remove null/undefined/empty-string params before sending.
 */
export const cleanParams = (params) => {
    if (!params) return params;
    const cleaned = {};
    for (const [key, value] of Object.entries(params)) {
        if (value !== '' && value !== null && value !== undefined) {
            cleaned[key] = value;
        }
    }
    return cleaned;
};

export { api }
export default api
