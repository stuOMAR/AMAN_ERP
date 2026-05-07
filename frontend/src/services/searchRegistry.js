const REGISTRY_CACHE_KEY = 'aman_search_registry';
const REGISTRY_VERSION_KEY = 'aman_search_registry_version';

let cachedRegistry = null;

export async function fetchSearchRegistry(forceRefresh = false) {
  if (cachedRegistry && !forceRefresh) {
    return cachedRegistry;
  }

  try {
    // Check localStorage cache
    const cached = localStorage.getItem(REGISTRY_CACHE_KEY);
    const version = localStorage.getItem(REGISTRY_VERSION_KEY);

    if (cached && !forceRefresh) {
      cachedRegistry = JSON.parse(cached);
      return cachedRegistry;
    }

    // Fetch from backend
    const response = await fetch('/api/search/registry');
    if (!response.ok) {
      throw new Error('Failed to fetch search registry');
    }

    const data = await response.json();
    cachedRegistry = data.entities || [];

    // Cache in localStorage
    localStorage.setItem(REGISTRY_CACHE_KEY, JSON.stringify(cachedRegistry));
    localStorage.setItem(REGISTRY_VERSION_KEY, Date.now().toString());

    return cachedRegistry;
  } catch (err) {
    console.error('Failed to fetch search registry:', err);
    // Return cached if available
    if (cachedRegistry) return cachedRegistry;

    // Return empty as fallback
    return [];
  }
}

export function getRegistryForEntity(entityCode) {
  if (!cachedRegistry) return null;
  return cachedRegistry.find((e) => e.entity_code === entityCode);
}

export function clearRegistryCache() {
  cachedRegistry = null;
  localStorage.removeItem(REGISTRY_CACHE_KEY);
  localStorage.removeItem(REGISTRY_VERSION_KEY);
}
