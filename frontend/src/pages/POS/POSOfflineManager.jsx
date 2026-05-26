import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { posAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { useToast } from '../../context/ToastContext';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';

/**
 * POS-001: Offline Mode + Auto Sync
 * Uses IndexedDB for offline storage and ServiceWorker for connectivity detection
 */

const DB_NAME = 'aman_pos_offline';
const DB_VERSION = 1;
const STORE_NAME = 'pending_orders';

function openDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'localId', autoIncrement: true });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function savePendingOrder(order) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        order.createdAt = new Date().toISOString();
        order.synced = false;
        const req = store.add(order);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function getPendingOrders() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const store = tx.objectStore(STORE_NAME);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result.filter(o => !o.synced));
        req.onerror = () => reject(req.error);
    });
}

async function markSynced(localId) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const getReq = store.get(localId);
        getReq.onsuccess = () => {
            const order = getReq.result;
            if (order) {
                order.synced = true;
                order.syncedAt = new Date().toISOString();
                store.put(order);
            }
            resolve();
        };
        getReq.onerror = () => reject(getReq.error);
    });
}

async function clearSyncedOrders() {
    const db = await openDB();
    return new Promise((resolve) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const req = store.getAll();
        req.onsuccess = () => {
            req.result.filter(o => o.synced).forEach(o => store.delete(o.localId));
            resolve();
        };
    });
}

function POSOfflineManager() {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [isOnline, setIsOnline] = useState(navigator.onLine);
    const [pendingOrders, setPendingOrders] = useState([]);
    const [syncing, setSyncing] = useState(false);
    const [syncLog, setSyncLog] = useState([]);
    const [autoSync, setAutoSync] = useState(true);
    const intervalRef = useRef(null);

    const refreshPending = useCallback(async () => {
        try {
            const orders = await getPendingOrders();
            setPendingOrders(orders);
        } catch (e) { showToast(t('common.error_occurred'), 'error'); }
    }, []);

    useEffect(() => {
        const goOnline = () => { setIsOnline(true); if (autoSync) syncAll(); };
        const goOffline = () => setIsOnline(false);
        window.addEventListener('online', goOnline);
        window.addEventListener('offline', goOffline);
        refreshPending();
        return () => { window.removeEventListener('online', goOnline); window.removeEventListener('offline', goOffline); };
    }, [autoSync]);

    useEffect(() => {
        if (autoSync && isOnline) {
            intervalRef.current = setInterval(() => { syncAll(); }, 30000);
            return () => clearInterval(intervalRef.current);
        }
    }, [autoSync, isOnline]);

    const syncAll = async () => {
        if (syncing) return;
        setSyncing(true);
        const log = [];
        try {
            const orders = await getPendingOrders();
            for (const order of orders) {
                try {
                    const idempotencyKey = order.idempotencyKey || order.orderData?.client_order_id;
                    await posAPI.createOrder(order.orderData, idempotencyKey);
                    await markSynced(order.localId);
                    log.push({ localId: order.localId, status: 'success', time: new Date().toLocaleTimeString() });
                } catch (err) {
                    log.push({ localId: order.localId, status: 'failed', error: err.message, time: new Date().toLocaleTimeString() });
                }
            }
            await clearSyncedOrders();
            await refreshPending();
        } catch (e) { showToast(t('common.error_occurred'), 'error'); }
        finally {
            setSyncing(false);
            setSyncLog(prev => [...log, ...prev].slice(0, 50));
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📡 {t('pos.offline.title', 'وضع العمل بدون إنترنت')}</h1>
                    <p className="workspace-subtitle">{t('pos.offline.subtitle', 'إدارة الطلبات المعلقة والمزامنة التلقائية')}</p>
                </div>
            </div>

            {/* Connection Status */}
            <div className="metrics-grid" style={{ marginBottom: 16 }}>
                <div className="metric-card">
                    <div className="metric-label">{t('pos.offline.connection', 'حالة الاتصال')}</div>
                    <div className="metric-value" style={{ color: isOnline ? 'var(--success)' : 'var(--danger)' }}>
                        {isOnline ? '🟢 ' + t('pos.offline.online', 'متصل') : '🔴 ' + t('pos.offline.disconnected', 'غير متصل')}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('pos.offline.pending_orders', 'طلبات معلقة')}</div>
                    <div className="metric-value text-warning">{pendingOrders.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('pos.offline.auto_sync', 'المزامنة التلقائية')}</div>
                    <div>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                            <input type="checkbox" checked={autoSync} onChange={e => setAutoSync(e.target.checked)} />
                            <span style={{ fontWeight: 600 }}>{autoSync ? t('pos.offline.enabled', 'مفعّل') : t('pos.offline.disabled', 'معطّل')}</span>
                        </label>
                    </div>
                </div>
                <div className="metric-card">
                    <button className="btn btn-primary" onClick={syncAll} disabled={syncing || !isOnline || pendingOrders.length === 0} style={{ width: '100%' }}>
                        {syncing ? '⏳ ...' : '🔄 ' + t('pos.offline.sync_now', 'مزامنة الآن')}
                    </button>
                </div>
            </div>

            {/* Pending Orders */}
            {pendingOrders.length > 0 && (
                <div className="section-card" style={{ marginBottom: 16 }}>
                    <h3 className="section-title">{t('pos.offline.pending_list', 'الطلبات المعلقة للمزامنة')}</h3>
                    <div className="table-responsive">
                        <table className="data-table">
                            <thead><tr>
                                <th>#</th>
                                <th>{t('pos.offline.created', 'وقت الإنشاء')}</th>
                                <th>{t('pos.offline.items', 'عدد الأصناف')}</th>
                                <th>{t('common.total', 'الإجمالي')}</th>
                            </tr></thead>
                            <tbody>
                                {pendingOrders.map((o, i) => (
                                    <tr key={o.localId}>
                                        <td>{i + 1}</td>
                                        <td>{new Date(o.createdAt).toLocaleString('ar-SA')}</td>
                                        <td>{o.orderData?.items?.length || 0}</td>
                                        <td>{o.preview?.total_amount ? formatNumber(o.preview.total_amount) : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Sync Log */}
            {syncLog.length > 0 && (
                <div className="section-card">
                    <h3 className="section-title">{t('pos.offline.sync_log', 'سجل المزامنة')}</h3>
                    <div className="table-responsive">
                        <table className="data-table">
                            <thead><tr><th>{t('pos.offline.time', 'الوقت')}</th><th>ID</th><th>{t('common.status_title', 'الحالة')}</th><th>{t('pos.offline.details', 'التفاصيل')}</th></tr></thead>
                            <tbody>
                                {syncLog.map((log, i) => (
                                    <tr key={i}>
                                        <td>{log.time}</td>
                                        <td>#{log.localId}</td>
                                        <td><span className={`status-badge ${log.status === 'success' ? 'status-active' : 'status-rejected'}`}>{log.status === 'success' ? t('pos.offline.synced', 'تمت المزامنة') : t('pos.offline.failed', 'فشل')}</span></td>
                                        <td>{log.error || '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}

// Export the utility functions for use by POSInterface
export { savePendingOrder, getPendingOrders };
export default POSOfflineManager;
