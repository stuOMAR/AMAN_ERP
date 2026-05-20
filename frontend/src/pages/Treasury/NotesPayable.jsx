import { useState, useEffect } from 'react';
import { getCurrency, hasPermission } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import { notesAPI, treasuryAPI, inventoryAPI } from '../../utils/api';
import { Plus, Eye, CheckCircle, XCircle, AlertTriangle, Clock } from 'lucide-react';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';

import DateInput from '../../components/common/DateInput';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format';
const NotesPayable = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [notes, setNotes] = useState([]);
    const currency = getCurrency() || '';
    const canCreateTreasury = hasPermission('treasury.create');
    const permissionDenied = () => toastEmitter.emit(t('common.permission_denied', 'ليس لديك صلاحية تنفيذ هذا الإجراء'), 'error');
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [statusFilter, setStatusFilter] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [showDetail, setShowDetail] = useState(null);
    const [showPay, setShowPay] = useState(null);
    const [showProtest, setShowProtest] = useState(null);
    const [suppliers, setSuppliers] = useState([]);
    const [treasuryAccounts, setTreasuryAccounts] = useState([]);
    const [form, setForm] = useState({
        note_number: '', beneficiary_name: '', bank_name: '', amount: '',
        currency: getCurrency(), issue_date: new Date().toISOString().split('T')[0],
        due_date: '', maturity_date: '', party_id: '', treasury_account_id: '', notes: ''
    });
    const [payForm, setPayForm] = useState({ payment_date: new Date().toISOString().split('T')[0], treasury_account_id: '' });
    const [protestForm, setProtestForm] = useState({ protest_date: new Date().toISOString().split('T')[0], reason: '' });

    useEffect(() => {
        const timer = setTimeout(() => {
            loadData();
        }, 300)
        return () => clearTimeout(timer);
    }, [currentBranch, statusFilter]);

    const loadData = async () => {
        try {
            setLoading(true);
            const params = { branch_id: currentBranch?.id };
            if (statusFilter) params.status_filter = statusFilter;
            const [notesRes, statsRes] = await Promise.all([
                notesAPI.listPayable(params),
                notesAPI.payableStats({ branch_id: currentBranch?.id })
            ]);
            setNotes(notesRes.data);
            setStats(statsRes.data);
        } catch (e) { console.error(e); }
        finally { setLoading(false); setInitialLoad(false); }
    };

    const loadCreateData = async () => {
        try {
            const [suppRes, treasRes] = await Promise.all([
                inventoryAPI.listSuppliers({ limit: 500 }),
                treasuryAPI.listAccounts(currentBranch?.id)
            ]);
            setSuppliers(suppRes.data || []);
            setTreasuryAccounts((treasRes.data || []).filter(a => a.account_type === 'bank'));
        } catch (e) { console.error(e); }
    };

    const handleCreate = async () => {
        if (!canCreateTreasury) {
            permissionDenied(); return;
        }
        if (!form.note_number || !form.amount || !form.due_date) {
            toastEmitter.emit(t('treasury.notes.fill_required'), 'error'); return;
        }
        try {
            await notesAPI.createPayable({ ...form, amount: form.amount, branch_id: currentBranch?.id });
            toastEmitter.emit(t('treasury.notes_payable.created'), 'success');
            setShowCreate(false);
            setForm({ note_number: '', beneficiary_name: '', bank_name: '', amount: '', currency: getCurrency(),
                issue_date: new Date().toISOString().split('T')[0], due_date: '', maturity_date: '',
                party_id: '', treasury_account_id: '', notes: '' });
            loadData();
        } catch (e) { toastEmitter.emit(e.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handlePay = async () => {
        if (!canCreateTreasury) {
            permissionDenied(); return;
        }
        try {
            await notesAPI.payPayable(showPay.id, payForm);
            toastEmitter.emit(t('treasury.notes_payable.paid'), 'success');
            setShowPay(null);
            loadData();
        } catch (e) { toastEmitter.emit(e.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleProtest = async () => {
        if (!canCreateTreasury) {
            permissionDenied(); return;
        }
        try {
            await notesAPI.protestPayable(showProtest.id, protestForm);
            toastEmitter.emit(t('treasury.notes_payable.rejected'), 'success');
            setShowProtest(null);
            loadData();
        } catch (e) { toastEmitter.emit(e.response?.data?.detail || t('common.error'), 'error'); }
    };

    const fmt = (n) => formatNumber(n || '0');
    const isOverdue = (note) => note.status === 'issued' && new Date(note.due_date) < new Date();
    const statusBadge = (s) => {
        const map = { issued: 'badge-warning', paid: 'badge-success', protested: 'badge-danger' };
        const labels = { issued: t('notesPayable.issued'), paid: t('notesPayable.paid'), protested: t('notesPayable.protested') };
        return <span className={`badge ${map[s] || 'badge-secondary'}`}>{labels[s] || s}</span>;
    };

    if (initialLoad) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📜 {t('notesPayable.title')}</h1>
                    <p className="workspace-subtitle">{t('notesPayable.subtitle')}</p>
                </div>
                {canCreateTreasury && (
                    <button className="btn btn-primary" onClick={() => { setShowCreate(true); loadCreateData(); }}>
                        <Plus size={16} /> {t('notesPayable.create')}
                    </button>
                )}
            </div>

            {/* Stats */}
            {stats && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                    <div className="card p-3 text-center">
                        <Clock size={24} className="text-warning mb-2" />
                        <div className="small text-muted">{t('notesPayable.issued')}</div>
                        <div className="fw-bold fs-4">{stats.issued.count}</div>
                        <div className="small text-muted">{fmt(stats.issued.total)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <CheckCircle size={24} className="text-success mb-2" />
                        <div className="small text-muted">{t('notesPayable.paid')}</div>
                        <div className="fw-bold fs-4 text-success">{stats.paid.count}</div>
                        <div className="small text-muted">{fmt(stats.paid.total)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <XCircle size={24} className="text-danger mb-2" />
                        <div className="small text-muted">{t('notesPayable.protested')}</div>
                        <div className="fw-bold fs-4 text-danger">{stats.protested.count}</div>
                        <div className="small text-muted">{fmt(stats.protested.total)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <AlertTriangle size={24} className="text-danger mb-2" />
                        <div className="small text-muted">{t('notesPayable.overdue')}</div>
                        <div className="fw-bold fs-4 text-danger">{stats.overdue.count}</div>
                        <div className="small text-muted">{fmt(stats.overdue.total)} {currency}</div>
                    </div>
                </div>
            )}

            {/* Filters */}
            <div className="card p-3 mb-3">
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <select className="form-input" style={{ maxWidth: '200px' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                        <option value="">{t('notesPayable.allStatuses')}</option>
                        <option value="issued">{t('notesPayable.issued')}</option>
                        <option value="paid">{t('notesPayable.paid')}</option>
                        <option value="protested">{t('notesPayable.protested')}</option>
                    </select>
                    <span className="text-muted small">{notes.length} {t('notesPayable.noteCount')}</span>
                </div>
            </div>

            {/* Table */}
            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('notesPayable.noteNumber')}</th>
                            <th>{t('notesPayable.beneficiary')}</th>
                            <th>{t('notesPayable.supplier')}</th>
                            <th>{t('notesPayable.bank')}</th>
                            <th className="text-end">{t('notesPayable.amount')}</th>
                            <th>{t('notesPayable.dueDate')}</th>
                            <th>{t('notesPayable.status')}</th>
                            <th>{t('notesPayable.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {notes.length === 0 ? (
                            <tr><td colSpan="8" className="text-center py-4 text-muted">{t('notesPayable.noNotes')}</td></tr>
                        ) : notes.map(note => (
                            <tr key={note.id} style={isOverdue(note) ? { backgroundColor: 'rgba(255,0,0,0.05)' } : {}}>
                                <td className="fw-bold">{note.note_number}</td>
                                <td>{note.beneficiary_name || '-'}</td>
                                <td>{note.party_name || '-'}</td>
                                <td>{note.bank_name || '-'}</td>
                                <td className="text-end font-monospace fw-bold">{fmt(note.amount)}</td>
                                <td>
                                    {formatDate(note.due_date)}
                                    {isOverdue(note) && <span className="badge badge-danger ms-1" style={{ fontSize: '10px' }}>{t('notesPayable.overdue')}</span>}
                                </td>
                                <td>{statusBadge(note.status)}</td>
                                <td>
                                    <div style={{ display: 'flex', gap: '4px' }}>
                                        <button className="btn btn-sm btn-light" onClick={() => setShowDetail(note)} title={t('notesPayable.view')}>
                                            <Eye size={14} />
                                        </button>
                                        {note.status === 'issued' && canCreateTreasury && (
                                            <>
                                                <button className="btn btn-sm btn-success" onClick={() => { setShowPay(note); loadCreateData(); }} title={t('notesPayable.pay')}>
                                                    <CheckCircle size={14} />
                                                </button>
                                                <button className="btn btn-sm btn-danger" onClick={() => setShowProtest(note)} title={t('notesPayable.protest')}>
                                                    <XCircle size={14} />
                                                </button>
                                            </>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Create Modal */}
            {showCreate && canCreateTreasury && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
                        <div className="modal-header">
                            <h3>{t('notesPayable.create')}</h3>
                            <button className="btn-icon" onClick={() => setShowCreate(false)}>&times;</button>
                        </div>
                        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.noteNumber')} *</label>
                                    <input className="form-input" value={form.note_number} onChange={e => setForm({ ...form, note_number: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.amount')} *</label>
                                    <input type="number" step="0.01" className="form-input" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.beneficiaryName')}</label>
                                    <input className="form-input" value={form.beneficiary_name} onChange={e => setForm({ ...form, beneficiary_name: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.bank')}</label>
                                    <input className="form-input" value={form.bank_name} onChange={e => setForm({ ...form, bank_name: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.issueDate')}</label>
                                    <DateInput className="form-input" value={form.issue_date} onChange={e => setForm({ ...form, issue_date: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.dueDate')} *</label>
                                    <DateInput className="form-input" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.supplier')}</label>
                                    <select className="form-input" value={form.party_id} onChange={e => setForm({ ...form, party_id: e.target.value })}>
                                        <option value="">{t('notesPayable.select')}</option>
                                        {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesPayable.treasuryAccount')}</label>
                                    <select className="form-input" value={form.treasury_account_id} onChange={e => setForm({ ...form, treasury_account_id: e.target.value })}>
                                        <option value="">{t('notesPayable.select')}</option>
                                        {treasuryAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('notesPayable.notes')}</label>
                                <textarea className="form-input" rows="2" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowCreate(false)}>{t('notesPayable.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleCreate}>{t('notesPayable.createBtn')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {showDetail && (
                <div className="modal-overlay" onClick={() => setShowDetail(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>{t('notesPayable.noteDetail')}</h3>
                            <button className="btn-icon" onClick={() => setShowDetail(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                {[
                                    [t('notesPayable.noteNumber'), showDetail.note_number],
                                    [t('notesPayable.amount'), fmt(showDetail.amount) + ' ' + (showDetail.currency || '')],
                                    [t('notesPayable.beneficiary'), showDetail.beneficiary_name],
                                    [t('notesPayable.bank'), showDetail.bank_name],
                                    [t('notesPayable.supplier'), showDetail.party_name],
                                    [t('notesPayable.issueDate'), showDetail.issue_date],
                                    [t('notesPayable.dueDate'), showDetail.due_date],
                                    [t('notesPayable.status'), showDetail.status],
                                    [t('notesPayable.paymentDate'), showDetail.payment_date],
                                    [t('notesPayable.protestDate'), showDetail.protest_date],
                                    [t('notesPayable.protestReason'), showDetail.protest_reason],
                                ].map(([label, val], i) => val ? (
                                    <div key={i}><span className="small text-muted">{label}</span><div className="fw-bold">{val}</div></div>
                                ) : null)}
                            </div>
                            {showDetail.notes && <div className="mt-3"><span className="small text-muted">{t('notesPayable.notes')}</span><div>{showDetail.notes}</div></div>}
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowDetail(null)}>{t('notesPayable.close')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Pay Modal */}
            {showPay && canCreateTreasury && (
                <div className="modal-overlay" onClick={() => setShowPay(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '400px' }}>
                        <div className="modal-header">
                            <h3>{t('notesPayable.pay')}</h3>
                            <button className="btn-icon" onClick={() => setShowPay(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <p>{t('notesPayable.noteInfo', { number: showPay.note_number, amount: fmt(showPay.amount) })}</p>
                            <div className="form-group mb-3">
                                <label className="form-label">{t('notesPayable.paymentDate')}</label>
                                <DateInput className="form-input" value={payForm.payment_date}
                                    onChange={e => setPayForm({ ...payForm, payment_date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('notesPayable.bankAccount')}</label>
                                <select className="form-input" value={payForm.treasury_account_id}
                                    onChange={e => setPayForm({ ...payForm, treasury_account_id: e.target.value })}>
                                    <option value="">{t('notesPayable.select')}</option>
                                    {treasuryAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                </select>
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowPay(null)}>{t('notesPayable.cancel')}</button>
                            <button className="btn btn-success" onClick={handlePay}>{t('notesPayable.confirmPay')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Protest Modal */}
            {showProtest && canCreateTreasury && (
                <div className="modal-overlay" onClick={() => setShowProtest(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '400px' }}>
                        <div className="modal-header">
                            <h3>{t('notesPayable.protest')}</h3>
                            <button className="btn-icon" onClick={() => setShowProtest(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <p>{t('notesPayable.noteInfo', { number: showProtest.note_number, amount: fmt(showProtest.amount) })}</p>
                            <div className="form-group mb-3">
                                <label className="form-label">{t('notesPayable.protestDate')}</label>
                                <DateInput className="form-input" value={protestForm.protest_date}
                                    onChange={e => setProtestForm({ ...protestForm, protest_date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('notesPayable.protestReason')}</label>
                                <textarea className="form-input" rows="2" value={protestForm.reason}
                                    onChange={e => setProtestForm({ ...protestForm, reason: e.target.value })} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowProtest(null)}>{t('notesPayable.cancel')}</button>
                            <button className="btn btn-danger" onClick={handleProtest}>{t('notesPayable.confirmProtest')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default NotesPayable;
