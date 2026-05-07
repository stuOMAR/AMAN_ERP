import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../../utils/api';
import { Play, CheckCircle, RefreshCw, Loader2, Package } from 'lucide-react';

const MrpRecommendations = () => {
    const { t } = useTranslation();
    const [recommendations, setRecommendations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [running, setRunning] = useState(false);
    const [runResult, setRunResult] = useState(null);
    const [filterRunId, setFilterRunId] = useState('');

    const fetchRecommendations = async () => {
        setLoading(true);
        try {
            const params = { limit: 200 };
            if (filterRunId) params.run_id = filterRunId;
            const res = await api.get('/manufacturing/mrp/recommendations', { params });
            setRecommendations(res.data);
        } catch (err) {
            console.error('Failed to fetch recommendations:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchRecommendations(); }, [filterRunId]);

    const handleRun = async () => {
        setRunning(true);
        setRunResult(null);
        try {
            const res = await api.post('/manufacturing/mrp/run');
            setRunResult(res.data);
            fetchRecommendations();
        } catch (err) {
            const detail = err.response?.data?.detail;
            setRunResult({ error: typeof detail === 'object' ? detail.message : detail || 'MRP run failed' });
        } finally {
            setRunning(false);
        }
    };

    const handleAccept = async (id) => {
        try {
            await api.post(`/manufacturing/mrp/recommendations/${id}/accept`);
            fetchRecommendations();
        } catch (err) {
            console.error('Accept failed:', err);
        }
    };

    const openRecs = recommendations.filter(r => r.state === 'open');
    const acceptedRecs = recommendations.filter(r => r.state === 'accepted');

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">{t('MRP Recommendations')}</h2>
                <button
                    onClick={handleRun}
                    disabled={running}
                    className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg
                               hover:bg-blue-700 disabled:opacity-50 text-sm"
                >
                    {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                    {running ? t('Running...') : t('Run MRP')}
                </button>
            </div>

            {runResult && (
                <div className={`p-3 rounded-lg text-sm ${runResult.error ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                    {runResult.error
                        ? runResult.error
                        : `Run ${runResult.run_id}: ${runResult.recommendations_created} recommendations created`}
                </div>
            )}

            <div className="flex items-center gap-4 text-sm text-gray-500">
                <span>{openRecs.length} open</span>
                <span>{acceptedRecs.length} accepted</span>
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
                                <th className="py-2 px-3">Item</th>
                                <th className="py-2 px-3">Warehouse</th>
                                <th className="py-2 px-3">Qty</th>
                                <th className="py-2 px-3">Source</th>
                                <th className="py-2 px-3">State</th>
                                <th className="py-2 px-3">Created</th>
                                <th className="py-2 px-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {recommendations.map(rec => (
                                <tr key={rec.id} className="border-b hover:bg-gray-50">
                                    <td className="py-2 px-3">
                                        <div className="flex items-center gap-1">
                                            <Package size={14} className="text-gray-400" />
                                            #{rec.item_id}
                                        </div>
                                    </td>
                                    <td className="py-2 px-3">#{rec.warehouse_id}</td>
                                    <td className="py-2 px-3 font-mono">{rec.recommended_qty}</td>
                                    <td className="py-2 px-3">{rec.source || '—'}</td>
                                    <td className="py-2 px-3">
                                        <span className={`px-2 py-0.5 rounded-full text-xs
                                            ${rec.state === 'open' ? 'text-yellow-600 bg-yellow-50' : 'text-green-600 bg-green-50'}`}>
                                            {rec.state}
                                        </span>
                                    </td>
                                    <td className="py-2 px-3">{new Date(rec.created_at).toLocaleString()}</td>
                                    <td className="py-2 px-3">
                                        {rec.state === 'open' && (
                                            <button
                                                onClick={() => handleAccept(rec.id)}
                                                className="text-green-600 hover:underline text-xs inline-flex items-center gap-1"
                                            >
                                                <CheckCircle size={12} /> Accept
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {recommendations.length === 0 && (
                        <p className="text-center text-gray-400 py-8">{t('No recommendations')}</p>
                    )}
                </div>
            )}
        </div>
    );
};

export default MrpRecommendations;
