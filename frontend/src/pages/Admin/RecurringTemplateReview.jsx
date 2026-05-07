import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FileCheck, Check, X, RefreshCw, AlertCircle } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const RecurringTemplateReview = () => {
    const { t } = useTranslation();
    const [pending, setPending] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [rejectId, setRejectId] = useState(null);
    const [rejectReason, setRejectReason] = useState('');

    useEffect(() => { fetchPending(); }, []);

    const fetchPending = async () => {
        try {
            setLoading(true);
            setError('');
            const res = await fetch('/api/admin/recurring/pending');
            if (!res.ok) throw new Error('Failed to fetch');
            setPending(await res.json());
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleApprove = async (id) => {
        if (!window.confirm(t('recurring_review.confirm_approve'))) return;
        try {
            setError('');
            const res = await fetch(`/api/admin/recurring/pending/${id}/approve`, { method: 'POST' });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Approval failed');
            }
            fetchPending();
        } catch (e) {
            setError(e.message);
        }
    };

    const handleReject = async () => {
        if (!rejectReason.trim()) return;
        try {
            setError('');
            const res = await fetch(`/api/admin/recurring/pending/${rejectId}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: rejectReason }),
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Rejection failed');
            }
            setRejectId(null);
            setRejectReason('');
            fetchPending();
        } catch (e) {
            setError(e.message);
        }
    };

    const fmtDate = (d) => d ? new Date(d).toLocaleDateString() : '—';
    const fmtAmount = (v) => v != null ? Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 }) : '—';

    return (
        <div style={{ padding: 24, direction: 'rtl' }}>
            <BackButton />
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <FileCheck size={24} /> {t('recurring_review.title')}
            </h1>

            {error && <div style={{ color: '#ef4444', marginBottom: 12 }}>{error}</div>}

            <div style={{ marginBottom: 16 }}>
                <button onClick={fetchPending} style={{ ...btnStyle, background: '#6b7280' }}>
                    <RefreshCw size={16} /> {t('common.refresh')}
                </button>
            </div>

            {rejectId && (
                <div style={{ background: '#fef2f2', padding: 16, borderRadius: 8, marginBottom: 16, border: '1px solid #fecaca' }}>
                    <h3 style={{ marginBottom: 8 }}>{t('recurring_review.reject_title')} #{rejectId}</h3>
                    <textarea
                        placeholder={t('recurring_review.reject_reason_placeholder')}
                        value={rejectReason}
                        onChange={e => setRejectReason(e.target.value)}
                        style={{ ...inputStyle, width: '100%', minHeight: 80, resize: 'vertical' }}
                    />
                    <div style={{ marginTop: 8 }}>
                        <button onClick={handleReject} style={{ ...btnStyle, background: '#ef4444' }}>
                            <X size={16} /> {t('recurring_review.confirm_reject')}
                        </button>
                        <button onClick={() => { setRejectId(null); setRejectReason(''); }} style={{ ...btnStyle, background: '#6b7280', marginRight: 8 }}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </div>
            )}

            {loading ? <p>{t('common.loading')}</p> : (
                pending.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
                        <AlertCircle size={32} style={{ marginBottom: 8 }} />
                        <p>{t('recurring_review.empty')}</p>
                    </div>
                ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                                <th style={thStyle}>{t('recurring_review.id')}</th>
                                <th style={thStyle}>{t('recurring_review.template')}</th>
                                <th style={thStyle}>{t('recurring_review.amount')}</th>
                                <th style={thStyle}>{t('recurring_review.run_date')}</th>
                                <th style={thStyle}>{t('recurring_review.created')}</th>
                                <th style={thStyle}>{t('common.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {pending.map(row => (
                                <tr key={row.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                                    <td style={tdStyle}>{row.id}</td>
                                    <td style={tdStyle}>{row.template_description || `#${row.template_id}`}</td>
                                    <td style={tdStyle}>{fmtAmount(row.amount)}</td>
                                    <td style={tdStyle}>{fmtDate(row.run_date)}</td>
                                    <td style={tdStyle}>{fmtDate(row.created_at)}</td>
                                    <td style={tdStyle}>
                                        <button onClick={() => handleApprove(row.id)} title={t('recurring_review.approve')} style={iconBtn}>
                                            <Check size={14} />
                                        </button>
                                        <button onClick={() => setRejectId(row.id)} title={t('recurring_review.reject')} style={{ ...iconBtn, color: '#ef4444' }}>
                                            <X size={14} />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )
            )}
        </div>
    );
};

const btnStyle = { padding: '8px 16px', borderRadius: 6, border: 'none', color: '#fff', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 14 };
const inputStyle = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 14 };
const thStyle = { textAlign: 'left', padding: '8px 12px', fontWeight: 600 };
const tdStyle = { padding: '8px 12px' };
const iconBtn = { background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: '#10b981' };

export default RecurringTemplateReview;
