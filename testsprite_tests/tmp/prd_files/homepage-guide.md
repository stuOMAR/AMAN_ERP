# AMAN ERP — Homepage Guide for Testprite

> **Purpose:** Comprehensive reference for testing the login, layout, and dashboard pages (collectively "the homepage experience") of AMAN ERP.
> **Target audience:** QA / Testprite automated & manual testers.

---

## 1. Architecture Overview

AMAN ERP is a React 18 SPA served from a single HTML entry point. The "homepage" is actually three distinct layers:

| Layer | File | Purpose |
|-------|------|---------|
| **HTML Shell** | `frontend/index.html` | RTL Arabic-first shell, mounts React at `#root` |
| **Login Page** | `frontend/src/pages/Login.jsx` | Unauthenticated entry — login, 2FA, SSO |
| **Dashboard** | `frontend/src/pages/Dashboard.jsx` | Authenticated landing — metrics, charts, quick actions |
| **App Layout** | `frontend/src/components/Layout.jsx` | Wraps all authenticated routes with Sidebar + Topbar |

---

## 2. Entry Flow (URL Routing)

```
/ (root) ──► redirects to /login (if unauthenticated)
         ──► redirects to /dashboard (if authenticated)

/login ──► success ──► /setup/industry (if industry not set)
                   ──► /dashboard (default)
                   ──► 2FA challenge (if user has 2FA enabled)

/dashboard ──► requires auth + dashboard.view permission
           ──► System Admin view OR Company User view (role-dependent)
```

**Key routes in `frontend/src/App.jsx`:**
- `/` — redirect to `/login` or `/dashboard`
- `/login` — login form
- `/dashboard` — main dashboard (wrapped in `Layout`)
- `/register` — self-registration
- `/forgot-password` / `/reset-password` — password recovery

---

## 3. HTML Shell (`frontend/index.html`)

```html
<html lang="ar" dir="rtl">
  <title>AMAN ERP - نظام أمان لإدارة الموارد المؤسسية</title>
  <!-- Tajawal Arabic font from Google Fonts -->
  <!-- React mounts at <div id="root"></div> -->
  <!-- <div id="datepicker-portal"></div> for portal elements -->
</html>
```

**Test points:**
- Page title is correct
- `lang="ar"` and `dir="rtl"` are set
- Tajawal font loads (network request to `fonts.googleapis.com`)
- `#root` div exists and is populated after React hydration

---

## 4. Login Page (`/login`)

### 4.1 Component States

| State | Trigger | What to Verify |
|-------|---------|----------------|
| **Default** | Page load (unauthenticated) | Form with company code, username, password fields visible |
| **Admin user** | Type `admin` as username | Company code field **hides** automatically |
| **Loading** | Form submit | Submit button shows spinner, all fields disabled |
| **Error — validation** | Empty required field | Error message in `.alert-error` |
| **Error — login fail** | Wrong credentials | Backend error in `.alert-error` |
| **Error — rate limit** | Too many attempts (HTTP 429) | Rate-limit message |
| **2FA challenge** | User with 2FA enabled logs in | Form switches to 6-digit TOTP input |
| **2FA verification** | TOTP code submitted | Redirect to dashboard/setup on success |
| **SSO providers** | Type a valid company code | SSO buttons appear below form (debounced 500ms) |
| **SSO redirect** | Click SSO provider | Redirects to external SSO or logs in directly |
| **Already authenticated** | Navigate to `/login` while logged in | Auto-redirect to `/dashboard` |

### 4.2 Form Fields

| Field | ID / Selector | Type | Notes |
|-------|---------------|------|-------|
| Company Code | `#company_code` | text | Hidden when username = `admin`. Min 2 chars to trigger SSO fetch |
| Username | `#username` | text | Required. `admin` = system admin (no company code needed) |
| Password | `#password` | password/text | Toggle visibility via show/hide button |
| TOTP Code | `#totp_code` | text (numeric) | Only visible in 2FA state. Max 6 digits. Auto-focus |

### 4.3 Other Login Page Elements

| Element | Selector | Behavior |
|---------|----------|----------|
| Language toggle | `.floating-language-toggle button` | Switches AR↔EN (top-right floating) |
| Forgot Password link | `a[href="/forgot-password"]` | Navigates to forgot-password page |
| Register link | `a[href="/register"]` | Navigates to registration page |
| SSO divider | Contains `t('auth.or_sso')` | Only visible when SSO providers loaded |
| SSO buttons | `button` inside SSO section | One per provider, shows provider.display_name |

### 4.4 Auth Redirect Logic

