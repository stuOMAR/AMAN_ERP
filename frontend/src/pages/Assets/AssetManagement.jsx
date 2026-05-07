import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { assetsAPI, branchesAPI } from '../../services';
import { useToast } from '../../context/ToastContext';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { Plus, ArrowRightLeft, CheckCircle, RefreshCw } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { Spinner } from '../../components/common/LoadingStates'

const AssetManagement = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const [activeTab, setActiveTab] = useState('transfers');
    const [transfers, setTransfers] = useState([]);
    const [revaluations, setRevaluations] = useState([]);
    const [assets, setAssets] = useState([]);
    const [branches, setBranches] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalType, setModalType] = useState('transfer');

    const [transferForm, setTransferForm] = useState({ asset_id: '', from_branch_id: '', to_branch_id: '', notes: '' });
    const [revalForm, setRevalForm] = useState({ asset_id: '', new_value: '', reason: '' });

    useEffect(() => {
        fetchData();
        fetchMetadata();
    }, [activeTab, currentBranch]);

    const fetchMetadata = async () => {
        try {
            const listParams = { limit: 1000 };
            if (currentBranch?.id) listParams.branch_id = currentBranch.id;
            const [assetsRes, branchesRes] = await Promise.all([
                assetsAPI.list(listParams),
                branchesAPI.list()
            ]);
            setAssets(assetsRes.data?.assets || assetsRes.data || []);
            setBranches(branchesRes.data || []);
        } catch (err) {
            console.error("Failed to fetch metadata", err);
        }
    };

    const fetchData = async () => {
        try {
            setLoading(true);
            if (activeTab === 'transfers') {
                const res = await assetsAPI.listTransfers();
                setTransfers(res.data || []);
            } else if (activeTab === 'revaluations') {
                const res = await assetsAPI.listRevaluations();
                setRevaluations(res.data || []);
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreateTransfer = async (e) => {
        e.preventDefault();
        try {
            await assetsAPI.createTransfer({
                asset_id: parseInt(transferForm.asset_id),
                from_branch_id: parseInt(transferForm.from_branch_id),
                to_branch_id: parseInt(transferForm.to_branch_id),
                notes: transferForm.notes
            });
            showToast(t('assets.transfer_created'), 'success');
            setShowModal(false);
            fetchData();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const handleApproveTransfer = async (id) => {
        try {
            await assetsAPI.approveTransfer(id);
            showToast(t('assets.approved_toast'), 'success');
            fetchData();
        } catch (err) {
            showToast(t('common.error'), 'error');
        }
    };

    const handleCreateRevaluation = async (e) => {
        e.preventDefault();
        try {
            await assetsAPI.createRevaluation({
                asset_id: parseInt(revalForm.asset_id),
                new_value: parseFloat(revalForm.new_value),
                reason: revalForm.reason
            });
            showToast(t('assets.revaluation_recorded'), 'success');
            setShowModal(false);
            fetchData();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const tabs = [
        { key: 'transfers', label: t('assets.tab_transfers'), icon: ArrowRightLeft },
        { key: 'revaluations', label: t('assets.tab_revaluations'), icon: RefreshCw },
    ];

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <span className="p-2 rounded bg-light text-primary">
                                <ArrowRightLeft size={24} />
                            </span>
                            {t('assets.management_title')}
                        </h1>
                        <p className="workspace-subtitle">{t('assets.management_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => {
                        setModalType(activeTab === 'transfers' ? 'transfer' : 'revaluation');
                        setShowModal(true);
                    }}>
                        <Plus size={18} /> {activeTab === 'transfers' ? t('assets.new_transfer') : t('assets.new_revaluation')}
                    </button>
                </div>
            </div>

            {/* Tabs */}
            <div className="d-flex gap-2 mb-4">
                {tabs.map(tab => {
                    const Icon = tab.icon;
                    return (
                        <button
                            key={tab.key}
                            onClick={() => setActiveTab(tab.key)}
                            className={`btn ${activeTab === tab.key ? 'btn-primary' : 'btn-secondary'}`}
                        >
                            <Icon size={16} /> {tab.label}
                        </button>
                    );
                })}
            </div>

            <div className="card section-card">
                {loading ? (
                     <div className="text-center p-5 text-muted">
                        <Spinner size="md"/>
                        {t('common.loading')}
                    </div>
                ) : activeTab === 'transfers' ? (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('assets.col_asset')}</th>
                                    <th>{t('assets.col_from')}</th>
                                    <th>{t('assets.col_to')}</th>
                                    <th>{t('assets.col_status')}</th>
                                    <th>{t('assets.col_date')}</th>
                                    <th>{t('assets.col_actions')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {transfers.map(tr => (
                                    <tr key={tr.id}>
                                        <td>{tr.asset_name || `#${tr.asset_id}`}</td>
                                        <td>{tr.from_branch_name || `#${tr.from_branch_id}`}</td>
                                        <td>{tr.to_branch_name || `#${tr.to_branch_id}`}</td>
                                        <td>
                                            <span className={`badge ${tr.status === 'approved' ? 'bg-success' : 'bg-warning text-dark'}`}>
                                                {tr.status === 'approved' ? t('assets.status_approved') : t('assets.status_pending')}
                                            </span>
                                        </td>
                                        <td className="small">{tr.created_at?.split('T')[0]}</td>
                                        <td>
                                            {tr.status === 'pending' && (
                                                <button className="btn btn-sm btn-success" onClick={() => handleApproveTransfer(tr.id)}>
                                                    <CheckCircle size={14} /> {t('assets.approve')}
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                                {transfers.length === 0 && (
                                    <tr>
                                        <td colSpan="6" className="text-center text-muted p-4">{t('assets.no_transfers')}</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('assets.col_asset')}</th>
                                    <th>{t('assets.col_old_value')}</th>
                                    <th>{t('assets.col_new_value')}</th>
                                    <th>{t('assets.col_difference')}</th>
                                    <th>{t('assets.col_reason')}</th>
                                    <th>{t('assets.col_date')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {revaluations.map(r => {
                                    const diff = (r.new_value || 0) - (r.old_value || 0);
                                    return (
                                        <tr key={r.id}>
                                            <td>{r.asset_name || `#${r.asset_id}`}</td>
                                            <td>{formatNumber(r.old_value)} {currency}</td>
                                            <td className="fw-bold">{formatNumber(r.new_value)} {currency}</td>
                                            <td className={diff >= 0 ? 'text-success' : 'text-danger'}>
                                                {diff >= 0 ? '+' : ''}{formatNumber(diff)} {currency}
                                            </td>
                                            <td>{r.reason || '—'}</td>
                                            <td className="small">{r.created_at?.split('T')[0]}</td>
                                        </tr>
                                    );
                                })}
                                {revaluations.length === 0 && (
                                    <tr>
                                        <td colSpan="6" className="text-center text-muted p-4">{t('assets.no_revaluations')}</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Transfer Modal */}
            {showModal && modalType === 'transfer' && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 450 }}>
                        <h3 className="modal-title">{t('assets.transfer_modal_title')}</h3>
                        <form onSubmit={handleCreateTransfer} className="mb-3">
                            <div className="form-group">
                                <label className="form-label">{t('assets.asset_id')}</label>
                                <select
                                    className="form-input"
                                    required
                                    value={transferForm.asset_id}
                                    onChange={e => setTransferForm({ ...transferForm, asset_id: e.target.value })}
                                >
                                    <option value="">-- {t('common.select')} --</option>
                                    {assets.map(a => (
                                        <option key={a.id} value={a.id}>{a.name} ({a.code})</option>
                                    ))}
                                </select>
                            </div>
                            <div className="row g-3">
                                <div className="form-group">
                                    <label className="form-label">{t('assets.col_from')}</label>
                                    <select
                                        className="form-input"
                                        required
                                        value={transferForm.from_branch_id}
                                        onChange={e => setTransferForm({ ...transferForm, from_branch_id: e.target.value })}
                                    >
                                        <option value="">-- {t('common.select')} --</option>
                                        {branches.map(b => (
                                            <option key={b.id} value={b.id}>{b.name}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('assets.col_to')}</label>
                                    <select
                                        className="form-input"
                                        required
                                        value={transferForm.to_branch_id}
                                        onChange={e => setTransferForm({ ...transferForm, to_branch_id: e.target.value })}
                                    >
                                        <option value="">-- {t('common.select')} --</option>
                                        {branches.map(b => (
                                            <option key={b.id} value={b.id}>{b.name}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('assets.notes')}</label>
                                <textarea
                                    className="form-input"
                                    rows="2"
                                    value={transferForm.notes}
                                    onChange={e => setTransferForm({ ...transferForm, notes: e.target.value })}
                                />
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-grow-1">{t('assets.create')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('assets.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Revaluation Modal */}
            {showModal && modalType === 'revaluation' && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 450 }}>
                        <h3 className="modal-title">{t('assets.revalue_modal_title')}</h3>
                        <form onSubmit={handleCreateRevaluation} className="mb-3">
                            <div className="form-group">
                                <label className="form-label">{t('assets.asset_id')}</label>
                                <select
                                    className="form-input"
                                    required
                                    value={revalForm.asset_id}
                                    onChange={e => setRevalForm({ ...revalForm, asset_id: e.target.value })}
                                >
                                    <option value="">-- {t('common.select')} --</option>
                                    {assets.map(a => (
                                        <option key={a.id} value={a.id}>{a.name} ({a.code})</option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('assets.col_new_value')}</label>
                                <input
                                    type="number"
                                    step="0.01"
                                    className="form-input"
                                    required
                                    value={revalForm.new_value}
                                    onChange={e => setRevalForm({ ...revalForm, new_value: e.target.value })}
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('assets.col_reason')}</label>
                                <textarea
                                    className="form-input"
                                    rows="2"
                                    required
                                    value={revalForm.reason}
                                    onChange={e => setRevalForm({ ...revalForm, reason: e.target.value })}
                                />
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-grow-1">{t('assets.revalue_btn')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('assets.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};


export default AssetManagement;
