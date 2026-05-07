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
            await api.post(`/einvoicing/outbox/${id}/reprocess`);
            fetchRows();
        } catch (err) {
            console.error('Reprocess failed:', err);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">{t('ZATCA Outbox')}</h2>
                <div className="flex items-center gap-2">
                    <select
                        value={filter}
                        onChange={e => setFilter(e.target.value)}
                        className="text-sm border rounded px-2 py-1"
                    >
                        <option value="">{t('All States')}</option>
                        <option value="pending">Pending</option>
                        <option value="processing">Processing</option>
                        <option value="failed">Failed</option>
                        <option value="dead_letter">Dead Letter</option>
                        <option value="submitted">Submitted</option>
                        <option value="cleared">Cleared</option>
                    </select>
                    <button onClick={fetchRows} className="p-1 hover:bg-gray-100 rounded">
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>

            {loading ? (
                <div className="flex items-center gap-2 text-gray-500">
                    <Loader2 size={16} className="animate-spin" /> {t('Loading...')}
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b text-left text-gray-500">
                                <th className="py-2 px-3">ID</th>
                                <th className="py-2 px-3">Invoice</th>
                                <th className="py-2 px-3">State</th>
                                <th className="py-2 px-3">Attempts</th>
                                <th className="py-2 px-3">Last Error</th>
                                <th className="py-2 px-3">Created</th>
                                <th className="py-2 px-3">Actions</th>
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
                                                Reprocess
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {rows.length === 0 && (
                        <p className="text-center text-gray-400 py-8">{t('No outbox rows')}</p>
                    )}
                </div>
            )}
        </div>
    );
};

export default ZatcaOutboxMonitor;
