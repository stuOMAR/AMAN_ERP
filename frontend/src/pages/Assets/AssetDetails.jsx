import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { assetsAPI, branchesAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';
import { Trash2, Calendar, DollarSign, RefreshCw, ArrowRightLeft } from 'lucide-react';
import { getCurrency } from '../../utils/auth';
import { formatShortDate } from '../../utils/dateUtils';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import { PageLoading, Spinner } from '../../components/common/LoadingStates'

const AssetDetails = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { id } = useParams();
    const currency = getCurrency();
    const { currentBranch } = useBranch();

    const [asset, setAsset] = useState(null);
    const [schedule, setSchedule] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);

    // Revalue Modal State
    const [showRevalueModal, setShowRevalueModal] = useState(false);
    const [revalueData, setRevalueData] = useState({ new_value: '', reason: '' });
    const [revaluing, setRevaluing] = useState(false);

    // Transfer Modal State
    const [showTransferModal, setShowTransferModal] = useState(false);
    const [transferData, setTransferData] = useState({ to_branch_id: '', notes: '' });
    const [transferring, setTransferring] = useState(false);
    const [branches, setBranches] = useState([]);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [id, currentBranch]);

    const fetchData = async () => {
        try {
            setLoading(true);
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const response = await assetsAPI.get(id, params);
            setAsset(response.data.asset);
            setSchedule(response.data.schedule);
        } catch (error) {
            console.error("Failed to fetch asset details", error);
            navigate('/assets');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handlePostDepreciation = async (scheduleId) => {
        if (!window.confirm(t('assets.confirm_post', 'Are you sure you want to post depreciation for this period?'))) return;

        try {
            await assetsAPI.postDepreciation(id, scheduleId);
            toastEmitter.emit(t('assets.depr_posted', 'Depreciation posted successfully'), 'success');
            fetchData();
        } catch (error) {
            console.error("Failed to post depreciation", error);
            toastEmitter.emit(error.response?.data?.detail || t('common.error_occurred'), 'error');
        }
    };

    const handleDispose = async () => {
        if (!window.confirm(t('assets.confirm_dispose'))) return;
        try {
            await assetsAPI.dispose(id, { disposal_date: new Date().toISOString().split('T')[0] });
            toastEmitter.emit(t('assets.disposed_msg'), 'success');
            fetchData();
        } catch (error) {
            console.error("Failed to dispose asset", error);
            toastEmitter.emit(t('common.error_occurred'), 'error');
        }
    };

    // --- Revalue ---
    const handleRevalue = async () => {
        if (!revalueData.new_value) return;
        setRevaluing(true);
        try {
            await assetsAPI.revalueAsset(id, {
                new_value: revalueData.new_value,
                reason: revalueData.reason
            });
            toastEmitter.emit(t('assets.asset_revalued_successfully'), 'success');
            setShowRevalueModal(false);
            setRevalueData({ new_value: '', reason: '' });
            fetchData();
        } catch (error) {
            console.error("Failed to revalue asset", error);
            toastEmitter.emit(error.response?.data?.detail || t('common.error_occurred'), 'error');
        } finally {
            setRevaluing(false);
        }
    };

    // --- Transfer ---
    const openTransferModal = async () => {
        try {
            const res = await branchesAPI.list();
            setBranches(res.data || []);
        } catch (err) { console.error(err); toastEmitter.emit(t('common.error_occurred'), 'error'); }
        setShowTransferModal(true);
    };

    const handleTransfer = async () => {
        if (!transferData.to_branch_id) return;
        setTransferring(true);
        try {
            await assetsAPI.transferAsset(id, {
                to_branch_id: parseInt(transferData.to_branch_id),
                notes: transferData.notes
            });
            toastEmitter.emit(t('assets.asset_transferred_successfully'), 'success');
            setShowTransferModal(false);
            setTransferData({ to_branch_id: '', notes: '' });
            fetchData();
        } catch (error) {
            console.error("Failed to transfer asset", error);
            toastEmitter.emit(error.response?.data?.detail || t('common.error_occurred'), 'error');
        } finally {
            setTransferring(false);
        }
    };

    if (initialLoad && loading) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div className="d-flex align-items-center gap-3">
                        <BackButton />
                        <div>
                            <h1 className="workspace-title text-primary">{asset.name}</h1>
                            <p className="workspace-subtitle text-muted fw-medium">
                                <span className="badge bg-light text-dark border me-2">{asset.code}</span>
                                <span className="text-secondary">{t(`assets.types.${asset.type}`, asset.type)}</span>
                            </p>
                        </div>
                    </div>
                    <div className="header-actions d-flex align-items-center gap-2">
                        {asset.status === 'active' && (
                            <>
                                <button className="btn btn-sm btn-outline-primary" onClick={() => setShowRevalueModal(true)}>
                                    <RefreshCw size={16} className="me-1" />
                                    {t('assets.revalue')}
                                </button>
                                <button className="btn btn-sm btn-outline-secondary" onClick={openTransferModal}>
                                    <ArrowRightLeft size={16} className="me-1" />
                                    {t('assets.transfer')}
                                </button>
                                <button className="btn btn-sm btn-outline-danger" onClick={handleDispose}>
                                    <Trash2 size={16} className="me-1" />
                                    {t('assets.dispose')}
                                </button>
                            </>
                        )}
                        <span className={`badge ${asset.status === 'active' ? 'bg-success-subtle text-success' : 'bg-secondary-subtle text-secondary'} border px-3 py-2 fs-6`}>
                            {t(`status.${asset.status}`, asset.status)}
                        </span>
                    </div>
                </div>
            </div>

            <div className="row g-4">
                {/* Asset Info Card */}
                <div className="col-md-4">
                    <div className="card section-card h-100">
                        <h3 className="section-title mb-4">{t('assets.details', 'Asset Details')}</h3>

                        <div className="detail-row mb-3">
                            <label className="text-muted d-block small mb-1">{t('assets.purchase_date', 'Purchase Date')}</label>
                            <div className="fw-medium d-flex align-items-center">
                                <Calendar size={16} className="me-2 text-primary" />
                                {formatShortDate(asset.purchase_date)}
                            </div>
                        </div>

                        <div className="detail-row mb-3">
                            <label className="text-muted d-block small mb-1">{t('assets.cost', 'Initial Cost')}</label>
                            <div className="fw-bold fs-5 text-dark d-flex align-items-center">
                                <DollarSign size={18} className="me-2 text-success" />
                                {formatNumber(asset.cost)} <span className="text-muted fs-6 ms-1">{asset.currency || currency}</span>
                            </div>
                        </div>

                        <div className="detail-row mb-3">
                            <label className="text-muted d-block small mb-1">{t('assets.residual_value', 'Residual Value')}</label>
                            <div className="fw-medium">
                                {formatNumber(asset.residual_value)} {asset.currency || currency}
                            </div>
                        </div>

                        <div className="detail-row mb-3">
                            <label className="text-muted d-block small mb-1">{t('assets.life_years', 'Useful Life')}</label>
                            <div className="fw-medium">
                                {asset.life_years} {t('common.years', 'Years')}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Depreciation Schedule */}
                <div className="col-md-8">
                    <div className="card section-card h-100">
                        <h3 className="section-title mb-4">{t('assets.depr_schedule', 'Depreciation Schedule')}</h3>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('common.year', 'Year')}</th>
                                        <th className="text-end">{t('assets.amount', 'Expense Amount')}</th>
                                        <th className="text-end">{t('assets.accumulated', 'Accumulated')}</th>
                                        <th className="text-end">{t('assets.book_value', 'Book Value')}</th>
                                        <th className="text-center">{t('common.status.title', 'Status')}</th>
                                        <th className="text-center">{t('common.actions', 'Actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {schedule.map((item, index) => (
                                        <tr key={item.id}>
                                            <td className="fw-medium">{item.fiscal_year}</td>
                                            <td className="text-end">{formatNumber(item.amount)} <small>{asset.currency || currency}</small></td>
                                            <td className="text-end text-muted">{formatNumber(item.accumulated_amount)} <small>{asset.currency || currency}</small></td>
                                            <td className="text-end fw-bold text-primary">{formatNumber(item.book_value)} <small>{asset.currency || currency}</small></td>
                                            <td className="text-center">
                                                {item.posted ? (
                                                    <span className="badge bg-success-subtle text-success">{t('status.posted', 'Posted')}</span>
                                                ) : (
                                                    <span className="badge bg-warning-subtle text-warning">{t('status.pending', 'Pending')}</span>
                                                )}
                                            </td>
                                            <td className="text-center">
                                                {!item.posted && (
                                                    <button
                                                        className="btn btn-sm btn-outline-primary"
                                                        onClick={() => handlePostDepreciation(item.id)}
                                                    >
                                                        {t('assets.post_entry', 'Post Entry')}
                                                    </button>
                                                )}
                                                {item.posted && item.journal_entry_id && (
                                                    <small className="text-muted">JE #{item.journal_entry_id}</small>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                    {schedule.length === 0 && (
                                        <tr><td colSpan="6" className="text-center py-4 text-muted">{t('common.no_data')}</td></tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            {/* ========== Revalue Modal ========== */}
            {showRevalueModal && (
                <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 1050, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowRevalueModal(false)}>
                    <div className="card" style={{ minWidth: 420, maxWidth: 500 }} onClick={e => e.stopPropagation()}>
                        <h3 className="section-title mb-4" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <RefreshCw size={20} className="text-primary" />
                            {t('assets.revalue_asset')}
                        </h3>
                        <div className="mb-3">
                            <label className="form-label">{t('assets.new_fair_value')}</label>
                            <input type="number" className="form-input" value={revalueData.new_value}
                                onChange={e => setRevalueData(p => ({ ...p, new_value: e.target.value }))}
                                placeholder={t('assets.enter_new_value')} />
                        </div>
                        <div className="mb-4">
                            <label className="form-label">{t('assets.reason')}</label>
                            <textarea className="form-input" rows={3} value={revalueData.reason}
                                onChange={e => setRevalueData(p => ({ ...p, reason: e.target.value }))}
                                placeholder={t('assets.reason_for_revaluation')} />
                        </div>
                        <div className="d-flex gap-2 justify-content-end">
                            <button className="btn btn-ghost" onClick={() => setShowRevalueModal(false)}>{t('common.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleRevalue} disabled={revaluing || !revalueData.new_value}>
                                {revaluing ? <Spinner size="sm"/> : (t('assets.confirm_revalue'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ========== Transfer Modal ========== */}
            {showTransferModal && (
                <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 1050, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowTransferModal(false)}>
                    <div className="card" style={{ minWidth: 420, maxWidth: 500 }} onClick={e => e.stopPropagation()}>
                        <h3 className="section-title mb-4" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <ArrowRightLeft size={20} className="text-secondary" />
                            {t('assets.transfer_asset_to_branch')}
                        </h3>
                        <div className="mb-3">
                            <label className="form-label">{t('assets.target_branch')}</label>
                            <select className="form-input" value={transferData.to_branch_id}
                                onChange={e => setTransferData(p => ({ ...p, to_branch_id: e.target.value }))}>
                                <option value="">{t('assets.select_branch')}</option>
                                {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                            </select>
                        </div>
                        <div className="mb-4">
                            <label className="form-label">{t('assets.notes')}</label>
                            <textarea className="form-input" rows={2} value={transferData.notes}
                                onChange={e => setTransferData(p => ({ ...p, notes: e.target.value }))}
                                placeholder={t('assets.additional_notes_optional')} />
                        </div>
                        <div className="d-flex gap-2 justify-content-end">
                            <button className="btn btn-ghost" onClick={() => setShowTransferModal(false)}>{t('common.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleTransfer} disabled={transferring || !transferData.to_branch_id}>
                                {transferring ? <Spinner size="sm"/> : (t('assets.confirm_transfer'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default AssetDetails;
