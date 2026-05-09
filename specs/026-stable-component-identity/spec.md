# Feature Specification: Stable Component Identity

**Feature Branch**: `026-stable-component-identity`  
**Created**: 2026-05-09  
**Status**: Draft  
**Input**: User description: "Apply Stable Component Identity pattern across ALL frontend pages to prevent state loss when switching branches"

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

When users switch branches in the Topbar branch selector, the application loses all UI state in the current page (active tabs, open modals, form inputs, scroll position, filters). This happens because components either remount due to aggressive key props or show full-page loading screens that wipe the UI. The goal is to ensure seamless branch switching where data refreshes reactively but the UI state is preserved.

### In Scope

- All pages under `frontend/src/pages/` (138 files reference `useBranch` or `currentBranch`)
- All components under `frontend/src/components/` that use `useBranch`
- Branch selector behavior in Topbar component
- Loading state management during branch switches

### Out of Scope

- Backend API changes
- New features or functionality
- Performance optimization beyond branch switching
- Mobile-specific optimizations

### Functional Flow Summary

- **Flow-001**: User is on any page with specific UI state (active tab, filters, scroll position) → User switches branch via Topbar dropdown → Page data refreshes in background → UI state remains intact → User sees updated data in same view
- **Flow-002**: User is on a page for the first time → Page shows full loading indicator → Data loads → User interacts with page → User switches branch → Subtle loading indicator appears → Data refreshes → User continues working without interruption
- **Flow-003**: User has form inputs filled → User switches branch → Form inputs remain filled → Background data refresh occurs → Form validation updates if needed

### Acceptance Criteria

1. **Given** user is on Taxes page with "Rates" tab active, **When** user switches branch, **Then** "Rates" tab remains active and data refreshes in background
2. **Given** user has a modal open, **When** user switches branch, **Then** modal remains open with current state
3. **Given** user has form inputs filled, **When** user switches branch, **Then** form inputs remain filled
4. **Given** user is on any page, **When** user switches branch, **Then** page does not show full-page loading screen (only subtle indicator)
5. **Given** user is on any page for first time, **When** page loads, **Then** full-page loading indicator appears until initial data loads
6. **Given** user switches branch rapidly, **When** multiple branch changes occur, **Then** only the final branch data is fetched (debouncing)
7. **Given** user is on a page with filters applied, **When** user switches branch, **Then** filters remain applied with updated data

### Edge Cases

- When branch switch causes data to become unavailable: System shows error toast, keeps current UI state visible, allows manual retry
- When network errors occur during background data refresh: System shows error toast, keeps current UI state visible, allows manual retry
- When user is in the middle of a form submission when branch changes: System completes the submission with original branch context, then refreshes data
- When branch switch occurs while a modal with unsaved changes is open: Modal remains open with unsaved data preserved, background data refreshes

## Clarifications

### Session 2026-05-09

- Q: How should the system handle errors during branch switch? → A: Show error toast notification, keep current UI state visible, allow user to retry manually
- Q: How long should the system wait before fetching data after the last branch change? → A: 300ms debounce

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST preserve UI state (active tabs, modals, form inputs, scroll position, filters) when user switches branches
- **FR-002**: System MUST refresh page data reactively when `currentBranch` changes via `useEffect` hooks
- **FR-003**: System MUST show full-page loading only on initial page mount, not on branch switches
- **FR-004**: System MUST show subtle loading indicators (skeleton/spinner) during background data refresh on branch switch
- **FR-005**: System MUST remove any `key` props that depend on `currentBranch` or branch-related state from Routes, Page components, or Layout wrappers
- **FR-006**: System MUST implement `initialLoad` state pattern for pages that show full-page loading
- **FR-007**: System MUST ensure `useEffect` hooks properly depend on `currentBranch` for data fetching
- **FR-008**: System MUST debounce rapid branch changes with 300ms delay to avoid unnecessary API calls
- **FR-009**: System MUST handle errors during background data refresh by showing error toast notification, keeping current UI state visible, and allowing user to retry manually
- **FR-010**: System MUST validate that all 138 files using `useBranch` follow the Stable Component Identity pattern

### Key Entities

- **BranchContext**: Context provider that manages current branch state and triggers re-renders
- **useBranch Hook**: Hook that provides `currentBranch`, `setBranch`, and `branches` to components
- **Page Components**: All pages under `frontend/src/pages/` that consume branch state
- **UI State**: Active tabs, modals, form inputs, scroll position, filters that must be preserved

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can switch branches without losing their current view state (tabs, modals, forms) in 100% of page interactions
- **SC-002**: Branch switch data refresh completes within 2 seconds without showing full-page loading
- **SC-003**: 100% of pages using `useBranch` implement the Stable Component Identity pattern
- **SC-004**: Zero instances of full-page loading screens during branch switches (only subtle indicators)
- **SC-005**: Users report seamless branch switching experience with no visible page reloads
- **SC-006**: All UI state (active tabs, form inputs, filters) persists across branch changes
- **SC-007**: Background data refresh errors are handled gracefully without disrupting user workflow

## Assumptions

- Existing `useBranch` hook and `BranchContext` will continue to be used
- All pages already have `useEffect` hooks for data fetching (may need updates)
- Backend APIs support branch filtering via `branch_id` parameter
- Network connectivity is stable enough for background data refresh
- Users expect instant UI feedback when switching branches
- The pattern applied to `TaxHome.jsx` serves as the template for all other pages

## Dependencies

- `BranchContext` must be properly configured in all page components
- All pages must use `useBranch` hook to access branch state
- Backend APIs must support branch filtering
- `PageLoading` component exists for initial load states
- Subtle loading indicators (skeleton/spinner) are available in component library
