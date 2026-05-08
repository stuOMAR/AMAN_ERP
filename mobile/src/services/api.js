/**
 * Mobile API client — wraps fetch with auth token and base URL.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

// For USB debug: use adb reverse → 127.0.0.1 works.
// For wireless debug: phone connects via laptop's LAN IP.
// We detect the Metro server host from the bundle URL and derive the backend IP.
import { NativeModules } from 'react-native';
function _devServerHost() {
  if (!__DEV__) return null;
  // React Native exposes the packager host through the native module
  const scriptURL =
    NativeModules.SourceCode?.scriptURL ||
    (global.__fbBatchedBridge && global.__fbBatchedBridge._lazyCallableModules?.['SourceCode']?.());
  if (scriptURL) {
    const m = scriptURL.match(/^https?:\/\/([^:/]+)/);
    if (m) return m[1];
  }
  return '127.0.0.1';
}

const _host = _devServerHost();

// Toggle this when running the mobile app in debug mode:
// - true  => use production server data (amanerp.me)
// - false => use local backend via Metro host detection
const USE_SERVER_DATA_IN_DEV = true;
const DEV_SERVER_API_BASE = 'http://amanerp.me/api';

const API_BASE = __DEV__
  ? (USE_SERVER_DATA_IN_DEV ? DEV_SERVER_API_BASE : `http://${_host}:8000/api`)
  : 'https://erp.aman.sa/api';

function normalizeInventoryProduct(item) {
  return {
    ...item,
    name: item.name || item.item_name || item.product_name || '',
    product_name: item.product_name || item.item_name || item.name || '',
    sku: item.sku || item.item_code || item.product_code || '',
    product_code: item.product_code || item.item_code || item.sku || '',
    quantity_on_hand: item.quantity_on_hand ?? item.current_stock ?? item.quantity ?? 0,
    selling_price: item.selling_price ?? item.price ?? 0,
  };
}

function normalizeOrder(item) {
  return {
    ...item,
    order_number: item.order_number || item.so_number || `#${item.id}`,
    total_amount: item.total_amount ?? item.total ?? 0,
    customer_name: item.customer_name || item.party_name || '—',
    created_at: item.created_at || item.order_date || item.created_on || null,
  };
}

function normalizeApproval(item) {
  return {
    ...item,
    entity_type: item.entity_type || item.document_type || item.type || 'طلب',
    reference: item.reference || item.document_number || `${item.document_type || 'طلب'} #${item.document_id || item.id}`,
    description: item.description || item.notes || '',
    requester_name: item.requester_name || item.requested_by_name || '—',
    amount: item.amount ?? item.total_amount ?? null,
  };
}

function normalizeSupplier(item) {
  return {
    ...item,
    name: item.name || item.party_name || item.supplier_name || item.vendor_name || '',
    phone: item.phone || item.mobile || '',
  };
}

function buildQueryString(params) {
  if (!params || typeof params !== 'object') return '';
  const pairs = Object.entries(params)
    .filter(([, v]) => v != null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `?${pairs.join('&')}` : '';
}

function buildFormBody(fields) {
  return Object.entries(fields)
    .filter(([, v]) => v != null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
}

async function getDashboardFallback() {
  /* Try the main web dashboard endpoint first, then fall back to aggregating individual endpoints */
  try {
    const stats = await api.get('/dashboard/stats');
    if (stats && typeof stats === 'object') {
      // Also fetch product count for the fallback path
      let totalProducts = 0;
      try {
        const prodRes = await api.get('/inventory/products', { params: { limit: 1000 } });
        totalProducts = Array.isArray(prodRes) ? prodRes.length : 0;
      } catch { /* ignore */ }
      return {
        inventory_summary: {
          total_products: totalProducts,
          total_stock: 0,
        },
        pending_orders: 0,
        pending_approvals: 0,
        sales: stats.sales ?? 0,
        expenses: stats.expenses ?? 0,
        profit: stats.profit ?? 0,
        cash: stats.cash ?? 0,
        currency_code: 'SAR',
        currency_symbol: 'ر.س',
        recent_quotations: [],
      };
    }
  } catch { /* ignore, fall through */ }

  const [inventoryRes, ordersRes, approvalsRes] = await Promise.allSettled([
    inventoryAPI.list({ limit: 1000 }),
    orderAPI.list({ limit: 200 }),
    approvalAPI.list({ limit: 200 }),
  ]);

  const inventoryItems = inventoryRes.status === 'fulfilled' ? inventoryRes.value : [];
  const orderItems = ordersRes.status === 'fulfilled' ? ordersRes.value : [];
  const approvalItems = approvalsRes.status === 'fulfilled' ? approvalsRes.value : [];

  return {
    inventory_summary: {
      total_products: inventoryItems.length,
      total_stock: inventoryItems.reduce((sum, item) => sum + Number(item.quantity_on_hand ?? item.current_stock ?? 0), 0),
    },
    pending_orders: orderItems.filter((item) => ['draft', 'confirmed'].includes(String(item.status || '').toLowerCase())).length,
    pending_approvals: approvalItems.length,
    currency_code: 'SAR',
    currency_symbol: 'ر.س',
    recent_quotations: [],
  };
}

