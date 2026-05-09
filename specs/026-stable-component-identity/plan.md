# Implementation Plan: Stable Component Identity

**Branch**: `026-stable-component-identity` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/026-stable-component-identity/spec.md`

## Summary

Apply the "Stable Component Identity" pattern across all 138 frontend files that use `useBranch` or `currentBranch`. The pattern ensures components never lose UI state (active tabs, modals, form inputs, scroll position, filters) when users switch branches. Data refreshes reactively via `useEffect` with 300ms debounce, showing subtle loading indicators instead of full-page loading screens. Errors display toast notifications while preserving current UI state.

## Technical Context

**Language/Version**: React 18 with Vite, JavaScript/JSX  
**Primary Dependencies**: React hooks (useState, useEffect, useCallback), BranchContext, useBranch hook  
**Storage**: No storage changes - uses existing BranchContext state management  
**Testing**: Manual testing across pages; no automated tests required  
**Target Platform**: Browser (existing frontend)  
**Project Type**: Frontend-only pattern application across existing pages  
**Performance Goals**: 300ms debounce on branch switch; background data refresh without UI blocking  
**Constraints**: Must preserve existing BranchContext API; must not break existing page functionality  
**Scale/Scope**: 138 files using useBranch/currentBranch across frontend/src/pages/ and frontend/src/components/

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | N/A - no financial calculations involved | PASS |
| Tenant isolation | N/A - no database access changes | PASS |
| GL integrity | N/A - no accounting impact | PASS |
| Security boundary | N/A - no endpoint changes; existing permissions preserved | PASS |
| Regulatory settings | N/A - no regulatory changes | PASS |
| Calculation centralization | N/A - no new calculations | PASS |
| Report consistency | N/A - no report changes | PASS |
| Concurrency | N/A - no concurrency changes | PASS |
| Query discipline | N/A - no query changes; existing API calls preserved | PASS |
| UI consistency | PASS - implements consistent branch switching behavior across all pages per Principle XXVII | PASS |
| Schema sync | N/A - no schema changes | PASS |
| Artifact boundaries | PASS - spec mentions entities only, no DDL | PASS |
| Spec format | PASS - requirements and acceptance criteria only, no user stories | PASS |

## Design Artifact Rules

`data-model.md` MUST list entity/table names, critical fields, relationships,
validation rules, and state transitions only. Do not generate full DDL unless
the user explicitly asks for DDL.

## Project Structure

### Documentation (this feature)

```text
specs/026-stable-component-identity/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
frontend/src/
├── context/
│   └── BranchContext.jsx          # Already exists - no changes needed
├── components/
│   ├── Topbar.jsx                 # Already fixed - removed branchRouteKey dependency
│   ├── common/
│   │   └── LoadingStates.jsx      # PageLoading component - exists
│   └── Tax/
│       └── ProductTaxSelector.jsx # Needs pattern application
├── pages/
│   ├── Taxes/
│   │   └── TaxHome.jsx            # Already fixed - template for other pages
│   ├── Accounting/                # Needs pattern application
│   ├── Sales/                     # Needs pattern application
│   ├── Stock/                     # Needs pattern application
│   ├── HR/                        # Needs pattern application
│   ├── Reports/                   # Needs pattern application
│   └── [all other page dirs]      # Needs pattern application
└── App.jsx                        # Already fixed - removed key={branchRouteKey}
```

**Structure Decision**: This is a frontend-only change. No backend modifications. The pattern is applied by modifying existing React components to use the Stable Component Identity pattern.

## Implementation Approach

### Pattern Template (from TaxHome.jsx)

Every page using `useBranch` must implement:

```javascript
// 1. State declarations
const [loading, setLoading] = useState(true)
const [initialLoad, setInitialLoad] = useState(true)
const [data, setData] = useState(null)

// 2. Fetch function with error handling
const fetchData = async () => {
    try {
        setLoading(true)
        const params = {}
        if (currentBranch) params.branch_id = currentBranch.id
        // API calls...
        setData(result)
    } catch (err) {
        showToast(err.message, 'error')  // Toast, not full-page error
    } finally {
        setLoading(false)
        setInitialLoad(false)
    }
}

// 3. Debounced useEffect for branch changes
useEffect(() => {
    const timer = setTimeout(() => {
        fetchData()
    }, 300)  // 300ms debounce
    return () => clearTimeout(timer)
}, [currentBranch])

// 4. Initial load guard (shows PageLoading only once)
if (initialLoad && !data) return <PageLoading />

// 5. Render with subtle loading indicator during branch switch
return (
    <div>
        {loading && !initialLoad && <SubtleSpinner />}
        {/* Page content */}
    </div>
)
```

### Files to Modify (Priority Order)

**Priority 1 - High Traffic Pages (Accounting, Sales, Stock):**
- `frontend/src/pages/Accounting/*.jsx` - Journal entries, chart of accounts, fiscal years
- `frontend/src/pages/Sales/*.jsx` - Invoices, quotations, orders
- `frontend/src/pages/Stock/*.jsx` - Products, inventory, warehouses

**Priority 2 - HR and Reports:**
- `frontend/src/pages/HR/*.jsx` - Employees, payroll
- `frontend/src/pages/Reports/*.jsx` - Report center, scheduled reports

**Priority 3 - Settings and Other Pages:**
- `frontend/src/pages/Settings/*.jsx` - Branches, company settings
- `frontend/src/pages/Treasury/*.jsx` - Treasury accounts
- `frontend/src/pages/Assets/*.jsx` - Asset management
- `frontend/src/pages/Analytics/*.jsx` - Dashboards
- `frontend/src/pages/KPI/*.jsx` - KPI dashboards

**Priority 4 - Components:**
- `frontend/src/components/Tax/ProductTaxSelector.jsx`
- Any other components using `useBranch`

### Key Changes Per File

For each file, apply these changes:
1. Add `initialLoad` state if not present
2. Update `finally` block to set `initialLoad(false)`
3. Change loading guard from `if (loading && !data)` to `if (initialLoad && !data)`
4. Ensure `useEffect` depends on `currentBranch`
5. Add 300ms debounce timer
6. Show subtle spinner during branch switch (not full-page loading)
7. Use `showToast` for errors (not full-page error states)

## Complexity Tracking

> **No Constitution violations - this section is empty**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | N/A | N/A |
