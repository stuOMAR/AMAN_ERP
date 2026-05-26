import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { purchasesAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { formatDate, formatDateTime } from '../../utils/dateUtils';
import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
import { Play, Package, DollarSign, AlertTriangle } from 'lucide-react';
import '../../components/ModuleStyles.css';

const BlanketPODetail = () => {
    const { id } = useParams();
    const { t } = useTranslation();
    const { showToast } = useToast();
    const currency = getCurrency();
    const [bpo, setBpo] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showReleaseModal, setShowReleaseModal] = useState(false);
    const [showAmendModal, setShowAmendModal] = useState(false);
    const [releaseForm, setReleaseForm] = useState({ release_quantity: '', release_date: '' });
    const [amendForm, setAmendForm] = useState({ new_price: '', effective_date: '', reason: '' });
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => { fetchDetail(); }, [id]);

    const fetchDetail = async () => {
        try {
            setLoading(true);
            const res = await purchasesAPI.getBlanketPO(id);
            setBpo(res.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleActivate = async () => {
        try {
            await purchasesAPI.activateBlanketPO(id);
            showToast(t('blanket_po.activated'), 'success');
            fetchDetail();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const handleRelease = async (e) => {
        e.preventDefault();
        if (submitting) return;
        setSubmitting(true);
        try {
            const payload = {
                release_quantity: String(releaseForm.release_quantity),
                release_date: releaseForm.release_date || null,
            };
            const res = await purchasesAPI.createBlanketPORelease(id, payload);
            if (res.data?.warning) {
                showToast(res.data.warning, 'warning');
            } else {
                showToast(t('blanket_po.release_created'), 'success');
            }
            setShowReleaseModal(false);
            setReleaseForm({ release_quantity: '', release_date: '' });
            fetchDetail();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const handleAmendPrice = async (e) => {
        e.preventDefault();
        if (submitting) return;
        setSubmitting(true);
        try {
            const payload = {
                new_price: String(amendForm.new_price),
                effective_date: amendForm.effective_date,
                reason: amendForm.reason || null,
            };
            await purchasesAPI.amendBlanketPOPrice(id, payload);
            showToast(t('blanket_po.price_amended'), 'success');
            setShowAmendModal(false);
            setAmendForm({ new_price: '', effective_date: '', reason: '' });
            fetchDetail();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const statusBadge = (s) => {
        const map = {
            draft: 'bg-gray-100 text-gray-600',
            active: 'bg-green-100 text-green-700',
            expired: 'bg-red-100 text-red-600',
            completed: 'bg-blue-100 text-blue-700',
            cancelled: 'bg-orange-100 text-orange-600',
        };
        return <span className={`badge ${map[s] || 'bg-gray-100'}`}>{t(`blanket_po.status_${s}`) || s}</span>;
    };

    if (loading) return <div className="workspace fade-in"><div className="text-center p-8">{t('common.loading')}</div></div>;
    if (!bpo) return <div className="workspace fade-in"><div className="text-center p-8">{t('blanket_po.not_found')}</div></div>;

    const remainingQty = bpo.remaining_quantity;
    const remainingAmt = bpo.remaining_amount;
    const progressPct = bpo.consumption_progress_pct || '0';

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{bpo.agreement_number}</h1>
                        <p className="workspace-subtitle">
                            {bpo.supplier_name || `Supplier #${bpo.supplier_id}`} · {statusBadge(bpo.status)}
                        </p>
                    </div>
                    <div className="d-flex gap-2">
                        {bpo.status === 'draft' && (
                            <button className="btn btn-success" onClick={handleActivate}>
                                <Play size={16} /> {t('blanket_po.activate')}
                            </button>
                        )}
                        {bpo.status === 'active' && (
                            <>
                                <button className="btn btn-primary" onClick={() => setShowReleaseModal(true)}>
                                    <Package size={16} /> {t('blanket_po.release')}
                                </button>
                                <button className="btn btn-outline" onClick={() => setShowAmendModal(true)}>
                                    <DollarSign size={16} /> {t('blanket_po.amend_price')}
                                </button>
                            </>
                        )}
                    </div>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-4 gap-4 mb-4">
                <div className="card p-4">
                    <div className="text-sm text-muted mb-1">{t('blanket_po.total_qty')}</div>
                    <div className="text-xl font-bold">{formatNumber(bpo.total_quantity)}</div>
                </div>
                <div className="card p-4">
                    <div className="text-sm text-muted mb-1">{t('blanket_po.unit_price')}</div>
                    <div className="text-xl font-bold">{formatNumber(bpo.unit_price)} {currency}</div>
                </div>
                <div className="card p-4">
                    <div className="text-sm text-muted mb-1">{t('blanket_po.total_amount')}</div>
                    <div className="text-xl font-bold">{formatNumber(bpo.total_amount)} {currency}</div>
                </div>
                <div className="card p-4">
                    <div className="text-sm text-muted mb-1">{t('blanket_po.remaining')}</div>
                    <div className="text-xl font-bold text-green-600">{formatNumber(remainingQty)} / {formatNumber(remainingAmt)} {currency}</div>
                </div>
            </div>

            {/* Progress Bar */}
            <div className="card section-card mb-4 p-4">
                <div className="d-flex justify-content-between mb-2">
                    <span className="font-semibold">{t('blanket_po.consumption_progress')}</span>
                    <span>{formatNumber(progressPct, 1)}%</span>
                </div>
                <div style={{ height: 10, background: '#e5e7eb', borderRadius: 5, overflow: 'hidden' }}>
                    <div style={{ width: `${progressPct}%`, height: '100%', background: bpo.is_fully_released ? '#3b82f6' : '#22c55e', borderRadius: 5, transition: 'width 0.3s' }} />
                </div>
                <div className="d-flex justify-content-between mt-2 text-sm text-muted">
                    <span>{t('blanket_po.released')}: {formatNumber(bpo.released_quantity)} ({formatNumber(bpo.released_amount)} {currency})</span>
                    <span>{t('blanket_po.validity')}: {formatDate(bpo.valid_from)} → {formatDate(bpo.valid_to)}</span>
                </div>
            </div>

            {/* Release Orders */}
            <div className="card section-card mb-4">
                <div className="card-header"><h3>{t('blanket_po.releases')}</h3></div>
                <div className="data-table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>{t('blanket_po.release_qty')}</th>
                                <th>{t('blanket_po.release_amount')}</th>
                                <th>{t('blanket_po.release_date')}</th>
                                <th>{t('blanket_po.po_number')}</th>
                                <th>{t('blanket_po.created_by')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(bpo.releases || []).map((r, idx) => (
                                <tr key={r.id}>
                                    <td>{idx + 1}</td>
                                    <td>{formatNumber(r.release_quantity)}</td>
                                    <td>{formatNumber(r.release_amount)} {currency}</td>
                                    <td>{formatDate(r.release_date)}</td>
                                    <td>{r.po_number || '—'}</td>
                                    <td>{r.created_by || '—'}</td>
                                </tr>
                            ))}
                            {(!bpo.releases || bpo.releases.length === 0) && (
                                <tr><td colSpan="6" className="text-center text-muted p-4">{t('blanket_po.no_releases')}</td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Price Amendment History */}
            {bpo.price_amendment_history && bpo.price_amendment_history.length > 0 && (
                <div className="card section-card mb-4">
                    <div className="card-header"><h3>{t('blanket_po.price_history')}</h3></div>
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('blanket_po.effective_date')}</th>
                                    <th>{t('blanket_po.old_price')}</th>
                                    <th>{t('blanket_po.new_price')}</th>
                                    <th>{t('blanket_po.reason')}</th>
                                    <th>{t('blanket_po.amended_at')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {bpo.price_amendment_history.map((h, idx) => (
                                    <tr key={idx}>
                                        <td>{formatDate(h.effective_date)}</td>
                                        <td>{formatNumber(h.old_price)} {currency}</td>
                                        <td className="font-semibold">{formatNumber(h.new_price)} {currency}</td>
                                        <td>{h.reason || '—'}</td>
                                        <td>{h.amended_at ? formatDateTime(h.amended_at) : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Release Modal */}
            {showReleaseModal && (
                <div className="modal-overlay" onClick={() => setShowReleaseModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 450 }}>
                        <h3 className="modal-title">{t('blanket_po.create_release')}</h3>
                        {bpo.is_fully_released && (
                            <div className="d-flex align-items-center gap-2 p-3 mb-3 bg-yellow-50 text-yellow-700 rounded">
                                <AlertTriangle size={16} />
                                <span>{t('blanket_po.fully_consumed_warning')}</span>
                            </div>
                        )}
                        <form onSubmit={handleRelease} className="space-y-4">
                            <div className="form-group">
                                <label className="form-label">{t('blanket_po.release_qty')} *</label>
                                <input type="number" step="0.01" min="0.01" className="form-input" required
                                    value={releaseForm.release_quantity}
                                    onChange={e => setReleaseForm({ ...releaseForm, release_quantity: e.target.value })} />
                                <div className="text-sm text-muted mt-1">{t('blanket_po.remaining')}: {formatNumber(remainingQty)}</div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('blanket_po.release_date')}</label>
                                <DateInput className="form-input" value={releaseForm.release_date}
                                    onChange={e => setReleaseForm({ ...releaseForm, release_date: e.target.value })} />
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1" disabled={submitting}>
                                    {submitting ? t('common.saving') : t('blanket_po.release')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowReleaseModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Amend Price Modal */}
            {showAmendModal && (
                <div className="modal-overlay" onClick={() => setShowAmendModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 450 }}>
                        <h3 className="modal-title">{t('blanket_po.amend_price')}</h3>
                        <div className="p-3 mb-3 bg-blue-50 text-blue-700 rounded text-sm">
                            {t('blanket_po.current_price')}: {formatNumber(bpo.unit_price)} {currency}
                        </div>
                        <form onSubmit={handleAmendPrice} className="space-y-4">
                            <div className="form-group">
                                <label className="form-label">{t('blanket_po.new_price')} *</label>
                                <input type="number" step="0.01" min="0.01" className="form-input" required
                                    value={amendForm.new_price}
                                    onChange={e => setAmendForm({ ...amendForm, new_price: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('blanket_po.effective_date')} *</label>
                                <DateInput className="form-input" required value={amendForm.effective_date}
                                    onChange={e => setAmendForm({ ...amendForm, effective_date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('blanket_po.reason')}</label>
                                <textarea className="form-input" rows={2} value={amendForm.reason}
                                    onChange={e => setAmendForm({ ...amendForm, reason: e.target.value })} />
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1" disabled={submitting}>
                                    {submitting ? t('common.saving') : t('blanket_po.confirm_amend')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowAmendModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default BlanketPODetail;
