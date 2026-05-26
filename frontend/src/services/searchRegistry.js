import api from './apiClient';
import { getCompanyId, getUser } from '../utils/auth';

const REGISTRY_CACHE_PREFIX = 'aman_search_registry';
const REGISTRY_VERSION_PREFIX = 'aman_search_registry_version';
const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

let cachedRegistry = null;
let cachedContextKey = null;

function getRegistryCacheKeys() {
  const user = getUser();
  const companyId = getCompanyId() || user?.company_id || 'unknown-company';
  const userId = user?.id || user?.user_id || user?.username || 'anonymous';
  const contextKey = `${companyId}:${userId}`;
  return {
    contextKey,
    registryKey: `${REGISTRY_CACHE_PREFIX}:${contextKey}`,
    versionKey: `${REGISTRY_VERSION_PREFIX}:${contextKey}`,
  };
}

export async function fetchSearchRegistry(forceRefresh = false) {
  const { contextKey, registryKey, versionKey } = getRegistryCacheKeys();

  if (cachedRegistry && cachedContextKey === contextKey && !forceRefresh) {
    return cachedRegistry;
  }

  try {
    // Check localStorage cache
    const cached = localStorage.getItem(registryKey);
    const versionStr = localStorage.getItem(versionKey);

    if (cached && versionStr && !forceRefresh) {
      const version = parseInt(versionStr, 10);
      if (Date.now() - version < CACHE_TTL_MS) {
        cachedRegistry = JSON.parse(cached);
        cachedContextKey = contextKey;
        return cachedRegistry;
      }
    }

    // Fetch from backend using standard apiClient
    const response = await api.get('/search/registry');
    const data = response.data || {};
    cachedRegistry = data.entities || [];
    cachedContextKey = contextKey;

    // Cache in localStorage
    localStorage.setItem(registryKey, JSON.stringify(cachedRegistry));
    localStorage.setItem(versionKey, Date.now().toString());

    return cachedRegistry;
  } catch (err) {
    console.error('Failed to fetch search registry:', err);
    // Return cached if available
    if (cachedRegistry && cachedContextKey === contextKey) return cachedRegistry;

    const cached = localStorage.getItem(registryKey);
    if (cached) {
      try {
        cachedRegistry = JSON.parse(cached);
        cachedContextKey = contextKey;
        return cachedRegistry;
      } catch (_) {}
    }

    // Return empty as fallback
    return [];
  }
}

export function getRegistryForEntity(entityCode) {
  if (!cachedRegistry) return null;
  return cachedRegistry.find((e) => e.entity_code === entityCode);
}

export function clearRegistryCache() {
  const { registryKey, versionKey } = getRegistryCacheKeys();
  cachedRegistry = null;
  cachedContextKey = null;
  localStorage.removeItem(registryKey);
  localStorage.removeItem(versionKey);
}
