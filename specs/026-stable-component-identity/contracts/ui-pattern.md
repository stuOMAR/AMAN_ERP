# Contract: Stable Component Identity Pattern

**Feature**: 026-stable-component-identity  
**Date**: 2026-05-09  
**Type**: UI Pattern Contract

## Pattern Contract

Every page component consuming `useBranch` MUST implement the following pattern:

### Required State

```javascript
const [loading, setLoading] = useState(true)        // Current fetch loading
const [initialLoad, setInitialLoad] = useState(true) // First mount only
const [data, setData] = useState(null)               // Page-specific data
```

### Required Fetch Function

```javascript
const fetchData = async () => {
    try {
        setLoading(true)
        const params = {}
        if (currentBranch) params.branch_id = currentBranch.id
        // API calls...
        setData(result)
    } catch (err) {
        showToast(err.message || 'Error', 'error')
    } finally {
        setLoading(false)
        setInitialLoad(false)
    }
}
```

### Required useEffect

```javascript
useEffect(() => {
    const timer = setTimeout(() => {
        fetchData()
    }, 300) // 300ms debounce
    return () => clearTimeout(timer)
}, [currentBranch]) // Depends on currentBranch
```

### Required Render Guard

```javascript
// Only full-page loading on initial mount
if (initialLoad && !data) return <PageLoading />

// Subtle spinner on branch switch
return (
    <div>
        {loading && !initialLoad && <SubtleSpinner />}
        {/* Content */}
    </div>
)
```

### Forbidden Patterns

1. ❌ `key={currentBranch?.id}` on any component
2. ❌ `if (loading) return <PageLoading />` (causes full-page reload)
3. ❌ Resetting UI state (activeTab, formInputs, filters) in useEffect
4. ❌ Error boundaries for branch switch errors
5. ❌ Full-page error states during branch switch

### Required Imports

```javascript
import { useState, useEffect } from 'react'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
```

## Validation Checklist

For each file, verify:

- [ ] `initialLoad` state exists
- [ ] `initialLoad` set to `false` in finally block
- [ ] Loading guard uses `initialLoad && !data`
- [ ] useEffect depends on `currentBranch`
- [ ] 300ms debounce implemented
- [ ] Toast notification for errors (not full-page error)
- [ ] No `key` props depending on branch state
- [ ] UI state (tabs, forms, filters) preserved
- [ ] Subtle spinner shown during branch switch
