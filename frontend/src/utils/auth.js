// Auth utilities

// SEC-T2.8: access token now lives in memory only — see ./tokenStore.js.
// `localStorage` MUST NOT contain a `token` key after login.
import { getToken as memGetToken, setToken as memSetToken, clearToken as memClearToken } from './tokenStore'

let bootstrapRefreshPromise = null

export function isAuthenticated() {
    const token = memGetToken();
    const user = localStorage.getItem('user');
    const isAuth = !!token && !!user && user !== 'undefined' && user !== 'null';
    return isAuth;
}

export function getToken() {
    return memGetToken()
}

// SEC-C4b: refresh token is kept in an HttpOnly, SameSite=Strict cookie
// issued by the backend (see utils/auth_cookies.py). It is NEVER written
// to localStorage anymore — that closed the XSS-→-token-theft path.
// This helper is kept only for compatibility; it always returns null.
export function getRefreshToken() {
    return null
}

export function getUser() {
    try {
        const user = localStorage.getItem('user')
        if (!user || user === 'undefined' || user === 'null') return null
        return JSON.parse(user)
    } catch (err) {
        console.error("Error parsing user from localStorage", err)
        localStorage.removeItem('user') // Clear corrupt data
        return null
    }
}

export function getCompanyId() {
    return localStorage.getItem('company_id')
}

export const DISPLAY_CURRENCY_KEY = 'display_currency'
export const DISPLAY_CURRENCY_MODE_KEY = 'display_currency_mode'
export const DISPLAY_CURRENCY_BASE_KEY = 'display_currency_base'
export const DISPLAY_CURRENCY_SCOPE_KEY = 'display_currency_scope'

export function getCompanyCurrency() {
    const user = getUser()
    return user?.currency || ''
}

export function setDisplayCurrency(currency, metadata = {}) {
    if (currency) localStorage.setItem(DISPLAY_CURRENCY_KEY, currency)
    else localStorage.removeItem(DISPLAY_CURRENCY_KEY)

    if (metadata.mode) localStorage.setItem(DISPLAY_CURRENCY_MODE_KEY, metadata.mode)
    else localStorage.removeItem(DISPLAY_CURRENCY_MODE_KEY)

    if (metadata.baseCurrency) localStorage.setItem(DISPLAY_CURRENCY_BASE_KEY, metadata.baseCurrency)
    else localStorage.removeItem(DISPLAY_CURRENCY_BASE_KEY)

    if (Array.isArray(metadata.currencies)) {
        localStorage.setItem(DISPLAY_CURRENCY_SCOPE_KEY, JSON.stringify(metadata.currencies))
    } else {
        localStorage.removeItem(DISPLAY_CURRENCY_SCOPE_KEY)
    }
}

export function clearDisplayCurrency() {
    localStorage.removeItem(DISPLAY_CURRENCY_KEY)
    localStorage.removeItem(DISPLAY_CURRENCY_MODE_KEY)
    localStorage.removeItem(DISPLAY_CURRENCY_BASE_KEY)
    localStorage.removeItem(DISPLAY_CURRENCY_SCOPE_KEY)
}

export function getCurrency() {
    return localStorage.getItem(DISPLAY_CURRENCY_KEY) || getCompanyCurrency()
}

export function getCountry() {
    const user = getUser()
    return user?.country || ''
}

// Permission aliases — mirrors backend PERMISSION_ALIASES
// If a user has the KEY permission, they implicitly have VALUE permissions
const PERMISSION_ALIASES = {
    'inventory.view':   ['stock.view', 'products.view'],
    'inventory.delete': ['products.delete', 'stock.adjustment'],
    'inventory.*':      ['stock.view', 'stock.view_cost', 'stock.adjustment', 'stock.transfer',
                         'stock.manage', 'stock.reports',
                         'products.view', 'products.create', 'products.edit', 'products.delete'],
    'projects.manage':  ['projects.view', 'projects.create', 'projects.edit', 'projects.delete'],
    'admin.users':      ['admin.roles', 'settings.view', 'settings.edit'],
    'admin.branches':   ['branches.view', 'branches.manage'],
    'sales.edit':       ['sales.create'],
    'sales.delete':     ['sales.create'],
    'buying.reports':   ['buying.view'],
    'hr.reports':       ['hr.view'],
    'reports.financial': ['reports.view'],
    'manufacturing.reports': ['manufacturing.view'],
    'notifications.send': ['notifications.view'],
    'finance.subscription_manage': ['finance.subscription_view'],
    'finance.cashflow_generate': ['finance.cashflow_view'],
    'crm.campaign_manage': ['crm.campaign_view'],
    'projects.resource_manage': ['projects.resource_view'],
    'approvals.manage': ['approvals.view', 'approvals.create', 'approvals.action'],
    'accounting.manage': ['accounting.view', 'accounting.edit', 'accounting.create_journal_entry', 'accounting.post_journal_entry', 'accounting.void_journal_entry'],
    'treasury.manage': ['treasury.view', 'treasury.create', 'treasury.edit', 'treasury.delete'],
    'taxes.manage': ['taxes.view'],
    'settings.manage': ['settings.view', 'settings.edit'],
    // === Duplicate-name aliases (kept in sync with backend PERMISSION_ALIASES) ===
    'approvals.approve': ['approvals.action'],
    'products.create': ['stock.create_product'],
    'products.delete': ['stock.delete_product'],
    'data_import.create': ['data_import.execute'],
    'sso.manage': ['auth.sso_manage'],
    'hr.leaves.manage': ['hr.leaves.view'],
    'crm.campaign_execute': ['crm.campaign_view'],
    'projects.time_approve': ['projects.time_view', 'projects.time_log'],
    'inventory.forecast_manage': ['inventory.forecast_view', 'inventory.forecast_generate'],
    'inventory.costing_manage': ['inventory.costing_view'],
    'manufacturing.shopfloor_operate': ['manufacturing.shopfloor_view'],
    'manufacturing.routing_manage': ['manufacturing.routing_view'],
    'hr.performance_manage': ['hr.performance_view', 'hr.performance_review', 'hr.performance_self'],
    'finance.cashflow_manage': ['finance.cashflow_view', 'finance.cashflow_generate'],
    'dashboard.analytics_manage': ['dashboard.analytics_view'],
    'accounting.post_journal_entry': ['accounting.create_journal_entry'],
    'accounting.void_journal_entry': ['accounting.create_journal_entry'],
    'buying.blanket_manage': ['buying.blanket_view'],
    'buying.blanket_release': ['buying.blanket_view'],
    'expenses.manage': ['expenses.view', 'expenses.create', 'expenses.edit', 'expenses.delete', 'expenses.approve'],
    'finance.accounting_post': ['finance.accounting_read', 'finance.accounting_view'],
    'finance.accounting_read': ['finance.accounting_view'],
    'finance.reconciliation_manage': ['finance.reconciliation_view'],
}

