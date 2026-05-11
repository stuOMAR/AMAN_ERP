import { useState, useEffect } from 'react';
import { getCurrency } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import { notesAPI, treasuryAPI, salesAPI } from '../../utils/api';
import { Plus, Eye, CheckCircle, XCircle, AlertTriangle, Clock } from 'lucide-react';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';

import DateInput from '../../components/common/DateInput';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
const NotesReceivable = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [notes, setNotes] = useState([]);
    const currency = getCurrency() || '';
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [statusFilter, setStatusFilter] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [showDetail, setShowDetail] = useState(null);
    const [showCollect, setShowCollect] = useState(null);
    const [showProtest, setShowProtest] = useState(null);
    const [customers, setCustomers] = useState([]);
    const [treasuryAccounts, setTreasuryAccounts] = useState([]);
    const [form, setForm] = useState({
        note_number: '', drawer_name: '', bank_name: '', amount: '',
        currency: getCurrency(), issue_date: new Date().toISOString().split('T')[0],
        due_date: '', maturity_date: '', party_id: '', party_site_id: '', treasury_account_id: '', notes: ''
    });
    const [collectForm, setCollectForm] = useState({ collection_date: new Date().toISOString().split('T')[0], treasury_account_id: '' });
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
                notesAPI.listReceivable(params),
                notesAPI.receivableStats({ branch_id: currentBranch?.id })
            ]);
            setNotes(notesRes.data);
            setStats(statsRes.data);
        } catch (e) { console.error(e); }
        finally { setLoading(false); setInitialLoad(false); }
    };

    const loadCreateData = async () => {
        try {
            const [custRes, treasRes] = await Promise.all([
                salesAPI.listCustomers(),
                treasuryAPI.listAccounts(currentBranch?.id)
            ]);
            setCustomers(custRes.data || []);
            setTreasuryAccounts((treasRes.data || []).filter(a => a.account_type === 'bank'));
        } catch (e) { console.error(e); }
    };

    const handleCreate = async () => {
        if (!form.note_number || !form.amount || !form.due_date) {
            toastEmitter.emit(t('treasury.notes.fill_required'), 'error'); return;
        }
        try {
            await notesAPI.createReceivable({ ...form, amount: parseFloat(form.amount), branch_id: currentBranch?.id });
            toastEmitter.emit(t('treasury.notes_receivable.created'), 'success');
            setShowCreate(false);
            setForm({ note_number: '', drawer_name: '', bank_name: '', amount: '', currency: getCurrency(),
                issue_date: new Date().toISOString().split('T')[0], due_date: '', maturity_date: '',
                party_id: '', treasury_account_id: '', notes: '' });
            loadData();
        } catch (e) { toastEmitter.emit(e.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleCollect = async () => {
        try {
            await notesAPI.collectReceivable(showCollect.id, collectForm);
            toastEmitter.emit(t('treasury.notes_receivable.collected'), 'success');
            setShowCollect(null);
            loadData();
        } catch (e) { toastEmitter.emit(e.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleProtest = async () => {
        try {
            await notesAPI.protestReceivable(showProtest.id, protestForm);
            toastEmitter.emit(t('treasury.notes_receivable.rejected'), 'success');
            setShowProtest(null);
            loadData();
        } catch (e) { toastEmitter.emit(e.response?.data?.detail || t('common.error'), 'error'); }
    };

    const fmt = (n) => Number(n || 0).toLocaleString('en', { minimumFractionDigits: 2 });
    const isOverdue = (note) => note.status === 'pending' && new Date(note.due_date) < new Date();
    const statusBadge = (s) => {
        const map = { pending: 'badge-warning', collected: 'badge-success', protested: 'badge-danger' };
        const labels = { pending: t('notesReceivable.pending'), collected: t('notesReceivable.collected'), protested: t('notesReceivable.protested') };
        return <span className={`badge ${map[s] || 'badge-secondary'}`}>{labels[s] || s}</span>;
    };

    if (initialLoad) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📜 {t('notesReceivable.title')}</h1>
                    <p className="workspace-subtitle">{t('notesReceivable.subtitle')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => { setShowCreate(true); loadCreateData(); }}>
                    <Plus size={16} /> {t('notesReceivable.create')}
                </button>
            </div>

            {/* Stats */}
            {stats && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                    <div className="card p-3 text-center">
                        <Clock size={24} className="text-warning mb-2" />
                        <div className="small text-muted">{t('notesReceivable.pending')}</div>
                        <div className="fw-bold fs-4">{stats.pending.count}</div>
                        <div className="small text-muted">{fmt(stats.pending.total)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <CheckCircle size={24} className="text-success mb-2" />
                        <div className="small text-muted">{t('notesReceivable.collected')}</div>
                        <div className="fw-bold fs-4 text-success">{stats.collected.count}</div>
                        <div className="small text-muted">{fmt(stats.collected.total)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <XCircle size={24} className="text-danger mb-2" />
                        <div className="small text-muted">{t('notesReceivable.protested')}</div>
                        <div className="fw-bold fs-4 text-danger">{stats.protested.count}</div>
                        <div className="small text-muted">{fmt(stats.protested.total)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <AlertTriangle size={24} className="text-danger mb-2" />
                        <div className="small text-muted">{t('notesReceivable.overdue')}</div>
                        <div className="fw-bold fs-4 text-danger">{stats.overdue.count}</div>
                        <div className="small text-muted">{fmt(stats.overdue.total)} {currency}</div>
                    </div>
                </div>
            )}

            {/* Filters */}
            <div className="card p-3 mb-3">
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <select className="form-input" style={{ maxWidth: '200px' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                        <option value="">{t('notesReceivable.allStatuses')}</option>
                        <option value="pending">{t('notesReceivable.pending')}</option>
                        <option value="collected">{t('notesReceivable.collected')}</option>
                        <option value="protested">{t('notesReceivable.protested')}</option>
                    </select>
                    <span className="text-muted small">{notes.length} {t('notesReceivable.noteCount')}</span>
                </div>
            </div>

            {/* Table */}
            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('notesReceivable.noteNumber')}</th>
                            <th>{t('notesReceivable.drawerName')}</th>
                            <th>{t('notesReceivable.customer')}</th>
                            <th>{t('notesReceivable.bank')}</th>
                            <th className="text-end">{t('notesReceivable.amount')}</th>
                            <th>{t('notesReceivable.dueDate')}</th>
                            <th>{t('notesReceivable.status')}</th>
                            <th>{t('notesReceivable.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {notes.length === 0 ? (
                            <tr><td colSpan="8" className="text-center py-4 text-muted">{t('notesReceivable.noNotes')}</td></tr>
                        ) : notes.map(note => (
                            <tr key={note.id} style={isOverdue(note) ? { backgroundColor: 'rgba(255,0,0,0.05)' } : {}}>
                                <td className="fw-bold">{note.note_number}</td>
                                <td>{note.drawer_name || '-'}</td>
                                <td>{note.party_name || '-'}</td>
                                <td>{note.bank_name || '-'}</td>
                                <td className="text-end font-monospace fw-bold">{fmt(note.amount)}</td>
                                <td>
                                    {formatDate(note.due_date)}
                                    {isOverdue(note) && <span className="badge badge-danger ms-1" style={{ fontSize: '10px' }}>{t('notesReceivable.overdue')}</span>}
                                </td>
                                <td>{statusBadge(note.status)}</td>
                                <td>
                                    <div style={{ display: 'flex', gap: '4px' }}>
                                        <button className="btn btn-sm btn-light" onClick={() => setShowDetail(note)} title={t('notesReceivable.view')}>
                                            <Eye size={14} />
                                        </button>
                                        {note.status === 'pending' && (
                                            <>
                                                <button className="btn btn-sm btn-success" onClick={() => { setShowCollect(note); loadCreateData(); }} title={t('notesReceivable.collect')}>
                                                    <CheckCircle size={14} />
                                                </button>
                                                <button className="btn btn-sm btn-danger" onClick={() => setShowProtest(note)} title={t('notesReceivable.protest')}>
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
            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
                        <div className="modal-header">
                            <h3>{t('notesReceivable.create')}</h3>
                            <button className="btn-icon" onClick={() => setShowCreate(false)}>&times;</button>
                        </div>
                        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.noteNumber')} *</label>
                                    <input className="form-input" value={form.note_number} onChange={e => setForm({ ...form, note_number: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.amount')} *</label>
                                    <input type="number" step="0.01" className="form-input" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.drawerName')}</label>
                                    <input className="form-input" value={form.drawer_name} onChange={e => setForm({ ...form, drawer_name: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.bank')}</label>
                                    <input className="form-input" value={form.bank_name} onChange={e => setForm({ ...form, bank_name: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.issueDate')}</label>
                                    <DateInput className="form-input" value={form.issue_date} onChange={e => setForm({ ...form, issue_date: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.dueDate')} *</label>
                                    <DateInput className="form-input" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.customer')}</label>
                                    <select className="form-input" value={form.party_id} onChange={e => setForm({ ...form, party_id: e.target.value })}>
                                        <option value="">{t('notesReceivable.select')}</option>
                                        {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('notesReceivable.treasuryAccount')}</label>
                                    <select className="form-input" value={form.treasury_account_id} onChange={e => setForm({ ...form, treasury_account_id: e.target.value })}>
                                        <option value="">{t('notesReceivable.select')}</option>
                                        {treasuryAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('notesReceivable.notes')}</label>
                                <textarea className="form-input" rows="2" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowCreate(false)}>{t('notesReceivable.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleCreate}>{t('notesReceivable.createBtn')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {showDetail && (
                <div className="modal-overlay" onClick={() => setShowDetail(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>{t('notesReceivable.noteDetail')}</h3>
                            <button className="btn-icon" onClick={() => setShowDetail(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                {[
                                    [t('notesReceivable.noteNumber'), showDetail.note_number],
                                    [t('notesReceivable.amount'), fmt(showDetail.amount) + ' ' + (showDetail.currency || '')],
                                    [t('notesReceivable.drawerName'), showDetail.drawer_name],
                                    [t('notesReceivable.bank'), showDetail.bank_name],
                                    [t('notesReceivable.customer'), showDetail.party_name],
                                    [t('notesReceivable.issueDate'), showDetail.issue_date],
                                    [t('notesReceivable.dueDate'), showDetail.due_date],
                                    [t('notesReceivable.status'), showDetail.status],
                                    [t('notesReceivable.collectionDate'), showDetail.collection_date],
                                    [t('notesReceivable.protestDate'), showDetail.protest_date],
                                    [t('notesReceivable.protestReason'), showDetail.protest_reason],
                                ].map(([label, val], i) => val ? (
                                    <div key={i}><span className="small text-muted">{label}</span><div className="fw-bold">{val}</div></div>
                                ) : null)}
                            </div>
                            {showDetail.notes && <div className="mt-3"><span className="small text-muted">{t('notesReceivable.notes')}</span><div>{showDetail.notes}</div></div>}
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowDetail(null)}>{t('notesReceivable.close')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Collect Modal */}
            {showCollect && (
                <div className="modal-overlay" onClick={() => setShowCollect(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '400px' }}>
                        <div className="modal-header">
                            <h3>{t('notesReceivable.collect')}</h3>
                            <button className="btn-icon" onClick={() => setShowCollect(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <p>{t('notesReceivable.noteInfo', { number: showCollect.note_number, amount: fmt(showCollect.amount) })}</p>
                            <div className="form-group mb-3">
                                <label className="form-label">{t('notesReceivable.collectionDate')}</label>
                                <DateInput className="form-input" value={collectForm.collection_date}
                                    onChange={e => setCollectForm({ ...collectForm, collection_date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('notesReceivable.bankAccount')}</label>
                                <select className="form-input" value={collectForm.treasury_account_id}
                                    onChange={e => setCollectForm({ ...collectForm, treasury_account_id: e.target.value })}>
                                    <option value="">{t('notesReceivable.select')}</option>
                                    {treasuryAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                </select>
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowCollect(null)}>{t('notesReceivable.cancel')}</button>
                            <button className="btn btn-success" onClick={handleCollect}>{t('notesReceivable.confirmCollect')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Protest Modal */}
            {showProtest && (
                <div className="modal-overlay" onClick={() => setShowProtest(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '400px' }}>
                        <div className="modal-header">
                            <h3>{t('notesReceivable.protest')}</h3>
                            <button className="btn-icon" onClick={() => setShowProtest(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <p>{t('notesReceivable.noteInfo', { number: showProtest.note_number, amount: fmt(showProtest.amount) })}</p>
                            <div className="form-group mb-3">
                                <label className="form-label">{t('notesReceivable.protestDate')}</label>
                                <DateInput className="form-input" value={protestForm.protest_date}
                                    onChange={e => setProtestForm({ ...protestForm, protest_date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('notesReceivable.protestReason')}</label>
                                <textarea className="form-input" rows="2" value={protestForm.reason}
                                    onChange={e => setProtestForm({ ...protestForm, reason: e.target.value })} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-light" onClick={() => setShowProtest(null)}>{t('notesReceivable.cancel')}</button>
                            <button className="btn btn-danger" onClick={handleProtest}>{t('notesReceivable.confirmProtest')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default NotesReceivable;
