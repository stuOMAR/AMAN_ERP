# Quickstart: Stable Component Identity

**Feature**: 026-stable-component-identity  
**Date**: 2026-05-09

## What This Feature Does

Ensures that when users switch branches in the Topbar dropdown, the current page data refreshes in the background without losing the user's current view state (active tabs, form inputs, filters, modals).

## How to Verify

### Test 1: Tab Preservation
1. Navigate to `/taxes`
2. Click on "Rates" tab
3. Switch to a different branch in Topbar
4. **Expected**: "Rates" tab remains active, data refreshes

### Test 2: Form Input Preservation
1. Navigate to any page with a form
2. Fill in some form fields
3. Switch to a different branch
4. **Expected**: Form inputs remain filled

### Test 3: Filter Preservation
1. Navigate to a page with search/filter
2. Apply a filter or search term
3. Switch to a different branch
4. **Expected**: Filter remains applied, data refreshes

### Test 4: Loading Behavior
1. Navigate to any page
2. Observe initial full-page loading
3. Switch to a different branch
4. **Expected**: Only subtle spinner appears (not full-page loading)

### Test 5: Error Handling
1. Disconnect network (or simulate API error)
2. Switch to a different branch
3. **Expected**: Error toast appears, current UI state remains visible

## Pattern Template

Apply this pattern to every page using `useBranch`:

```javascript
import { useState, useEffect } from 'react'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'

function MyPage() {
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [data, setData] = useState(null)
    const [activeTab, setActiveTab] = useState('overview') // Preserved!

    const fetchData = async () => {
        try {
            setLoading(true)
            const params = {}
            if (currentBranch) params.branch_id = currentBranch.id
            // Your API calls here...
            setData(result)
        } catch (err) {
            showToast(err.message || 'Error loading data', 'error')
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300) // 300ms debounce
        return () => clearTimeout(timer)
    }, [currentBranch])

    // Only show full-page loading on initial mount
    if (initialLoad && !data) return <PageLoading />

    return (
        <div>
            {/* Subtle spinner during branch switch */}
            {loading && !initialLoad && (
                <div style={{ position: 'fixed', top: 10, right: 10, zIndex: 1000 }}>
                    <span>Loading...</span>
                </div>
            )}
            
            {/* Your page content */}
            <div className="tabs">
                <button onClick={() => setActiveTab('overview')}>Overview</button>
                <button onClick={() => setActiveTab('details')}>Details</button>
            </div>
            
            {/* Content based on activeTab - preserved across branch switches */}
            {activeTab === 'overview' && <Overview data={data} />}
            {activeTab === 'details' && <Details data={data} />}
        </div>
    )
}
```

## Files to Modify

See `plan.md` for complete list organized by priority.

## Common Pitfalls

1. **Don't use `key={currentBranch?.id}`** on components - this causes remounting
2. **Don't reset state in useEffect** - preserve activeTab, formInputs, etc.
3. **Don't show full-page loading on branch switch** - use subtle spinner
4. **Don't forget debounce** - 300ms prevents rapid API calls
5. **Don't use error boundaries for branch switch errors** - use toast notifications
