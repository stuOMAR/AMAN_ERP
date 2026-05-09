# Data Model: Stable Component Identity

**Feature**: 026-stable-component-identity  
**Date**: 2026-05-09

## Entities

### BranchContext (Existing - No Changes)

**Purpose**: Provides branch state to all components  
**Location**: `frontend/src/context/BranchContext.jsx`

| Field | Type | Description |
|-------|------|-------------|
| currentBranch | Object/null | Currently selected branch object |
| branches | Array | List of all available branches |
| setBranch | Function | Updates currentBranch and persists to localStorage |
| loading | Boolean | Initial branch list loading state |
| displayCurrency | Object | Currency display configuration |

**Relationships**: Consumed by all pages via `useBranch()` hook

### useBranch Hook (Existing - No Changes)

**Purpose**: Provides branch context to components  
**Location**: `frontend/src/context/BranchContext.jsx`

**Returns**:
- `currentBranch`: Currently selected branch
- `branches`: Array of all branches
- `setBranch`: Function to update current branch
- `loading`: Boolean for initial load state
- `displayCurrency`: Currency configuration

### Page Components (Modified)

**Purpose**: All pages consuming branch state  
**Location**: `frontend/src/pages/**/*.jsx`

**State Pattern** (NEW):
| State | Type | Description |
|-------|------|-------------|
| loading | Boolean | Current data loading state |
| initialLoad | Boolean | First mount loading state (prevents full-page loading on branch switch) |
| data | Object | Page-specific data (summary, rates, returns, etc.) |

**Behavior**:
- `initialLoad` starts as `true`, set to `false` after first data fetch
- `loading` toggles on each fetch (including branch switch)
- Full-page loading only shown when `initialLoad && !data`
- Subtle spinner shown when `loading && !initialLoad`

### UI State (Preserved)

**Purpose**: User interaction state that persists across branch switches  
**Location**: Component state (useState hooks)

| State | Type | Description |
|-------|------|-------------|
| activeTab | String | Currently active tab/section |
| modals | Object | Open modals and their state |
| formInputs | Object | Form field values |
| filters | Object | Applied filters/search terms |
| scrollPosition | Number | Page scroll position (browser native) |

**Behavior**: All UI state remains unchanged when `currentBranch` changes. Only data fetches trigger re-renders with new data.

## State Transitions

### Branch Switch Flow

```
User clicks branch in Topbar
  → setBranch(newBranch) called
  → BranchContext updates currentBranch
  → All components with useEffect([currentBranch]) trigger
  → 300ms debounce timer starts
  → After 300ms, fetchData() called
  → loading = true (subtle spinner shown)
  → API calls made with new branch_id
  → Data updated
  → loading = false
  → UI state (tabs, forms, filters) unchanged
```

### Initial Page Load Flow

```
User navigates to page
  → Component mounts
  → initialLoad = true, loading = true
  → PageLoading component shown (full-page)
  → fetchData() called
  → Data loaded
  → initialLoad = false, loading = false
  → Page content rendered
  → User interacts (sets tabs, fills forms, applies filters)
  → User switches branch
  → Subtle spinner shown (not full-page)
  → Data refreshes in background
  → UI state preserved
```

## Validation Rules

### Branch Selection
- `currentBranch` can be `null` (All Branches) or a branch object
- Branch object must have `id` and `branch_name` properties
- Branch must be in `branches` array (validated by BranchContext)

### Data Fetching
- All API calls must include `branch_id` parameter when `currentBranch` is not null
- When `currentBranch` is null, omit `branch_id` (or send `all_branches: true`)
- 300ms debounce prevents rapid API calls
- Errors show toast notification, not full-page error

### UI State Preservation
- `activeTab` must not reset on branch change
- Form inputs must not clear on branch change
- Filters must not reset on branch change
- Modals must not close on branch change
- Scroll position maintained by browser
