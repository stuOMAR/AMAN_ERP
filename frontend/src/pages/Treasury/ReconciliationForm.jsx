import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { treasuryAPI, reconciliationAPI } from '../../utils/api';
import { Check, X, AlertCircle, Lock, Landmark, ArrowLeft, Plus, Trash2, Link2, Unlink, CheckCircle, Upload, Zap, FileSpreadsheet } from 'lucide-react';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';
import CustomDatePicker from '../../components/common/CustomDatePicker';

import DateInput from '../../components/common/DateInput';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import { PageLoading } from '../../components/common/LoadingStates'
const ReconciliationForm = () => {
    const { t } = useTranslation();

    const { id } = useParams();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();

    const [reconciliation, setReconciliation] = useState(null);
    const [summary, setSummary] = useState(null);
    const [statementLines, setStatementLines] = useState([]);
    const [ledgerLines, setLedgerLines] = useState([]);
    const [selectedStatementLine, setSelectedStatementLine] = useState(null);
    const [selectedLedgerLine, setSelectedLedgerLine] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [stmtTab, setStmtTab] = useState('unmatched'); // 'unmatched' | 'matched'
    const [showAddLine, setShowAddLine] = useState(false);
    const [showImport, setShowImport] = useState(false);
    const [importPreview, setImportPreview] = useState(null);
    const [importLoading, setImportLoading] = useState(false);
    const [autoMatchLoading, setAutoMatchLoading] = useState(false);
    const [newLine, setNewLine] = useState({
        transaction_date: new Date().toISOString().split('T')[0],
        description: '', reference: '', debit: '', credit: ''
    });

    const [accounts, setAccounts] = useState([]);
    const [formData, setFormData] = useState({
        treasury_account_id: '',
        statement_date: new Date().toISOString().split('T')[0],
        start_balance: 0, end_balance: 0,
        notes: '', branch_id: currentBranch?.id || null
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            if (id === 'new') { fetchAccounts(); }
            else { fetchData(); }
        }, 300)
        return () => clearTimeout(timer);
    }, [id, currentBranch]);

    const fetchAccounts = async () => {
        try {
            setLoading(true);
            const res = await treasuryAPI.listAccounts(currentBranch?.id);
            const banks = res.data.filter(a => a.account_type === 'bank');
            setAccounts(banks);
            if (banks.length > 0) setFormData(prev => ({ ...prev, treasury_account_id: banks[0].id }));
        } catch (error) { console.error(error); }
        finally { setLoading(false); setInitialLoad(false); }
    };

    const fetchData = async () => {
        if (id === 'new') return;
        try {
            setLoading(true);
            const resRec = await reconciliationAPI.get(id);
            setReconciliation(resRec.data.header);
            setStatementLines(resRec.data.lines || []);
            setSummary(resRec.data.summary || null);
            const resLedger = await reconciliationAPI.getLedger(id);
            setLedgerLines(resLedger.data);
        } catch (error) { console.error(error); }
        finally { setLoading(false); setInitialLoad(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        try {
            const res = await reconciliationAPI.create({
                ...formData, branch_id: currentBranch?.id || null
            });
            toastEmitter.emit(t('common.success'), 'success');
            navigate(`/treasury/reconciliation/${res.data.id}`);
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const handleAddLine = async () => {
        if (!newLine.description || (!newLine.debit && !newLine.credit)) {
            toastEmitter.emit(t('treasury.reconciliation.fill_required'), 'error');
            return;
        }
        try {
            await reconciliationAPI.addLines(id, [{
                transaction_date: newLine.transaction_date,
                description: newLine.description,
                reference: newLine.reference || null,
                debit: parseFloat(newLine.debit) || 0,
                credit: parseFloat(newLine.credit) || 0
            }]);
            toastEmitter.emit(t('common.success'), 'success');
            setNewLine({ transaction_date: new Date().toISOString().split('T')[0], description: '', reference: '', debit: '', credit: '' });
            setShowAddLine(false);
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const handleDeleteLine = async (e, lineId) => {
        e.stopPropagation();
        try {
            await reconciliationAPI.deleteLine(id, lineId);
            toastEmitter.emit(t('common.deleted_successfully'), 'success');
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const handleFileSelect = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        try {
            setImportLoading(true);
            const res = await reconciliationAPI.importPreview(id, file);
            setImportPreview(res.data);
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('treasury.reconciliation.parse_error'), 'error');
        } finally {
            setImportLoading(false);
            e.target.value = '';
        }
    };

    const handleImportConfirm = async () => {
        if (!importPreview?.all_lines?.length) return;
        try {
            setImportLoading(true);
            await reconciliationAPI.importConfirm(id, importPreview.all_lines);
            toastEmitter.emit(t('treasury.reconciliation.imported_success') + ' ' + importPreview.all_lines.length, 'success');
            setImportPreview(null);
            setShowImport(false);
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setImportLoading(false);
        }
    };

    const handleAutoMatch = async () => {
        try {
            setAutoMatchLoading(true);
            const res = await reconciliationAPI.autoMatch(id);
            toastEmitter.emit(res.data.message, res.data.matched_count > 0 ? 'success' : 'info');
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setAutoMatchLoading(false);
        }
    };

    const handleMatch = async () => {
        if (!selectedStatementLine || !selectedLedgerLine) return;
        try {
            await reconciliationAPI.match(id, {
                statement_line_id: selectedStatementLine.id,
                journal_line_id: selectedLedgerLine.id
            });
            toastEmitter.emit(t('treasury.reconciliation.matched_success'), 'success');
            setSelectedStatementLine(null);
            setSelectedLedgerLine(null);
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('treasury.reconciliation.match_error'), 'error');
        }
    };

    const handleUnmatch = async (e, lineId) => {
        e.stopPropagation();
        try {
            await reconciliationAPI.unmatch(id, { statement_line_id: lineId });
            toastEmitter.emit(t('treasury.reconciliation.unmatched_success'), 'success');
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const handleFinalize = async () => {
        const toleranceMsg = summary?.tolerance != null
            ? `\n${t('treasury.reconciliation.tolerance', 'هامش التسامح')}: ${summary.tolerance}`
            : '';
        if (!window.confirm(t('common.confirm_action') + toleranceMsg)) return;
        try {
            await reconciliationAPI.finalize(id);
            toastEmitter.emit(t('treasury.reconciliation.finalized_success'), 'success');
            navigate('/treasury/reconciliation');
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const fmt = (n) => Number(n || 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    if (initialLoad) return (
        <PageLoading />
    );

    // === CREATE FORM ===
    if (id === 'new') {
        return (
            <div className="workspace fade-in">
                <div className="workspace-header">
                    <div className="d-flex align-items-center gap-3">
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('treasury.reconciliation.new')}</h1>
                            <p className="workspace-subtitle">{t('treasury.reconciliation.new_subtitle')}</p>
                        </div>
                    </div>
                </div>
                <div className="card p-4 mx-auto" style={{ maxWidth: '600px' }}>
                    <form onSubmit={handleCreate}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <FormField label={t('treasury.reconciliation.select_account')} required>
                                <select className="form-input" required
                                    value={formData.treasury_account_id}
                                    onChange={e => setFormData({ ...formData, treasury_account_id: e.target.value })}>
                                    <option value="">{t('common.select')}</option>
                                    {accounts.map(acc => (
                                        <option key={acc.id} value={acc.id}>{acc.name} ({acc.currency})</option>
                                    ))}
                                </select>
                            </FormField>
                            <div className="form-group">
                                <CustomDatePicker
                                    label={t('treasury.reconciliation.statement_date')}
                                    selected={formData.statement_date}
                                    onChange={d => setFormData({ ...formData, statement_date: d })}
                                    required />
                            </div>
                            <div style={{ display: 'flex', gap: '16px' }}>
                                <FormField label={t('treasury.reconciliation.start_bal')} required style={{ flex: 1 }}>
                                    <input type="number" step="0.01" className="form-input" required
                                        value={formData.start_balance}
                                        onChange={e => setFormData({ ...formData, start_balance: e.target.value })}
                                        placeholder="0.00" />
                                </FormField>
                                <FormField label={t('treasury.reconciliation.end_bal')} required style={{ flex: 1 }}>
                                    <input type="number" step="0.01" className="form-input" required
                                        value={formData.end_balance}
                                        onChange={e => setFormData({ ...formData, end_balance: e.target.value })}
                                        placeholder="0.00" />
                                </FormField>
                            </div>
                            <FormField label={t('common.notes')}>
                                <textarea className="form-input" rows="2"
                                    value={formData.notes}
                                    onChange={e => setFormData({ ...formData, notes: e.target.value })}
                                    placeholder={t('treasury.reconciliation.notes_placeholder')} />
                            </FormField>
                            <button type="submit" className="btn btn-primary w-100 py-3 mt-2">
                                {t('treasury.reconciliation.create')}
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        );
    }

    // === NOT FOUND ===
    if (!reconciliation) return (
        <div className="page-center text-center text-muted">
            <AlertCircle size={64} className="mb-3 opacity-25" />
            <h4 className="fw-bold">{t('treasury.reconciliation.not_found')}</h4>
            <button className="btn btn-link" onClick={() => navigate('/treasury/reconciliation')}>
                {t('common.back')}
            </button>
        </div>
    );

    const isPosted = reconciliation.status === 'posted';
    const unmatchedStatementLines = statementLines.filter(l => !l.is_reconciled);
    const matchedStatementLines = statementLines.filter(l => l.is_reconciled);

    return (
        <div className="workspace fade-in" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px)', padding: 0 }}>
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {/* === HEADER === */}
            <div style={{ 
                padding: '16px 24px', borderBottom: '1px solid var(--border-color)',
                background: 'var(--bg-card)', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                flexShrink: 0
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <button className="btn-icon" onClick={() => navigate('/treasury/reconciliation')}>
                        <ArrowLeft size={20} />
                    </button>
                    <div style={{ padding: '10px', borderRadius: '10px', backgroundColor: 'var(--bg-hover)', color: 'var(--primary)' }}>
                        <Landmark size={22} />
                    </div>
                    <div>
                        <h4 style={{ margin: 0, fontWeight: 700 }}>{reconciliation.account_name}</h4>
                        <div className="small text-muted">{reconciliation.statement_date} · {reconciliation.currency}</div>
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
                    <div className="text-center">
                        <div className="small text-muted">{t('treasury.reconciliation.start_bal')}</div>
                        <div className="fw-bold font-monospace" style={{ fontSize: '16px' }}>{fmt(reconciliation.start_balance)}</div>
                    </div>
                    <div style={{ width: '1px', height: '36px', background: 'var(--border-color)' }} />
                    <div className="text-center">
                        <div className="small text-muted">{t('treasury.reconciliation.end_bal')}</div>
                        <div className="fw-bold font-monospace" style={{ fontSize: '16px' }}>{fmt(reconciliation.end_balance)}</div>
                    </div>
                    <div style={{ width: '1px', height: '36px', background: 'var(--border-color)' }} />
                    <div className="text-center">
                        <div className="small text-muted">{t('treasury.reconciliation.book_balance')}</div>
                        <div className="fw-bold font-monospace" style={{ fontSize: '16px' }}>{fmt(reconciliation.book_balance)}</div>
                    </div>
                    <div style={{ width: '1px', height: '36px', background: 'var(--border-color)' }} />
                    {isPosted ? (
                        <span className="badge badge-success" style={{ padding: '8px 20px', borderRadius: '20px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <CheckCircle size={14} /> {t('treasury.reconciliation.status_posted')}
                        </span>
                    ) : (
                        <button className="btn btn-warning" style={{ borderRadius: '20px', fontWeight: 600 }} onClick={handleFinalize}>
                            <Lock size={14} style={{ marginInlineEnd: '6px' }} />
                            {t('treasury.reconciliation.finalize')}
                        </button>
                    )}
                </div>
            </div>

            {/* === SUMMARY BAR === */}
            {summary && (
                <div style={{
                    padding: '12px 24px', borderBottom: '1px solid var(--border-color)',
                    background: 'var(--bg-hover)', display: 'flex', justifyContent: 'center',
                    gap: '32px', flexShrink: 0, flexWrap: 'wrap'
                }}>
                    <div className="text-center">
                        <span className="small text-muted">{t('treasury.reconciliation.total_lines')}</span>
                        <div className="fw-bold">{summary.total_lines}</div>
                    </div>
                    <div className="text-center">
                        <span className="small text-muted">{t('treasury.reconciliation.matched_lines')}</span>
                        <div className="fw-bold text-success">{summary.matched_count}</div>
                    </div>
                    <div className="text-center">
                        <span className="small text-muted">{t('treasury.reconciliation.unmatched_lines')}</span>
                        <div className="fw-bold text-warning">{summary.unmatched_count}</div>
                    </div>
                    <div style={{ width: '1px', height: '36px', background: 'var(--border-color)', alignSelf: 'center' }} />
                    <div className="text-center">
                        <span className="small text-muted">{t('treasury.reconciliation.calculated_balance')}</span>
                        <div className="fw-bold font-monospace">{fmt(summary.calculated_end_balance)}</div>
                    </div>
                    <div className="text-center">
                        <span className="small text-muted">{t('treasury.reconciliation.difference')}</span>
                        <div className={`fw-bold font-monospace ${Math.abs(summary.difference) < 0.01 ? 'text-success' : 'text-danger'}`}>
                            {fmt(summary.difference)}
                        </div>
                    </div>
                </div>
            )}

            {/* === SPLIT VIEW === */}
            <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
                {/* LEFT: Bank Statement */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderInlineEnd: '1px solid var(--border-color)' }}>
                    <div style={{
                        padding: '12px 16px', background: 'var(--bg-card)', borderBottom: '1px solid var(--border-color)',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                    }}>
                        <div style={{ display: 'flex', gap: '0' }}>
                            <button
                                onClick={() => setStmtTab('unmatched')}
                                style={{
                                    padding: '6px 16px', border: 'none', borderRadius: '6px 6px 0 0', cursor: 'pointer',
                                    fontWeight: 600, fontSize: '13px',
                                    background: stmtTab === 'unmatched' ? 'var(--primary)' : 'transparent',
                                    color: stmtTab === 'unmatched' ? '#fff' : 'var(--text-secondary)',
                                }}>
                                {t('treasury.reconciliation.pending')} ({unmatchedStatementLines.length})
                            </button>
                            <button
                                onClick={() => setStmtTab('matched')}
                                style={{
                                    padding: '6px 16px', border: 'none', borderRadius: '6px 6px 0 0', cursor: 'pointer',
                                    fontWeight: 600, fontSize: '13px',
                                    background: stmtTab === 'matched' ? 'var(--success)' : 'transparent',
                                    color: stmtTab === 'matched' ? '#fff' : 'var(--text-secondary)',
                                }}>
                                {t('treasury.reconciliation.matched')} ({matchedStatementLines.length})
                            </button>
                        </div>
                        {!isPosted && (
                            <div style={{ display: 'flex', gap: '6px' }}>
                                <button className="btn btn-sm btn-outline-primary d-flex align-items-center gap-1"
                                    onClick={() => setShowAddLine(!showAddLine)} style={{ borderRadius: '8px', fontSize: '12px' }}>
                                    <Plus size={14} /> {t('treasury.reconciliation.add_line')}
                                </button>
                                <button className="btn btn-sm btn-outline-success d-flex align-items-center gap-1"
                                    onClick={() => setShowImport(!showImport)} style={{ borderRadius: '8px', fontSize: '12px' }}>
                                    <Upload size={14} /> {t('treasury.reconciliation.import_file')}
                                </button>
                                <button className="btn btn-sm btn-outline-warning d-flex align-items-center gap-1"
                                    onClick={handleAutoMatch} disabled={autoMatchLoading}
                                    style={{ borderRadius: '8px', fontSize: '12px' }}>
                                    <Zap size={14} /> {autoMatchLoading ? '...' : t('treasury.reconciliation.auto_match')}
                                </button>
                            </div>
                        )}
                    </div>
                    
                    {/* Add line form */}
                    {showAddLine && !isPosted && (
                        <div style={{ padding: '12px 16px', background: 'var(--bg-hover)', borderBottom: '1px solid var(--border-color)' }}>
                            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                                <div style={{ flex: '0 0 120px' }}>
                                    <label className="small text-muted">{t('common.date')}</label>
                                    <DateInput className="form-input form-input-sm"
                                        value={newLine.transaction_date}
                                        onChange={e => setNewLine({ ...newLine, transaction_date: e.target.value })} />
                                </div>
                                <div style={{ flex: 1, minWidth: '140px' }}>
                                    <label className="small text-muted">{t('common.description')}</label>
                                    <input type="text" className="form-input form-input-sm" placeholder={t('treasury.reconciliation.desc_placeholder')}
                                        value={newLine.description}
                                        onChange={e => setNewLine({ ...newLine, description: e.target.value })} />
                                </div>
                                <div style={{ flex: '0 0 100px' }}>
                                    <label className="small text-muted">{t('common.reference')}</label>
                                    <input type="text" className="form-input form-input-sm" placeholder="REF"
                                        value={newLine.reference}
                                        onChange={e => setNewLine({ ...newLine, reference: e.target.value })} />
                                </div>
                                <div style={{ flex: '0 0 100px' }}>
                                    <label className="small text-muted">{t('treasury.reconciliation.withdrawal')}</label>
                                    <input type="number" step="0.01" className="form-input form-input-sm" placeholder="0.00"
                                        value={newLine.debit}
                                        onChange={e => setNewLine({ ...newLine, debit: e.target.value, credit: e.target.value ? '' : newLine.credit })} />
                                </div>
                                <div style={{ flex: '0 0 100px' }}>
                                    <label className="small text-muted">{t('treasury.reconciliation.deposit')}</label>
                                    <input type="number" step="0.01" className="form-input form-input-sm" placeholder="0.00"
                                        value={newLine.credit}
                                        onChange={e => setNewLine({ ...newLine, credit: e.target.value, debit: e.target.value ? '' : newLine.debit })} />
                                </div>
                                <button className="btn btn-sm btn-primary" onClick={handleAddLine} style={{ height: '32px' }}>
                                    <Check size={14} />
                                </button>
                                <button className="btn btn-sm btn-light" onClick={() => setShowAddLine(false)} style={{ height: '32px' }}>
                                    <X size={14} />
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Import file panel */}
                    {showImport && !isPosted && (
                        <div style={{ padding: '16px', background: 'var(--bg-hover)', borderBottom: '1px solid var(--border-color)' }}>
                            {!importPreview ? (
                                <div style={{ textAlign: 'center', padding: '24px' }}>
                                    <FileSpreadsheet size={40} style={{ color: 'var(--success)', marginBottom: '12px', opacity: 0.6 }} />
                                    <p className="small text-muted mb-3">{t('treasury.upload_bank_statement')}</p>
                                    <label className="btn btn-sm btn-success" style={{ cursor: 'pointer', borderRadius: '8px' }}>
                                        <Upload size={14} style={{ marginInlineEnd: '6px' }} />
                                        {importLoading ? t('treasury.reconciliation.analyzing') : t('treasury.reconciliation.select_file')}
                                        <input type="file" accept=".csv,.xlsx,.xls,.tsv" onChange={handleFileSelect} style={{ display: 'none' }} disabled={importLoading} />
                                    </label>
                                    <button className="btn btn-sm btn-light ms-2" onClick={() => setShowImport(false)} style={{ borderRadius: '8px' }}>
                                        {t('treasury.reconciliation.cancel')}
                                    </button>
                                </div>
                            ) : (
                                <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                                        <div>
                                            <span className="fw-bold">📄 {importPreview.filename}</span>
                                            <span className="small text-muted ms-3">
                                                {importPreview.parsed_lines} {t('treasury.reconciliation.ready_for_import')}
                                                {importPreview.skipped_rows > 0 && <span className="text-warning"> ({importPreview.skipped_rows} {t('treasury.reconciliation.skipped')})</span>}
                                            </span>
                                        </div>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button className="btn btn-sm btn-primary" onClick={handleImportConfirm} disabled={importLoading}
                                                style={{ borderRadius: '8px' }}>
                                                {importLoading ? t('treasury.reconciliation.importing') : `تأكيد الاستيراد (${importPreview.all_lines?.length || 0})`}
                                            </button>
                                            <button className="btn btn-sm btn-light" onClick={() => setImportPreview(null)} style={{ borderRadius: '8px' }}>
                                                {t('treasury.reconciliation.change_file')}
                                            </button>
                                            <button className="btn btn-sm btn-outline-danger" onClick={() => { setImportPreview(null); setShowImport(false); }}
                                                style={{ borderRadius: '8px' }}>
                                                {t('treasury.reconciliation.cancel')}
                                            </button>
                                        </div>
                                    </div>
                                    <div style={{ maxHeight: '200px', overflow: 'auto', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                                        <table className="data-table" style={{ marginBottom: 0, fontSize: '12px' }}>
                                            <thead>
                                                <tr>
                                                    <th>#</th>
                                                    <th>{t('common.date')}</th>
                                                    <th>{t('common.description')}</th>
                                                    <th>{t('common.reference')}</th>
                                                    <th className="text-end">{t('treasury.withdrawal')}</th>
                                                    <th className="text-end">{t('treasury.deposit')}</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {(importPreview.preview || []).map((line, i) => (
                                                    <tr key={i}>
                                                        <td className="text-muted">{i + 1}</td>
                                                        <td>{line.transaction_date}</td>
                                                        <td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{line.description}</td>
                                                        <td>{line.reference}</td>
                                                        <td className="text-end font-monospace text-danger">{line.debit > 0 ? fmt(line.debit) : ''}</td>
                                                        <td className="text-end font-monospace text-success">{line.credit > 0 ? fmt(line.credit) : ''}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                    {importPreview.all_lines?.length > 200 && (
                                        <p className="small text-muted mt-2 text-center">{t('treasury.reconciliation.preview_limit_msg')} ({importPreview.all_lines.length})</p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    <div style={{ overflow: 'auto', flex: 1 }}>
                        <table className="data-table" style={{ marginBottom: 0 }}>
                            <thead>
                                <tr className="small text-uppercase">
                                    <th>{t('common.date')}</th>
                                    <th>{t('common.description')}</th>
                                    <th className="text-end">{t('treasury.reconciliation.withdrawal')}</th>
                                    <th className="text-end">{t('treasury.reconciliation.deposit')}</th>
                                    {!isPosted && <th style={{ width: '36px' }}></th>}
                                </tr>
                            </thead>
                            <tbody>
                                {(stmtTab === 'unmatched' ? unmatchedStatementLines : matchedStatementLines).length === 0 ? (
                                    <tr><td colSpan={isPosted ? 4 : 5} className="text-center py-4 text-muted small">
                                        {stmtTab === 'unmatched' ? t('treasury.reconciliation.no_pending') : t('treasury.reconciliation.no_matched')}
                                    </td></tr>
                                ) : (stmtTab === 'unmatched' ? unmatchedStatementLines : matchedStatementLines).map(line => (
                                    <tr key={line.id}
                                        className={`${selectedStatementLine?.id === line.id ? 'active-row' : ''} ${isPosted || stmtTab === 'matched' ? '' : 'cursor-pointer'}`}
                                        onClick={() => !isPosted && stmtTab === 'unmatched' && setSelectedStatementLine(
                                            selectedStatementLine?.id === line.id ? null : line
                                        )}>
                                        <td className="small">{line.transaction_date}</td>
                                        <td>
                                            <div className="fw-bold text-dark" style={{ fontSize: '13px' }}>{line.description}</div>
                                            <div className="small text-muted">{line.reference || ''} 
                                                {line.matched_entry_number && <span className="text-success"> ← {line.matched_entry_number}</span>}
                                            </div>
                                        </td>
                                        <td className="text-end font-monospace text-danger">{line.debit > 0 ? fmt(line.debit) : ''}</td>
                                        <td className="text-end font-monospace text-success">{line.credit > 0 ? fmt(line.credit) : ''}</td>
                                        {!isPosted && (
                                            <td className="text-center">
                                                {stmtTab === 'matched' ? (
                                                    <button className="btn btn-link text-warning p-0" title={t('treasury.reconciliation.unmatch')}
                                                        onClick={(e) => handleUnmatch(e, line.id)}>
                                                        <Unlink size={14} />
                                                    </button>
                                                ) : (
                                                    <button className="btn btn-link text-danger p-0" title={t('common.delete')}
                                                        onClick={(e) => handleDeleteLine(e, line.id)}>
                                                        <Trash2 size={14} />
                                                    </button>
                                                )}
                                            </td>
                                        )}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* RIGHT: System Ledger */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                    <div style={{
                        padding: '12px 16px', background: 'var(--bg-card)', borderBottom: '1px solid var(--border-color)',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                    }}>
                        <span className="fw-bold" style={{ fontSize: '13px', letterSpacing: '0.5px' }}>
                            {t('treasury.reconciliation.system_ledger')}
                        </span>
                        <span className="badge" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)', borderRadius: '12px' }}>
                            {ledgerLines.length} {t('treasury.reconciliation.entries')}
                        </span>
                    </div>
                    <div style={{ overflow: 'auto', flex: 1 }}>
                        <table className="data-table" style={{ marginBottom: 0 }}>
                            <thead>
                                <tr className="small text-uppercase">
                                    <th>{t('common.date')}</th>
                                    <th>{t('common.reference')}</th>
                                    <th className="text-end">{t('common.debit')}</th>
                                    <th className="text-end">{t('common.credit')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {ledgerLines.length === 0 ? (
                                    <tr><td colSpan="4" className="text-center py-4 text-muted small">
                                        {t('treasury.reconciliation.no_ledger_entries')}
                                    </td></tr>
                                ) : ledgerLines.map(line => (
                                    <tr key={line.id}
                                        className={`${selectedLedgerLine?.id === line.id ? 'active-row' : ''} ${isPosted ? '' : 'cursor-pointer'}`}
                                        onClick={() => !isPosted && setSelectedLedgerLine(
                                            selectedLedgerLine?.id === line.id ? null : line
                                        )}>
                                        <td className="small">{formatDate(line.entry_date)}</td>
                                        <td>
                                            <div className="fw-bold text-dark" style={{ fontSize: '13px' }}>{line.entry_number}</div>
                                            <div className="small text-muted">{line.line_desc || line.header_desc}</div>
                                        </td>
                                        <td className="text-end font-monospace text-success">{line.debit > 0 ? fmt(line.debit) : ''}</td>
                                        <td className="text-end font-monospace text-danger">{line.credit > 0 ? fmt(line.credit) : ''}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            {/* === MATCH ACTION BAR === */}
            {!isPosted && (
                <div style={{
                    padding: '16px 24px', borderTop: '2px solid var(--border-color)',
                    background: 'var(--bg-card)', display: 'flex', justifyContent: 'center',
                    alignItems: 'center', gap: '32px', flexShrink: 0,
                    boxShadow: '0 -4px 12px rgba(0,0,0,0.05)'
                }}>
                    <div className="text-center" style={{ minWidth: '200px' }}>
                        <div className="small text-muted mb-1">{t('treasury.reconciliation.selected_bank_line')}</div>
                        <div style={{
                            padding: '10px 16px', borderRadius: '10px', border: '2px solid',
                            borderColor: selectedStatementLine ? 'var(--primary)' : 'var(--border-color)',
                            background: selectedStatementLine ? 'var(--bg-hover)' : 'transparent',
                            minHeight: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center'
                        }}>
                            {selectedStatementLine ? (
                                <div>
                                    <div className="fw-bold" style={{ color: 'var(--primary)', fontSize: '15px' }}>
                                        {selectedStatementLine.debit > 0 
                                            ? <span className="text-danger">- {fmt(selectedStatementLine.debit)}</span>
                                            : <span className="text-success">+ {fmt(selectedStatementLine.credit)}</span>
                                        }
                                    </div>
                                    <div className="small text-muted">{selectedStatementLine.description}</div>
                                </div>
                            ) : <span className="text-muted">—</span>}
                        </div>
                    </div>

                    <button
                        className={`btn ${selectedStatementLine && selectedLedgerLine ? 'btn-primary' : 'btn-light'}`}
                        onClick={handleMatch}
                        disabled={!selectedStatementLine || !selectedLedgerLine}
                        style={{
                            width: '56px', height: '56px', borderRadius: '50%',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            boxShadow: selectedStatementLine && selectedLedgerLine ? '0 4px 12px rgba(var(--primary-rgb), 0.3)' : 'none',
                            transition: 'all 0.2s'
                        }}>
                        <Link2 size={24} />
                    </button>

                    <div className="text-center" style={{ minWidth: '200px' }}>
                        <div className="small text-muted mb-1">{t('treasury.reconciliation.selected_system_line')}</div>
                        <div style={{
                            padding: '10px 16px', borderRadius: '10px', border: '2px solid',
                            borderColor: selectedLedgerLine ? 'var(--primary)' : 'var(--border-color)',
                            background: selectedLedgerLine ? 'var(--bg-hover)' : 'transparent',
                            minHeight: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center'
                        }}>
                            {selectedLedgerLine ? (
                                <div>
                                    <div className="fw-bold" style={{ color: 'var(--primary)', fontSize: '15px' }}>
                                        {selectedLedgerLine.debit > 0 
                                            ? <span className="text-success">+ {fmt(selectedLedgerLine.debit)}</span>
                                            : <span className="text-danger">- {fmt(selectedLedgerLine.credit)}</span>
                                        }
                                    </div>
                                    <div className="small text-muted">{selectedLedgerLine.entry_number}</div>
                                </div>
                            ) : <span className="text-muted">—</span>}
                        </div>
                    </div>
                </div>
            )}

            <style>{`
                .active-row { background-color: var(--bg-hover) !important; border-inline-start: 4px solid var(--primary) !important; }
                .cursor-pointer { cursor: pointer; }
                .cursor-pointer:hover { background-color: var(--bg-hover); }
                .form-input-sm { padding: 4px 8px !important; font-size: 13px !important; height: 32px !important; }
            `}</style>
        </div>
    );
};

export default ReconciliationForm;
