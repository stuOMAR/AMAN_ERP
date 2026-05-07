import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../../utils/api';
import { Wifi, WifiOff, RefreshCw, AlertTriangle, CheckCircle, Clock } from 'lucide-react';

const STATUS_COLORS = {
    queued: 'text-yellow-600 bg-yellow-50',
    reconciling: 'text-blue-600 bg-blue-50',
    committed: 'text-green-600 bg-green-50',
    manual_review: 'text-red-600 bg-red-50',
    failed: 'text-red-600 bg-red-50',
};

const ReconnectStatus = ({ deviceId }) => {
    const { t } = useTranslation();
    const [batches, setBatches] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchBatches = async () => {
        try {
            const res = await api.get('/pos/offline/batches', { params: { device_id: deviceId } });
            setBatches(res.data);
        } catch (err) {
            console.error('Failed to fetch offline batches:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchBatches();
        const interval = setInterval(fetchBatches, 10000);
        return () => clearInterval(interval);
    }, [deviceId]);

    const handleRetry = async (batchId) => {
        try {
            await api.post(`/pos/offline/batches/${batchId}/retry`);
            fetchBatches();
        } catch (err) {
            console.error('Retry failed:', err);
        }
    };

    if (loading) return <div className="text-sm text-gray-500">{t('Loading...')}</div>;

    const pending = batches.filter(b => ['queued', 'reconciling'].includes(b.state));
    const issues = batches.filter(b => ['manual_review', 'failed'].includes(b.state));
    const completed = batches.filter(b => b.state === 'committed');

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                {pending.length > 0 ? (
                    <WifiOff size={18} className="text-yellow-500" />
                ) : (
                    <Wifi size={18} className="text-green-500" />
                )}
                <h3 className="font-medium">{t('Offline Sync Status')}</h3>
            </div>

            {pending.length > 0 && (
                <div className="p-3 bg-yellow-50 rounded-lg">
                    <p className="text-sm text-yellow-700">
                        {pending.length} batch(es) pending sync
                    </p>
                </div>
            )}

            {issues.length > 0 && (
                <div className="space-y-2">
                    <h4 className="text-sm font-medium text-red-600 flex items-center gap-1">
                        <AlertTriangle size={14} />
                        {t('Needs Review')}
                    </h4>
                    {issues.map(batch => (
                        <div key={batch.id} className="p-3 bg-red-50 rounded-lg flex items-center justify-between">
                            <div>
                                <p className="text-sm font-medium">Batch #{batch.id}</p>
                                <p className="text-xs text-gray-500">
                                    {batch.failure_reason_code}: {batch.failure_detail}
                                </p>
                            </div>
                            <button
                                onClick={() => handleRetry(batch.id)}
                                className="px-3 py-1 text-xs bg-white border rounded hover:bg-gray-50"
                            >
                                <RefreshCw size={12} className="inline mr-1" />
                                Retry
                            </button>
                        </div>
                    ))}
                </div>
            )}

            {batches.length === 0 && (
                <p className="text-sm text-gray-500">{t('No offline batches')}</p>
            )}
        </div>
    );
};

export default ReconnectStatus;
