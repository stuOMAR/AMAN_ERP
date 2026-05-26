import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../../utils/api';
import { RefreshCw, AlertTriangle, CheckCircle, Clock, Loader2 } from 'lucide-react';

const STATE_STYLES = {
    pending: 'text-yellow-600 bg-yellow-50',
    processing: 'text-blue-600 bg-blue-50',
    submitted: 'text-green-600 bg-green-50',
    cleared: 'text-green-700 bg-green-100',
    reported: 'text-green-700 bg-green-100',
    failed: 'text-red-600 bg-red-50',
    dead_letter: 'text-red-700 bg-red-100',
};

function makeIdempotencyKey(prefix) {
    if (window.crypto?.randomUUID) return `${prefix}:${window.crypto.randomUUID()}`;
    return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

const ZatcaOutboxMonitor = () => {
    const { t } = useTranslation();
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('');

    const fetchRows = async () => {
        setLoading(true);
        try {
            const params = { limit: 100 };
            if (filter) params.state = filter;
            const res = await api.get('/einvoicing/outbox', { params });
            setRows(res.data);
        } catch (err) {
            console.error('Failed to fetch outbox:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchRows(); }, [filter]);

    const handleReprocess = async (id) => {
        try {
            await api.post(`/einvoicing/outbox/${id}/reprocess`, null, {
                headers: { 'Idempotency-Key': makeIdempotencyKey(`zatca-reprocess:${id}`) },
            });
            fetchRows();
        } catch (err) {
            console.error('Reprocess failed:', err);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">{t('einvoicing.zatca_outbox.title')}</h2>
                <div className="flex items-center gap-2">
                    <select
                        value={filter}
                        onChange={e => setFilter(e.target.value)}
                        className="text-sm border rounded px-2 py-1"
                    >
                        <option value="">{t('einvoicing.zatca_outbox.filters.all_states')}</option>
                        <option value="pending">{t('einvoicing.zatca_outbox.filters.pending')}</option>
                        <option value="processing">{t('einvoicing.zatca_outbox.filters.processing')}</option>
                        <option value="failed">{t('einvoicing.zatca_outbox.filters.failed')}</option>
                        <option value="dead_letter">{t('einvoicing.zatca_outbox.filters.dead_letter')}</option>
                        <option value="submitted">{t('einvoicing.zatca_outbox.filters.submitted')}</option>
                        <option value="cleared">{t('einvoicing.zatca_outbox.filters.cleared')}</option>
                    </select>
                    <button onClick={fetchRows} className="p-1 hover:bg-gray-100 rounded">
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>

            {loading ? (
                <div className="flex items-center gap-2 text-gray-500">
                    <Loader2 size={16} className="animate-spin" /> {t('common.loading')}
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b text-left text-gray-500">
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.id')}</th>
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.invoice')}</th>
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.state')}</th>
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.attempts')}</th>
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.last_error')}</th>
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.created')}</th>
                                <th className="py-2 px-3">{t('einvoicing.zatca_outbox.table.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map(row => (
                                <tr key={row.id} className="border-b hover:bg-gray-50">
                                    <td className="py-2 px-3">{row.id}</td>
                                    <td className="py-2 px-3">#{row.invoice_id}</td>
                                    <td className="py-2 px-3">
                                        <span className={`px-2 py-0.5 rounded-full text-xs ${STATE_STYLES[row.state] || ''}`}>
                                            {row.state}
                                        </span>
                                    </td>
                                    <td className="py-2 px-3">{row.attempts}/{row.max_attempts}</td>
                                    <td className="py-2 px-3 max-w-xs truncate">{row.last_error || '—'}</td>
                                    <td className="py-2 px-3">{new Date(row.created_at).toLocaleString()}</td>
                                    <td className="py-2 px-3">
                                        {['failed', 'dead_letter'].includes(row.state) && (
                                            <button
                                                onClick={() => handleReprocess(row.id)}
                                                className="text-blue-600 hover:underline text-xs"
                                            >
                                                {t('einvoicing.zatca_outbox.buttons.reprocess')}
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {rows.length === 0 && (
                        <p className="text-center text-gray-400 py-8">{t('einvoicing.zatca_outbox.no_entries')}</p>
                    )}
                </div>
            )}
        </div>
    );
};

export default ZatcaOutboxMonitor;
