import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import { shopFloorAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { Play, CheckCircle, Pause, ArrowLeft } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const OperationEntry = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const { id } = useParams();
    const navigate = useNavigate();
    const [progress, setProgress] = useState(null);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');

    // Form state for complete
    const [outputQty, setOutputQty] = useState('');
    const [scrapQty, setScrapQty] = useState('0');
    const [downtimeMin, setDowntimeMin] = useState('0');
    const [notes, setNotes] = useState('');
    const [operatorId, setOperatorId] = useState('');

    const loadProgress = () => {
        shopFloorAPI.getWorkOrderProgress(id)
            .then(res => setProgress(res.data))
            .catch(() => toastEmitter.emit(t('common.error'), 'error'))
            .finally(() => setLoading(false));
    };

    useEffect(() => { loadProgress(); }, [id]);

    const handleStart = async (operationId) => {
        if (!operatorId) {
            setError(t('shopfloor.enter_operator_id'));
            return;
        }
        setActionLoading(true);
        setError('');
        setMessage('');
        try {
            await shopFloorAPI.startOperation({
                work_order_id: parseInt(id),
                routing_operation_id: operationId,
                operator_id: parseInt(operatorId),
            });
            setMessage(t('shopfloor.operation_started'));
            loadProgress();
        } catch (e) {
            setError(e.response?.data?.detail || t('shopfloor.start_failed'));
        } finally {
            setActionLoading(false);
        }
    };

    const handleComplete = async (logId) => {
        setActionLoading(true);
        setError('');
        setMessage('');
        try {
            const res = await shopFloorAPI.completeOperation({
                log_id: logId,
                output_quantity: outputQty || '0',
                scrap_quantity: scrapQty || '0',
                downtime_minutes: downtimeMin || '0',
                notes: notes || null,
            });
            const msg = res.data?.is_delayed
                ? t('shopfloor.completed_with_delay')
                : t('shopfloor.operation_completed');
            setMessage(msg);
            loadProgress();
        } catch (e) {
            setError(e.response?.data?.detail || t('shopfloor.complete_failed'));
        } finally {
            setActionLoading(false);
        }
    };

    const handlePause = async (logId) => {
        setActionLoading(true);
        setError('');
        setMessage('');
        try {
            await shopFloorAPI.pauseOperation({ log_id: logId, notes: notes || null });
            setMessage(t('shopfloor.operation_paused'));
            loadProgress();
        } catch (e) {
            setError(e.response?.data?.detail || t('shopfloor.pause_failed'));
        } finally {
            setActionLoading(false);
        }
    };

    const statusColor = (s) => {
        const m = { completed: '#22c55e', in_progress: '#3b82f6', paused: '#f59e0b', pending: '#9ca3af' };
        return m[s] || '#9ca3af';
    };

    if (loading) return <div className="module-container"><PageLoading /></div>;
    if (!progress) return <div className="module-container"><div className="empty-state">{t('shopfloor.not_found')}</div></div>;

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{t('shopfloor.operation_entry')}: {progress.order_number || `WO #${id}`}</h1>
                <button className="btn btn-outline" onClick={() => navigate('/manufacturing/shopfloor')}>
                    <ArrowLeft size={16} /> {t('shopfloor.back_to_dashboard')}
                </button>
            </div>

            {/* Work order summary */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16, marginBottom: 24 }}>
                <div className="stat-card">
                    <div className="stat-label">{t('shopfloor.product')}</div>
                    <div className="stat-value" style={{ fontSize: 15 }}>{progress.product_name}</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">{t('shopfloor.qty')}</div>
                    <div className="stat-value">{progress.quantity}</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">{t('shopfloor.wo_status')}</div>
                    <div className="stat-value" style={{ fontSize: 15 }}>{progress.status}</div>
                </div>
            </div>

            {/* Operator ID */}
            <div className="form-card" style={{ maxWidth: 400, marginBottom: 16 }}>
                <div className="form-group">
                    <label>{t('shopfloor.operator_id')}</label>
                    <input type="number" className="form-control" value={operatorId} onChange={e => setOperatorId(e.target.value)} />
                </div>
            </div>

            {error && <div className="alert alert-danger" style={{ marginBottom: 16 }}>{error}</div>}
            {message && <div className="alert alert-info" style={{ marginBottom: 16 }}>{message}</div>}

            {/* Operation list */}
            <div className="data-table-wrapper">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('shopfloor.sequence')}</th>
                            <th>{t('shopfloor.operation')}</th>
                            <th>{t('shopfloor.status')}</th>
                            <th>{t('shopfloor.operator')}</th>
                            <th>{t('shopfloor.output')}</th>
                            <th>{t('shopfloor.scrap')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(progress.operations || []).map(op => (
                            <tr key={op.operation_id}>
                                <td>{op.sequence}</td>
                                <td>{op.operation_name || '-'}</td>
                                <td>
                                    <span style={{
                                        padding: '2px 8px', borderRadius: 12,
                                        background: `${statusColor(op.status)}20`,
                                        color: statusColor(op.status),
                                        fontSize: 12, fontWeight: 600,
                                    }}>
                                        {t(`shopfloor.status_${op.status}`) || op.status}
                                    </span>
                                </td>
                                <td>{op.operator_name || '-'}</td>
                                <td>{op.output_quantity}</td>
                                <td>{op.scrap_quantity}</td>
                                <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                    {op.status === 'pending' && (
                                        <button className="btn btn-sm btn-primary" disabled={actionLoading}
                                            onClick={() => handleStart(op.operation_id)}>
                                            <Play size={12} /> {t('shopfloor.start')}
                                        </button>
                                    )}
                                    {op.status === 'in_progress' && (
                                        <>
                                            <button className="btn btn-sm btn-primary" disabled={actionLoading}
                                                onClick={() => handleComplete(op.log_id || op.operation_id)}>
                                                <CheckCircle size={12} /> {t('shopfloor.complete')}
                                            </button>
                                            <button className="btn btn-sm btn-outline" disabled={actionLoading}
                                                onClick={() => handlePause(op.log_id || op.operation_id)}>
                                                <Pause size={12} /> {t('shopfloor.pause')}
                                            </button>
                                        </>
                                    )}
                                    {op.status === 'paused' && (
                                        <button className="btn btn-sm btn-primary" disabled={actionLoading}
                                            onClick={() => handleStart(op.operation_id)}>
                                            <Play size={12} /> {t('shopfloor.resume')}
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Complete form (shown when there's in-progress ops) */}
            {progress.operations?.some(o => o.status === 'in_progress') && (
                <div className="form-card" style={{ maxWidth: 500, marginTop: 16 }}>
                    <h3>{t('shopfloor.completion_form')}</h3>
                    <div className="form-group">
                        <label>{t('shopfloor.output_quantity')}</label>
                        <input type="number" className="form-control" step="0.01" value={outputQty} onChange={e => setOutputQty(e.target.value)} />
                    </div>
                    <div className="form-group">
                        <label>{t('shopfloor.scrap_quantity')}</label>
                        <input type="number" className="form-control" step="0.01" value={scrapQty} onChange={e => setScrapQty(e.target.value)} />
                    </div>
                    <div className="form-group">
                        <label>{t('shopfloor.downtime_minutes')}</label>
                        <input type="number" className="form-control" step="0.5" value={downtimeMin} onChange={e => setDowntimeMin(e.target.value)} />
                    </div>
                    <div className="form-group">
                        <label>{t('shopfloor.notes')}</label>
                        <textarea className="form-control" rows={2} value={notes} onChange={e => setNotes(e.target.value)} />
                    </div>
                </div>
            )}
        </div>
    );
};

export default OperationEntry;