export function hasPermission(permission) {
    const user = getUser()
    if (!user || !user.permissions || !Array.isArray(user.permissions)) {
        return false
    }

    // Admin check - wildcard for superuser
    if (user.permissions.includes('*')) return true

    // If permission is an array, check if user has ANY of them
    const requiredPermissions = Array.isArray(permission) ? permission : [permission]

    return requiredPermissions.some(perm => {
        if (!perm) return false
        // Exact match
        if (user.permissions.includes(perm)) return true

        // Check wildcard sections (e.g., 'sales.*')
        const parts = perm.split('.')
        if (parts.length > 1) {
            const sectionWildcard = parts[0] + '.*'
            if (user.permissions.includes(sectionWildcard)) return true
        }

        // Alias expansion: check if any user permission implies the required one
        for (const userPerm of user.permissions) {
            const implied = PERMISSION_ALIASES[userPerm]
            if (implied && implied.includes(perm)) return true
        }

        return false
    })
}

/**
 * Returns true when the user object is fully loaded with a valid permissions
 * array. Use this to distinguish between two cases:
 *   - isAuthReady() === false → auth still loading  → show "..."
 *   - isAuthReady() === true  → auth resolved        → check hasPermission()
 *                                                       false → show "***"
 *                                                       true  → show real value
 *
 * This prevents the race condition where hasPermission() briefly returns false
 * for admin users during page navigation (before /auth/me completes).
 */
export function isAuthReady() {
    const user = getUser()
    return (
        user !== null &&
        typeof user === 'object' &&
        Array.isArray(user.permissions) &&
        user.permissions.length > 0
    )
}


export function updateUser(userData) {
    const currentUser = getUser();
    const updatedUser = { ...currentUser, ...userData };
    localStorage.setItem('user', JSON.stringify(updatedUser));
}

export function setAuth(token, user, companyId, _refreshToken = null) {
    // SEC-C4b: refresh token is received as an HttpOnly cookie from /auth/login
    // and /auth/refresh. We deliberately do NOT persist it in localStorage.
    // SEC-T2.8: access token is held only in memory (see ./tokenStore.js).
    memSetToken(token)
    // Purge any stale tokens written by older builds.
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    localStorage.setItem('user', JSON.stringify(user))
    if (companyId) {
        localStorage.setItem('company_id', companyId)
    }
    // حفظ نوع النشاط التجاري أو مسحه (يضمن إعادة التوجيه للمعالج عند الشركات الجديدة)
    if (user?.industry_type) {
        localStorage.setItem('industry_type', user.industry_type)
    } else {
        // clear any stale value from a previous company login
        localStorage.removeItem('industry_type')
    }
}

export function clearAuth() {
    memClearToken()
    // Purge any legacy keys still lingering from previous builds.
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    localStorage.removeItem('company_id')
    localStorage.removeItem('industry_type')
    clearDisplayCurrency()
}

export function logout() {
    clearAuth()
    window.location.href = '/login'
}

// SEC-T2.8: silent refresh on app boot.
//
// After a full page reload the in-memory access token is gone but the HttpOnly
// refresh-token cookie is still on the wire. If `user` is in localStorage we
// optimistically call /auth/refresh once to recover an access token. On
// failure we clear the partial session and force the user to log in again.
//
// Returns true if an access token is now available, false otherwise.
export async function bootstrapAuth() {
    // Already have a fresh token in memory (e.g. just logged in) — no work to do.
    if (memGetToken()) return true

    if (bootstrapRefreshPromise) {
        return bootstrapRefreshPromise
    }

    const publicAuthPaths = ['/login', '/register', '/forgot-password', '/reset-password']
    if (typeof window !== 'undefined' && publicAuthPaths.includes(window.location.pathname)) {
        clearAuth()
        return false
    }

    const userBlob = localStorage.getItem('user')
    if (!userBlob || userBlob === 'undefined' || userBlob === 'null') {
        // No previous session — nothing to recover.
        return false
    }

    bootstrapRefreshPromise = (async () => {
        const baseURL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || '/api'
        const res = await fetch(`${baseURL}/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
        })
        if (!res.ok) {
            clearAuth()
            return false
        }
        const data = await res.json().catch(() => null)
        const newToken = data?.access_token
        if (!newToken) {
            clearAuth()
            return false
        }
        memSetToken(newToken)
        return true
    })()

    try {
        return await bootstrapRefreshPromise
    } catch {
        clearAuth()
        return false
    } finally {
        bootstrapRefreshPromise = null
    }
}