async function request(method, path, { body, params } = {}) {
  const token = await AsyncStorage.getItem('auth_token');
  const url = `${API_BASE}${path}${buildQueryString(params)}`;

  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    // Attempt token refresh before giving up
    const refreshToken = await AsyncStorage.getItem('refresh_token');
    if (refreshToken && !path.includes('/auth/')) {
      try {
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (refreshRes.ok) {
          const data = await refreshRes.json();
          await AsyncStorage.setItem('auth_token', data.access_token);
          if (data.refresh_token) {
            await AsyncStorage.setItem('refresh_token', data.refresh_token);
          }
          // Retry the original request with new token
          headers['Authorization'] = `Bearer ${data.access_token}`;
          const retryRes = await fetch(url, {
            method,
            headers,
            body: body ? JSON.stringify(body) : undefined,
          });
          if (retryRes.ok) return retryRes.json();
        }
      } catch { /* refresh failed, fall through to logout */ }
    }
    await AsyncStorage.removeItem('auth_token');
    await AsyncStorage.removeItem('refresh_token');
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    let message;
    if (Array.isArray(detail)) {
      message = detail.map((d) => d.msg || JSON.stringify(d)).join('، ');
    } else if (typeof detail === 'string') {
      message = detail;
    } else {
      message = `HTTP ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json();
}

export const api = {
  get: (path, opts) => request('GET', path, opts),
  post: (path, body) => request('POST', path, { body }),
  put: (path, body) => request('PUT', path, { body }),
  delete: (path) => request('DELETE', path),
};

// ── Mobile-specific endpoints ──
export const mobileAPI = {
  login: (companyCode, username, password) => {
    // Backend uses OAuth2PasswordRequestForm (form-urlencoded) + company_code Form field
    const body = buildFormBody({
      username,
      password,
      company_code: companyCode || undefined,
    });
    return fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    }).then(async (res) => {
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const detail = data.detail;
        let msg;
        if (Array.isArray(detail)) msg = detail.map((d) => d.msg || JSON.stringify(d)).join('، ');
        else if (typeof detail === 'string') msg = detail;
        else msg = `HTTP ${res.status}`;
        throw new Error(msg);
      }
      return res.json();
    });
  },
  dashboard: async () => {
    try {
      return await api.get('/mobile/dashboard');
    } catch {
      return getDashboardFallback();
    }
  },
  batchSync: (deviceId, items) =>
    api.post('/mobile/sync', { device_id: deviceId, items }),
  syncStatus: (deviceId) =>
    api.get('/mobile/sync/status', { params: { device_id: deviceId } }),
  resolveConflict: (syncQueueId, resolution, mergedPayload) =>
    api.post('/mobile/sync/resolve', {
      sync_queue_id: syncQueueId,
      resolution,
      merged_payload: mergedPayload,
    }),
  registerDevice: (deviceId, platform, fcmToken) =>
    api.post('/mobile/register-device', {
      device_id: deviceId,
      platform,
      fcm_token: fcmToken,
    }),
};

// ── Existing endpoints used by mobile ──
export const inventoryAPI = {
  list: async (params) => {
    const result = await api.get('/inventory/products', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items.map(normalizeInventoryProduct);
  },
  getProduct: async (id) => normalizeInventoryProduct(await api.get(`/inventory/products/${id}`)),
};

export const quotationAPI = {
  list: (params) => api.get('/sales/quotations', { params }),
  create: (data) => api.post('/sales/quotations', data),
};

export const orderAPI = {
  list: async (params) => {
    const result = await api.get('/sales/orders', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items.map(normalizeOrder);
  },
};

export const approvalAPI = {
  list: async (params) => {
    const result = await api.get('/approvals/pending', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items.map(normalizeApproval);
  },
  approve: (id, notes = '') => api.post(`/approvals/requests/${id}/action`, { action: 'approve', notes }),
  reject: (id, reason) => api.post(`/approvals/requests/${id}/action`, { action: 'reject', notes: reason }),
};

// ── Customer endpoints ──
export const customerAPI = {
  list: async (params) => {
    const result = await api.get('/sales/customers', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items;
  },
  get: (id) => api.get(`/sales/customers/${id}`),
  transactions: (id) => api.get(`/sales/customers/${id}/transactions`),
};

// ── Invoice endpoints ──
export const invoiceAPI = {
  list: async (params) => {
    const result = await api.get('/sales/invoices', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items;
  },
  get: (id) => api.get(`/sales/invoices/${id}`),
};

// ── HR / Employees endpoints ──
export const hrAPI = {
  employees: async (params) => {
    const result = await api.get('/hr/employees', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items;
  },
};

// ── Dashboard stats (web) ──
export const dashboardAPI = {
  stats: (params) => api.get('/dashboard/stats', { params }),
};

// ── Reports ──
export const reportsAPI = {
  salesSummary: () => api.get('/sales/summary'),
};

// ── Purchase (Buying) endpoints ──
export const purchaseInvoiceAPI = {
  list: async (params) => {
    const result = await api.get('/buying/invoices', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items;
  },
  get: (id) => api.get(`/buying/invoices/${id}`),
};

export const purchaseOrderAPI = {
  list: async (params) => {
    const result = await api.get('/buying/orders', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items;
  },
};

// ── Supplier endpoints ──
export const supplierAPI = {
  list: async (params) => {
    const result = await api.get('/parties/suppliers', { params });
    const items = Array.isArray(result) ? result : (result?.items || []);
    return items.map(normalizeSupplier);
  },
};

// ── Tax endpoints ──
export const taxAPI = {
  getBranchTax: (branchId) => api.get(`/taxes/rates/branch/${branchId}`),
};
