# Research: Stable Component Identity Pattern

**Feature**: 026-stable-component-identity  
**Date**: 2026-05-09

## Decision 1: Debounce Duration

**Decision**: 300ms debounce for rapid branch changes  
**Rationale**: Fast enough to feel instant (< 1 second), prevents unnecessary API calls during rapid switching, industry standard for UI debounce patterns  
**Alternatives considered**:
- 150ms: Too fast, may still trigger extra calls
- 500ms: Noticeable delay, users may perceive lag
- 1000ms: Too slow, poor user experience

## Decision 2: Error Handling Strategy

**Decision**: Show error toast notification, keep current UI state visible, allow user to retry manually  
**Rationale**: Most common pattern in production apps, prevents data loss, non-blocking UX  
**Alternatives considered**:
- Inline error banner: More intrusive, may confuse users
- Error modal: Blocks workflow, frustrating for transient errors
- Silent fail: Users unaware of stale data, dangerous for financial data

## Decision 3: Loading State Pattern

**Decision**: `initialLoad` state for first load, subtle spinner for branch switches  
**Rationale**: Full-page loading only on initial mount prevents jarring UX during branch switches  
**Alternatives considered**:
- Always show full-page loading: Disruptive, loses UI state
- Never show loading: Users may not know data is refreshing
- Skeleton screens: More complex to implement, may not be worth effort for branch switch

## Decision 4: State Preservation Scope

**Decision**: Preserve all UI state including active tabs, modals, form inputs, scroll position, filters  
**Rationale**: Maximizes user productivity, prevents frustration from lost work  
**Alternatives considered**:
- Only preserve tabs: Too limited, users still lose form data
- Reset everything: Current behavior, causes user frustration
- Only preserve form data: Inconsistent, confusing UX

## Decision 5: Implementation Scope

**Decision**: Apply pattern to all 138 files using useBranch  
**Rationale**: Consistent behavior across entire application, no edge cases  
**Alternatives considered**:
- Only fix reported pages: Inconsistent behavior, more bug reports later
- Progressive rollout: Complex tracking, delayed benefits
- Only high-traffic pages: Still leaves broken pages

## Decision 6: BranchContext Changes

**Decision**: No changes to BranchContext itself  
**Rationale**: Context already provides necessary API (currentBranch, setBranch), changes would require extensive testing  
**Alternatives considered**:
- Add debounce to context: Would affect all consumers, too broad
- Add loading state to context: Would duplicate page-level state
- Refactor to useReducer: Over-engineering for this scope