After successful login:
1. If `requires_2fa === true` → show 2FA form (don't redirect yet)
2. If `user.role === 'system_admin'` → redirect to `/dashboard`
3. If `hasIndustryTypeSet() === false` → redirect to `/setup/industry`
4. Otherwise → redirect to `/dashboard`

**Tokens stored:** `access_token`, `refresh_token` in localStorage + `user` object + `company_id`.

---

## 5. App Layout (Wrapper for `/dashboard`)

### 5.1 Layout Component (`frontend/src/components/Layout.jsx`)

The Layout wraps **all authenticated routes**. On mount it calls `authAPI.me()` to sync user data.

| Behavior | Trigger | Expected |
|----------|---------|----------|
| Sidebar open | Desktop (width > 1024px) | Sidebar visible, main content shifted |
| Sidebar closed | Mobile (width ≤ 1024px) | Sidebar hidden, overlay when toggled open |
| Sidebar toggle | Click hamburger menu | Toggles sidebar open/close |
| Overlay close | Click overlay (mobile) | Closes sidebar |
| Resize | Window resize past 1024px | Sidebar auto-opens/closes |
| Nav return flash | `aman:return-target` in sessionStorage | Target nav item highlighted briefly |

### 5.2 Sidebar (`frontend/src/components/Sidebar.jsx`)

| Element | Selector | Notes |
|---------|----------|-------|
| Brand | `.sidebar-brand-text` | Always "AMAN ERP" |
| Toggle button | `.sidebar-toggle` | Same hamburger as Topbar toggle |
| Nav container | `.sidebar-nav` | Contains NavLink items |
| Dashboard link | `a[href="/dashboard"]` | Always present, first item |
| Module links | Varies | Filtered by `enabled_modules`, permissions, and industry type |
| Active indicator | `.nav-item.active` class | Applied to current route |
| System admin nav | Companies, Scheduler, Health links | Only when `user.role === 'system_admin'` |

**Modules shown (company user):** Accounting, Assets, Treasury, Sales, POS, Buying, Stock/Inventory, Manufacturing, Projects, CRM, Services, Expenses, Taxes, Approvals, Reports, HR, Settings, KPI Admin.

Each module requires both `*.view` permission AND enabled in `user.enabled_modules` (or industry template fallback).

### 5.3 Topbar (`frontend/src/components/Topbar.jsx`)

| Element | Selector / Description | Behavior |
|---------|------------------------|----------|
| Hamburger toggle | `.topbar-sidebar-toggle` | Toggles sidebar, has `aria-expanded` |
| Global search | `.topbar-search` or Ctrl+K | Opens `GlobalSearch` modal |
| Language switch | `.topbar-lang-btn` | Toggles AR↔EN, text shows "EN" or "ع" |
| Dark mode toggle | `.topbar-theme-btn` | Sun/moon icon, calls `toggleDarkMode()` |
| Branch selector | `.topbar-branch-btn` | Shows current branch + currency. Dropdown on click |
| Branch dropdown | `.dropdown-menu` inside branch ref | Lists all branches + "All branches" option |
| Notification bell | Bell emoji button | Shows unread count badge (red circle, max "9+") |
| Notification dropdown | `.topbar-notif-dropdown` | List of notifications, click to mark read + navigate |
| Mark all read | "Mark all read" button | Calls `notificationsAPI.markAllRead()` |
| User menu trigger | `.user-menu-trigger` | Shows full name + company ID + avatar circle |
| User dropdown | `.dropdown-menu` | Profile, Company Profile (admin), Logout |

**WebSocket behavior:** Real-time notifications via WebSocket. Falls back to 60s polling when WS disconnected.

**Keyboard shortcut:** `Ctrl+K` (Windows/Linux) or `Cmd+K` (Mac) toggles global search.

---

## 6. Dashboard Page (`/dashboard`)

### 6.1 System Admin View

Triggered when `user.role === 'system_admin'`.

**API call:** `GET /dashboard/system-stats`

**Display:**

| Element | Data |
|---------|------|
| Title | `t('dashboard.system_admin_title')` |
| Subtitle | `t('dashboard.system_admin_welcome')` |
| Stats cards (4) | Total Companies, Total Users, Active Users, System Status |
| Admin action cards (3) | Companies → `/admin/companies`, Audit Logs → `/admin/audit-logs`, Roles → `/admin/roles` |

**Test points:**
- Stats load from API and display numeric values
- Loading state shows placeholder shimmer (gray rectangles)
- System Status card turns green text when value = "Healthy"
- Admin cards navigate to correct routes on click

### 6.2 Company User View

Triggered when `user.role !== 'system_admin'`.

**API calls (3 parallel requests):**
- `GET /dashboard/stats?branch_id=X` → `stats`
- `GET /dashboard/charts/financial?branch_id=X` → `finData`
- `GET /dashboard/charts/products?branch_id=X` → `prodData`

Branch filter is applied via `currentBranch` from `BranchContext`.

**Display layout (top to bottom):**

| Row | Component | Conditional | Description |
|-----|-----------|-------------|-------------|
| Header | Inline | No | Greeting + date + refresh button + branch badge |
| 1 | `StatsCards` | No | Key KPIs (revenue, orders, customers, etc.) |
| → | `IndustryWidgets` | No | Industry-specific widgets |
| 2 | `SalesSummaryWidget` × 3 | `isModOn('sales')` | Today / This Week / This Month cards |
| 3 | `FinancialChart` + `QuickActions` | No | 2:1 grid — chart + action links |
| 4 | `TopProductsChart` + `LowStockWidget` | `isModOn('stock')` | Product performance + low-stock alerts |
| 5 | `CashFlowWidget` | No | 30-day cash flow chart |
| 6 | `PendingTasksWidget` | No | Pending task list (limit 10) |

### 6.3 Dashboard Header

| Element | Data Source | Notes |
|---------|-------------|-------|
| Greeting | Computed from `new Date().getHours()` | "Good morning" (6-11), "Good afternoon" (12-17), "Good evening" (18+) |
| User name | `user.full_name` or `user.username` | From auth context |
| Branch badge | `currentBranch.branch_name` | Only shown when a branch is selected |
| Date | `formatShortDate(new Date())` | Formatted via dateUtils |
| Refresh button | Calls `fetchAll()` | Spinner while loading, disabled during load |

### 6.4 QuickActions Component

4 action buttons filtered by `enabled_modules`:

| Action | Route | Module | Icon |
|--------|-------|--------|------|
| New Sales Invoice | `/sales/invoices/new` | sales | TrendingUp |
| New Product | `/stock/products/new` | stock | Package |
| New Journal Entry | `/accounting/journal-entries/new` | accounting | Wallet |
| Employees | `/hr/employees` | hr | Users |

**Test points:**
- Buttons navigate to correct routes on click
- Buttons filtered out if module not in `enabled_modules`
- Hover effects: background color + border color changes per action

### 6.5 Child Widget Components

All dashboard widgets live in `frontend/src/components/dashboard/`:

| Component | File | Props | Description |
|-----------|------|-------|-------------|
| `StatsCards` | `StatsCards.jsx` | `stats`, `loading`, `currency` | Key metric cards |
| `FinancialChart` | `FinancialChart.jsx` | `data`, `loading`, `currency` | Revenue/expense chart |
| `TopProductsChart` | `TopProductsChart.jsx` | `data`, `loading`, `currency` | Top products by sales |
| `SalesSummaryWidget` | `SalesSummaryWidget.jsx` | `config` (period), `currency` | Period-based sales summary |
| `LowStockWidget` | `LowStockWidget.jsx` | `config` (limit: 8), `currency` | Products below reorder point |
| `PendingTasksWidget` | `PendingTasksWidget.jsx` | `config` (limit: 10), `currency` | Pending approvals/tasks |
| `CashFlowWidget` | `CashFlowWidget.jsx` | `config` (days: 30), `currency` | Cash flow trend |
| `IndustryWidgets` | `IndustryWidgets.jsx` | (none — uses context) | Industry-specific widgets |

---

## 7. Responsive Behavior

| Breakpoint | Behavior |
|------------|----------|
| > 1024px (Desktop) | Sidebar always open, full layout |
| ≤ 1024px (Mobile/Tablet) | Sidebar hidden by default. Toggle opens it with dark overlay. Click overlay or nav link to close |
| `window.innerWidth` change | Auto-updates via resize listener |

**Test:** Resize window across 1024px boundary, verify sidebar auto-shows/hides.

---

## 8. Localization (i18n)

- Two languages: Arabic (`ar`) and English (`en`)
- RTL for Arabic, LTR for English
- Language change persists via `i18next`
- Translation files: `frontend/src/locales/ar.json` and `en.json`
- **Test:** Switch language on both login and dashboard, verify all labels update

---

## 9. API Endpoints Used by Homepage

| Endpoint | Method | Used By | Notes |
|----------|--------|---------|-------|
| `/auth/login` | POST | Login | Returns JWT or 2FA challenge |
| `/auth/verify-2fa-login` | POST | Login (2FA) | Returns JWT after TOTP verification |
| `/auth/sso-providers/{code}` | GET | Login | Returns SSO providers for company |
| `/auth/sso-login` | POST | Login (SSO) | SSO login |
| `/auth/me` | GET | Layout | Syncs user data on mount |
| `/dashboard/system-stats` | GET | Dashboard (admin) | System admin stats |
| `/dashboard/stats` | GET | Dashboard (company) | Company KPIs |
| `/dashboard/charts/financial` | GET | Dashboard (company) | Financial chart data |
| `/dashboard/charts/products` | GET | Dashboard (company) | Product chart data |
| `/notifications/` | GET | Topbar | Notification list |
| `/notifications/unread-count` | GET | Topbar | Unread notification count |
| `/notifications/{id}/read` | POST | Topbar | Mark notification read |
| `/notifications/mark-all-read` | POST | Topbar | Mark all read |

---

## 10. Logout

| Method | Description |
|--------|-------------|
| User menu → Logout | Calls `logout()` which clears localStorage tokens and redirects to `/login` |

---

## 11. Key CSS Classes

| Class | Applies To | Purpose |
|-------|-----------|---------|
| `.auth-layout` | Login page wrapper | Centers the login card |
| `.auth-card` | Login form container | Card with white background, shadow |
| `.auth-header` | Login title area | Title + subtitle |
| `.alert-error` | Error messages | Red alert box |
| `.app-layout` | Layout root | Full-page flex layout |
| `.sidebar` / `.sidebar-open` | Sidebar | Collapsible nav panel |
| `.sidebar-brand` | Sidebar brand | "AMAN ERP" + toggle |
| `.sidebar-nav` | Nav links | Scrollable nav list |
| `.nav-item` / `.nav-item.active` | NavLink | Individual nav items |
| `.sidebar-overlay` | Mobile overlay | Dark backdrop when sidebar open on mobile |
| `.main-container` | Main content area | Flexes beside sidebar |
| `.topbar` | Topbar | Fixed header bar |
| `.topbar-search` | Search trigger | Clickable search bar |
| `.workspace` / `.workspace-header` | Dashboard | Page wrapper + header |
| `.workspace-title` / `.workspace-subtitle` | Dashboard | Title + subtitle text |
| `.dashboard-row-2col` | Dashboard row 3 | 2-column grid (2:1) |
| `.modules-grid` | Dashboard row 2 | 3-column sales summary grid |
| `.card` | Generic cards | Reusable card component |
| `.dropdown-menu` | Dropdowns | User menu, notifications, branch selector |
| `.fade-in` | Animation | Entrance animation for dropdowns/pages |
| `.animate-spin` | Loading | Spinning animation on refresh icon |
| `.nav-return-flash` | Nav highlight | Brief flash on return-target nav item |

---

## 12. Recommended Test Scenarios

### Login Tests
1. **Happy path:** Valid credentials → redirect to dashboard
2. **Admin login:** Username `admin`, no company code → redirect to dashboard
3. **2FA flow:** User with 2FA → TOTP prompt → verify → dashboard
4. **SSO flow:** Type valid company code → SSO buttons appear → click SSO → redirect
5. **Validation:** Empty fields → error message
6. **Wrong credentials:** Invalid password → error message
7. **Rate limiting:** Rapid failed attempts → 429 error → rate-limit message
8. **Already authenticated:** Visit `/login` while logged in → auto-redirect

### Dashboard Tests
1. **System admin view:** Admin user sees system stats + admin action cards
2. **Company user view:** Normal user sees full dashboard with all widget rows
3. **Module filtering:** Disable `sales` module → sales summary row hidden
4. **Module filtering:** Disable `stock` module → top products + low stock row hidden
5. **Branch filter:** Select branch → API calls include `branch_id` param
6. **Quick actions:** Each action button navigates to correct route
7. **Refresh:** Click refresh → data reloads, spinner shows
8. **Empty state:** When no data → widgets handle gracefully
9. **Responsive:** Resize to mobile → sidebar collapses, layout adjusts

### Layout Tests
1. **Navigation:** Each sidebar link navigates correctly
2. **Active state:** Current page link has `.active` class
3. **Sidebar toggle:** Toggle button opens/closes sidebar
4. **Mobile overlay:** Click overlay closes sidebar on mobile
5. **Global search:** Ctrl+K opens search, searches correctly
6. **Language switch:** AR↔EN toggle updates all text
7. **Dark mode:** Theme toggle switches light/dark
8. **Notifications:** Badge count updates, dropdown opens, mark read works
9. **User menu:** Profile, Company Profile (admin), Logout all work
10. **Logout:** Clears auth and redirects to login

---

## 13. Test Data / Credentials Reference

> Fill in with your test environment credentials:

| Role | Username | Password | Company Code | Notes |
|------|----------|----------|--------------|-------|
| System Admin | `admin` | (test password) | (none needed) | Full system access |
| Company Admin | (test user) | (test password) | (test code) | Company-level admin |
| Regular User | (test user) | (test password) | (test code) | Limited permissions |
| 2FA User | (test user) | (test password) | (test code) | Has 2FA enabled |
