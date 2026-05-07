"T239: StrictMode routes allow-list — per-route enablement during transition."

export const STRICT_MODE_ROUTES = [
  // Routes that are confirmed StrictMode-clean
  '/dashboard',
  '/reports',
  '/settings',
];

export function isStrictModeEnabled(pathname) {
  return STRICT_MODE_ROUTES.some((route) => pathname.startsWith(route));
}
