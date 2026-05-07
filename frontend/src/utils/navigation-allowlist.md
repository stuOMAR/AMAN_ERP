# Navigation Allow-List

This file documents legitimate cases where `window.location` is allowed
instead of `useNavigate()` from React Router.

## Allowed Cases

1. **Full reload after logout** — clears all React state
   - File: `frontend/src/utils/auth.js`
   - Pattern: `window.location.href = '/login'`

2. **OAuth redirect** — external auth providers
   - File: `frontend/src/services/apiClient.js`
   - Pattern: `window.location.href = oauthUrl`

3. **Hard refresh after language change** — re-renders all components
   - File: `frontend/src/components/Layout.jsx`
   - Pattern: `window.location.reload()`

4. **Post-login redirect** — full page load to initialize auth state
   - File: `frontend/src/pages/Login.jsx`
   - Pattern: `window.location.href = '/dashboard'` or `/setup/industry`

5. **Setup wizard navigation** — full page load during onboarding
   - File: `frontend/src/pages/Setup/IndustrySetup.jsx`
   - File: `frontend/src/pages/Setup/ModuleCustomization.jsx`
   - File: `frontend/src/pages/Setup/OnboardingWizard.jsx`
   - Pattern: `window.location.href = '/setup/modules'` or `/dashboard`

6. **Settings reload** — hard refresh after company settings change
   - File: `frontend/src/pages/Settings/CompanySettings.jsx`
   - Pattern: `window.location.reload()`

## CI Gate

`scripts/check_frontend_window_location.py` enforces this allow-list.
Any `window.location` usage outside these files will fail CI.
