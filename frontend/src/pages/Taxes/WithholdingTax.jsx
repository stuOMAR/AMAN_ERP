import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import DOMPurify from 'dompurify'
import { externalAPI } from '../../utils/api'
import { formatNumber } from '../../utils/format'
import { getCurrency, hasPermission } from '../../utils/auth'
import '../../components/ModuleStyles.css'

import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
import { useBranch } from '../../context/BranchContext'
import DataTable from '../../components/common/DataTable'
import { Decimal } from '../../utils/decimal'

function makeIdempotencyKey(prefix) {
    if (window.crypto?.randomUUID) return `${prefix}:${window.crypto.randomUUID()}`
    return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`
}

function sumMoney(rows, field) {
    return rows.reduce((total, row) => total.add(row?.[field] || '0.00'), new Decimal(0)).toString()
}

export default function WithholdingTax() {
    const { t, i18n } = useTranslation()
  const { showToast } = useToast()
    const isRTL = i18n.language === 'ar'
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const canManageRates = hasPermission(['accounting.manage', 'taxes.manage'])
    const canCalculateWht = hasPermission(['accounting.view', 'buying.view'])
    const canCreateTransactions = hasPermission(['accounting.edit', 'taxes.manage'])
    const [activeTab, setActiveTab] = useState('rates')
    const [loading, setLoading] = useState(true)
    const certRef = useRef(null)

    // Rates state
    const [rates, setRates] = useState([])
    const [showRateModal, setShowRateModal] = useState(false)
    const [rateForm, setRateForm] = useState({ name: '', name_ar: '', rate: '', category: 'services' })
    const [rateSubmitting, setRateSubmitting] = useState(false)

    // Transactions state
    const [transactions, setTransactions] = useState([])
    const [txLoading, setTxLoading] = useState(false)

    // Calculator state
    const [calcRateId, setCalcRateId] = useState('')
    const [calcSupplierId, setCalcSupplierId] = useState('')
    const [calcPaymentId, setCalcPaymentId] = useState('')
    const [calcGross, setCalcGross] = useState('')
    const [calcResult, setCalcResult] = useState(null)
    const [calcLoading, setCalcLoading] = useState(false)
    const [txSubmitting, setTxSubmitting] = useState(false)

    // Certificate state
    const [selectedTx, setSelectedTx] = useState(null)
    const [showCertificate, setShowCertificate] = useState(false)

    const categoryLabels = {
        services: t('wht.cat_services'),
        rent: t('wht.cat_rent'),
        royalties: t('wht.cat_royalties'),
        consulting: t('wht.cat_consulting'),
        other: t('wht.cat_other'),
    }

    const fetchRates = useCallback(async () => {
        try {
            setLoading(true)
            const params = currentBranch?.id ? { branch_id: currentBranch.id } : undefined
            const res = await externalAPI.listWhtRates(params)
            setRates(res.data ?? res)
        } catch (e) {
            console.error(e)
            showToast(t('wht.error_loading_rates', 'حدث خطأ في تحميل نسب ضريبة الاستقطاع'), 'error')
        } finally {
            setLoading(false)
        }
    }, [currentBranch?.id, showToast, t])

    const fetchTransactions = useCallback(async () => {
        try {
            setTxLoading(true)
            const params = currentBranch?.id ? { branch_id: currentBranch.id } : undefined
            const res = await externalAPI.listWhtTransactions(params)
            setTransactions(res.data ?? res)
        } catch (e) {
            console.error(e)
            showToast(t('wht.error_loading_transactions', 'حدث خطأ في تحميل المعاملات'), 'error')
        } finally {
            setTxLoading(false)
        }
    }, [currentBranch?.id, showToast, t])

    useEffect(() => {
        fetchRates()
    }, [fetchRates])

    useEffect(() => {
        if (activeTab === 'transactions') {
            fetchTransactions()
            if (rates.length === 0) fetchRates()
        }
    }, [activeTab, fetchTransactions, fetchRates, rates.length])

    const handleCreateRate = async (e) => {
        e.preventDefault()
        try {
            setRateSubmitting(true)
            await externalAPI.createWhtRate({
                name: rateForm.name.trim(),
                name_ar: rateForm.name_ar || null,
                rate: String(rateForm.rate),
                category: rateForm.category || 'services',
            })
            setShowRateModal(false)
            setRateForm({ name: '', name_ar: '', rate: '', category: 'services' })
            fetchRates()
        } catch (e) {
            console.error(e)
            showToast(t('wht.error_creating_rate', 'error'))
        } finally {
            setRateSubmitting(false)
        }
    }

    const handleCalculate = async () => {
        if (!calcRateId || !calcGross) return
        if (!currentBranch?.id) {
            showToast(t('wht.select_branch_first', 'يرجى تحديد الفرع أولاً'), 'error')
            return
        }
        try {
            setCalcLoading(true)
            const res = await externalAPI.calculateWht({
                wht_rate_id: parseInt(calcRateId),
                gross_amount: String(calcGross),
                branch_id: currentBranch?.id || null,
            })
            setCalcResult(res.data ?? res)
        } catch (e) {
            console.error(e)
            showToast(t('wht.error_calculating', 'error'))
        } finally {
            setCalcLoading(false)
        }
    }

    const handleCreateTransaction = async () => {
        if (!calcResult || !calcSupplierId || !calcPaymentId || txSubmitting) return
        try {
            setTxSubmitting(true)
            await externalAPI.createWhtTransaction({
                invoice_id: null,
                payment_id: parseInt(calcPaymentId),
                supplier_id: parseInt(calcSupplierId),
                wht_rate_id: parseInt(calcRateId),
                gross_amount: String(calcGross),
                branch_id: currentBranch?.id || null,
            }, makeIdempotencyKey(`wht-tx:${calcSupplierId}`))
            setCalcResult(null)
            setCalcRateId('')
            setCalcSupplierId('')
            setCalcPaymentId('')
            setCalcGross('')
            fetchTransactions()
        } catch (e) {
            console.error(e)
            showToast(t('wht.error_creating_tx', 'error'))
        } finally {
            setTxSubmitting(false)
        }
    }

    const handlePrintCertificate = () => {
        if (!certRef.current) return;
        const printWindow = window.open('', '_blank');
        if (!printWindow) return;

        // SEC / TASK-029: build the print document using DOM APIs instead of
        // document.write with template-literal interpolation. Translated title
        // and direction go into the DOM via textContent / setAttribute.
        const doc = printWindow.document;
        doc.open();
        doc.write('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>');
        doc.close();
        doc.documentElement.setAttribute('dir', isRTL ? 'rtl' : 'ltr');
        doc.title = String(t('wht.certificate_title') || '');

        const style = doc.createElement('style');
        style.textContent =
            '* { margin:0; padding:0; box-sizing:border-box; } ' +
            "body { font-family: 'Segoe UI', Tahoma, sans-serif; padding: 30px; direction: " +
            (isRTL ? 'rtl' : 'ltr') + '; color: #1a1a2e; } ' +
            '.cert-container { max-width: 650px; margin: auto; border: 3px solid #1e40af; border-radius: 12px; padding: 40px; } ' +
            '.cert-header { text-align: center; border-bottom: 2px solid #1e40af; padding-bottom: 20px; margin-bottom: 24px; } ' +
            '.cert-header h1 { color: #1e40af; font-size: 24px; margin-bottom: 4px; } ' +
            '.cert-header h2 { font-size: 16px; color: #6b7280; font-weight: 500; } ' +
            '.cert-number { text-align: center; font-size: 14px; color: #7c3aed; margin-bottom: 20px; padding: 8px; background: #f5f3ff; border-radius: 6px; } ' +
            '.cert-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; } ' +
            '.cert-field { margin-bottom: 8px; } ' +
            '.cert-field .label { font-size: 12px; color: #6b7280; margin-bottom: 2px; } ' +
            '.cert-field .value { font-weight: 600; font-size: 14px; } ' +
            '.cert-amounts { background: #f8fafc; padding: 16px; border-radius: 8px; margin-bottom: 24px; } ' +
            '.cert-amounts table { width: 100%; border-collapse: collapse; } ' +
            '.cert-amounts th { text-align: ' + (isRTL ? 'right' : 'left') + '; padding: 8px; font-size: 13px; border-bottom: 1px solid #e2e8f0; } ' +
            '.cert-amounts td { padding: 8px; font-size: 14px; border-bottom: 1px solid #f1f5f9; } ' +
            '.cert-footer { margin-top: 40px; display: flex; justify-content: space-between; } ' +
            '.cert-footer .sign { text-align: center; min-width: 160px; } ' +
            '.cert-footer .sign-line { border-top: 1px solid #1a1a2e; margin-top: 40px; padding-top: 8px; font-size: 12px; color: #6b7280; } ' +
            '.cert-disclaimer { margin-top: 24px; font-size: 11px; color: #9ca3af; text-align: center; border-top: 1px dashed #d1d5db; padding-top: 12px; } ' +
            '@media print { body { padding: 10px; } .cert-container { border-width: 2px; } }';
        doc.head.appendChild(style);

        // SEC-C4a: Sanitize via DOMPurify before injecting into the print window.
        const wrapper = doc.createElement('div');
        wrapper.innerHTML = DOMPurify.sanitize(certRef.current.innerHTML, { USE_PROFILES: { html: true } });
        doc.body.appendChild(wrapper);

        setTimeout(() => { printWindow.print(); }, 300);
    };

    const openCertificate = (tx) => {
        setSelectedTx(tx);
        setShowCertificate(true);
    };

    const formatDate = (d) => {
        if (!d) return '—'
        return formatShortDate(d)
    }

    // Summary stats
    const totalWht = sumMoney(transactions, 'wht_amount');
    const totalGross = sumMoney(transactions, 'gross_amount');
    const displayCurrency = transactions[0]?.currency || calcResult?.currency || currency

    const rateColumns = [
        { key: 'name', label: t('wht.col_name'), render: (v) => <span className="font-medium">{v}</span> },
        { key: 'name_ar', label: t('wht.col_name_ar'), render: (v) => v || '—' },
        { key: 'rate', label: t('wht.col_rate'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (v) => `${formatNumber(v, 2)}%` },
        { key: 'category', label: t('wht.col_category'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (v) => <span className="badge badge-info">{categoryLabels[v] || v}</span> },
        { key: 'country_code', label: t('taxes.country_code'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (v) => v || '—' },
        { key: 'is_active', label: t('wht.col_status'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (v) => <span className={`badge ${v ? 'badge-success' : 'badge-secondary'}`}>{v ? t('wht.active') : t('wht.inactive')}</span> },
    ]

    const transactionColumns = [
        { key: 'invoice_id', label: t('wht.col_invoice'), render: (v) => v || '—' },
        { key: 'supplier_name', label: t('wht.col_supplier'), render: (v, tx) => v || tx.supplier_id || '—' },
        { key: 'gross_amount', label: t('wht.gross_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left' }, render: (v, tx) => <span className="font-mono">{formatNumber(v)} <small>{tx.currency || displayCurrency}</small></span> },
        { key: 'wht_rate', label: t('wht.col_rate'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (v) => <span className="font-mono">{formatNumber(v, 2)}%</span> },
        { key: 'wht_amount', label: t('wht.wht_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left' }, render: (v, tx) => <span className="font-mono text-danger">{formatNumber(v)} <small>{tx.currency || displayCurrency}</small></span> },
        { key: 'net_amount', label: t('wht.net_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left' }, render: (v, tx) => <span className="font-mono text-success">{formatNumber(v)} <small>{tx.currency || displayCurrency}</small></span> },
        { key: 'certificate_number', label: t('wht.col_certificate'), render: (v) => v || '—' },
        { key: 'created_at', label: t('wht.col_date'), render: (v, tx) => formatDate(tx.period_date || v) },
        { key: 'actions', label: t('wht.col_actions'), sortable: false, searchable: false, exportable: false, render: (_, tx) => (
            <button className="btn btn-sm btn-secondary" onClick={() => openCertificate(tx)} title={t('wht.print_certificate')}>
                🖨️
            </button>
        ) },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('wht.title')}</h1>
                    <p className="workspace-subtitle">{t('wht.subtitle')}</p>
                </div>
                {activeTab === 'rates' && canManageRates && (
                    <div className="header-actions">
                        <button className="btn btn-primary" onClick={() => setShowRateModal(true)}>
                            + {t('wht.add_rate')}
                        </button>
                    </div>
                )}
            </div>

            {/* Summary */}
            {transactions.length > 0 && (
                <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', marginBottom: 24 }}>
                    <div className="metric-card">
                        <div className="metric-label">{t('wht.total_transactions')}</div>
                        <div className="metric-value" style={{ color: '#2563eb' }}>{transactions.length}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('wht.total_gross')}</div>
                        <div className="metric-value" style={{ color: '#7c3aed' }}>{formatNumber(totalGross)} <small style={{ fontSize: 12 }}>{displayCurrency}</small></div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('wht.total_withheld')}</div>
                        <div className="metric-value" style={{ color: '#dc2626' }}>{formatNumber(totalWht)} <small style={{ fontSize: 12 }}>{displayCurrency}</small></div>
                    </div>
                </div>
            )}

            {/* Tabs */}
            <div className="tabs-container" style={{ marginBottom: '24px' }}>
                <button
                    className={`tab-btn ${activeTab === 'rates' ? 'active' : ''}`}
                    onClick={() => setActiveTab('rates')}
                >
                    {t('wht.tab_rates')}
                </button>
                <button
                    className={`tab-btn ${activeTab === 'transactions' ? 'active' : ''}`}
                    onClick={() => setActiveTab('transactions')}
                >
                    {t('wht.tab_transactions')}
                </button>
            </div>

            {/* ===== Rates Tab ===== */}
            {activeTab === 'rates' && (
                <div className="section-card">
                    <DataTable
                        columns={rateColumns}
                        data={rates}
                        loading={loading}
                        rowKey="id"
                        searchable
                        exportable
                        exportName="wht-rates"
                        emptyTitle={t('wht.no_rates')}
                    />
                </div>
            )}

            {/* ===== Transactions Tab ===== */}
            {activeTab === 'transactions' && (
                <>
                    {/* WHT Calculator */}
                    {canCalculateWht && (
                    <div className="section-card" style={{ marginBottom: '24px' }}>
                        <h3 className="section-title">{t('wht.calculator_title')}</h3>
                        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                            <div className="form-group" style={{ flex: 1, minWidth: '200px', marginBottom: 0 }}>
                                <label className="form-label">{t('wht.select_rate')}</label>
                                <select
                                    className="form-input"
                                    value={calcRateId}
                                    onChange={(e) => setCalcRateId(e.target.value)}
                                >
                                    <option value="">-- {t('wht.select_rate')} --</option>
                                    {rates.map((r) => (
                                        <option key={r.id} value={r.id}>
                                            {r.name_ar || r.name} ({formatNumber(r.rate, 2)}%)
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group" style={{ flex: 1, minWidth: '160px', marginBottom: 0 }}>
                                <label className="form-label">{t('wht.col_supplier')}</label>
                                <input
                                    type="number"
                                    className="form-input"
                                    placeholder={t('wht.supplier_id')}
                                    value={calcSupplierId}
                                    onChange={(e) => setCalcSupplierId(e.target.value)}
                                    min="1"
                                />
                            </div>
                            <div className="form-group" style={{ flex: 1, minWidth: '160px', marginBottom: 0 }}>
                                <label className="form-label">{t('wht.payment_id')}</label>
                                <input
                                    type="number"
                                    className="form-input"
                                    placeholder={t('wht.payment_id')}
                                    value={calcPaymentId}
                                    onChange={(e) => setCalcPaymentId(e.target.value)}
                                    min="1"
                                />
                            </div>
                            <div className="form-group" style={{ flex: 1, minWidth: '200px', marginBottom: 0 }}>
                                <label className="form-label">{t('wht.gross_amount')}</label>
                                <input
                                    type="number"
                                    className="form-input"
                                    placeholder="0.00"
                                    value={calcGross}
                                    onChange={(e) => setCalcGross(e.target.value)}
                                    min="0"
                                    step="0.01"
                                />
                            </div>
                            <button
                                className="btn btn-primary"
                                onClick={handleCalculate}
                                disabled={calcLoading || !currentBranch?.id || !calcRateId || !calcGross}
                                style={{ height: '42px' }}
                            >
                                {calcLoading ? t('wht.calculating') : t('wht.calculate_btn')}
                            </button>
                        </div>

                        {calcResult && (
                            <div style={{
                                marginTop: '20px',
                                padding: '16px',
                                background: 'rgba(37, 99, 235, 0.05)',
                                borderRadius: '12px',
                                border: '1px solid rgba(37, 99, 235, 0.15)',
                                display: 'flex',
                                gap: '32px',
                                alignItems: 'center',
                                flexWrap: 'wrap',
                            }}>
                                <div>
                                    <span className="text-secondary" style={{ fontSize: '13px' }}>{t('wht.wht_amount')}</span>
                                    <div className="font-bold text-danger" style={{ fontSize: '1.25rem' }}>
                                        {formatNumber(calcResult.wht_amount)} <small>{displayCurrency}</small>
                                    </div>
                                </div>
                                <div>
                                    <span className="text-secondary" style={{ fontSize: '13px' }}>{t('wht.net_amount')}</span>
                                    <div className="font-bold text-success" style={{ fontSize: '1.25rem' }}>
                                        {formatNumber(calcResult.net_amount)} <small>{displayCurrency}</small>
                                    </div>
                                </div>
                                {canCreateTransactions && (
                                    <button
                                        className="btn btn-success"
                                        onClick={handleCreateTransaction}
                                        disabled={txSubmitting || !currentBranch?.id || !calcSupplierId || !calcPaymentId}
                                        style={{ marginRight: 'auto' }}
                                    >
                                        {txSubmitting ? t('wht.saving') : t('wht.create_transaction')}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                    )}

                    {/* Transactions Table */}
                    <div className="section-card">
                        <DataTable
                            columns={transactionColumns}
                            data={transactions}
                            loading={txLoading}
                            rowKey="id"
                            searchable
                            exportable
                            exportName="wht-transactions"
                            emptyTitle={t('wht.no_transactions')}
                        />
                    </div>
                </>
            )}

            {/* ===== Create Rate Modal ===== */}
            {showRateModal && (
                <div className="modal-overlay" onClick={() => setShowRateModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>{t('wht.add_rate_modal')}</h3>
                            <button className="modal-close" onClick={() => setShowRateModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleCreateRate}>
                            <div className="modal-body">
                                <div className="form-group">
                                    <label className="form-label">{t('wht.col_name')}</label>
                                    <input
                                        type="text"
                                        className="form-input"
                                        value={rateForm.name}
                                        onChange={(e) => setRateForm({ ...rateForm, name: e.target.value })}
                                        required
                                        placeholder={t('taxes.wht_name_placeholder')}
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('wht.col_name_ar')}</label>
                                    <input
                                        type="text"
                                        className="form-input"
                                        value={rateForm.name_ar}
                                        onChange={(e) => setRateForm({ ...rateForm, name_ar: e.target.value })}
                                        required
                                        placeholder={t('wht.name_ar_placeholder')}
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('wht.col_rate')}</label>
                                    <input
                                        type="number"
                                        className="form-input"
                                        value={rateForm.rate}
                                        onChange={(e) => setRateForm({ ...rateForm, rate: e.target.value })}
                                        required
                                        min="0"
                                        max="100"
                                        step="0.01"
                                        placeholder="5"
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('wht.col_category')}</label>
                                    <select
                                        className="form-input"
                                        value={rateForm.category}
                                        onChange={(e) => setRateForm({ ...rateForm, category: e.target.value })}
                                    >
                                        <option value="services">{t('wht.cat_services')}</option>
                                        <option value="rent">{t('wht.cat_rent')}</option>
                                        <option value="royalties">{t('wht.cat_royalties')}</option>
                                        <option value="consulting">{t('wht.cat_consulting')}</option>
                                        <option value="other">{t('wht.cat_other')}</option>
                                    </select>
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowRateModal(false)}>
                                    {t('common.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={rateSubmitting}>
                                    {rateSubmitting ? t('wht.saving') : t('common.save')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* ===== WHT Certificate Modal ===== */}
            {showCertificate && selectedTx && (
                <div className="modal-overlay" onClick={() => setShowCertificate(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '700px', maxHeight: '90vh', overflow: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}>{t('wht.certificate_title')}</h3>
                            <div className="d-flex gap-2" style={{ alignItems: 'center' }}>
                                <button className="btn btn-sm btn-primary" onClick={handlePrintCertificate}>🖨️ {t('wht.print_certificate')}</button>
                                <button type="button" onClick={() => setShowCertificate(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: 'var(--text-muted)' }}>✕</button>
                            </div>
                        </div>

                        <div ref={certRef}>
                            <div className="cert-container" style={{ maxWidth: 650, margin: 'auto', border: '3px solid #1e40af', borderRadius: 12, padding: 40 }}>
                                {/* Header */}
                                <div style={{ textAlign: 'center', borderBottom: '2px solid #1e40af', paddingBottom: 20, marginBottom: 24 }}>
                                    <h1 style={{ color: '#1e40af', fontSize: 22, marginBottom: 4 }}>{t('wht.certificate_heading')}</h1>
                                    <h2 style={{ fontSize: 15, color: '#6b7280', fontWeight: 500 }}>{t('wht.certificate_heading')}</h2>
                                </div>

                                {/* Certificate Number */}
                                <div style={{ textAlign: 'center', fontSize: 14, color: '#7c3aed', marginBottom: 20, padding: 8, background: '#f5f3ff', borderRadius: 6 }}>
                                    {t('wht.certificate_number')}: <strong>{selectedTx.certificate_number || '—'}</strong>
                                </div>

                                {/* Details Grid */}
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
                                    <div>
                                        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>{t('wht.col_supplier')}</div>
                                        <div style={{ fontWeight: 600, fontSize: 14 }}>{selectedTx.supplier_name || selectedTx.supplier_id || '—'}</div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>{t('wht.col_invoice')}</div>
                                        <div style={{ fontWeight: 600, fontSize: 14 }}>{selectedTx.invoice_id || '—'}</div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>{t('wht.col_date')}</div>
                                        <div style={{ fontWeight: 600, fontSize: 14 }}>{formatDate(selectedTx.created_at)}</div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>{t('wht.col_rate')}</div>
                                        <div style={{ fontWeight: 600, fontSize: 14 }}>{formatNumber(selectedTx.wht_rate, 2)}%</div>
                                    </div>
                                </div>

                                {/* Amounts */}
                                <div style={{ background: '#f8fafc', padding: 16, borderRadius: 8, marginBottom: 24 }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                        <thead>
                                            <tr>
                                                <th style={{ textAlign: isRTL ? 'right' : 'left', padding: 8, fontSize: 13, borderBottom: '1px solid #e2e8f0' }}>{t('wht.cert_description')}</th>
                                                <th style={{ textAlign: isRTL ? 'left' : 'right', padding: 8, fontSize: 13, borderBottom: '1px solid #e2e8f0' }}>{t('wht.cert_amount')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <tr>
                                                <td style={{ padding: '10px 8px', borderBottom: '1px solid #f1f5f9', fontSize: 14 }}>{t('wht.gross_amount')}</td>
                                                <td style={{ padding: '10px 8px', borderBottom: '1px solid #f1f5f9', fontSize: 14, textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedTx.gross_amount)} {currency}</td>
                                            </tr>
                                            <tr>
                                                <td style={{ padding: '10px 8px', borderBottom: '1px solid #f1f5f9', fontSize: 14, color: '#dc2626' }}>{t('wht.wht_amount')} ({formatNumber(selectedTx.wht_rate, 2)}%)</td>
                                                <td style={{ padding: '10px 8px', borderBottom: '1px solid #f1f5f9', fontSize: 14, textAlign: isRTL ? 'left' : 'right', color: '#dc2626', fontWeight: 600 }}>-{formatNumber(selectedTx.wht_amount)} {currency}</td>
                                            </tr>
                                            <tr style={{ fontWeight: 700 }}>
                                                <td style={{ padding: '10px 8px', fontSize: 15, borderTop: '2px solid #1e40af' }}>{t('wht.net_amount')}</td>
                                                <td style={{ padding: '10px 8px', fontSize: 15, textAlign: isRTL ? 'left' : 'right', color: '#16a34a', borderTop: '2px solid #1e40af' }}>{formatNumber(selectedTx.net_amount)} {currency}</td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>

                                {/* Signatures */}
                                <div style={{ marginTop: 40, display: 'flex', justifyContent: 'space-between' }}>
                                    <div style={{ textAlign: 'center', minWidth: 160 }}>
                                        <div style={{ borderTop: '1px solid #1a1a2e', marginTop: 50, paddingTop: 8, fontSize: 12, color: '#6b7280' }}>{t('wht.cert_company_stamp')}</div>
                                    </div>
                                    <div style={{ textAlign: 'center', minWidth: 160 }}>
                                        <div style={{ borderTop: '1px solid #1a1a2e', marginTop: 50, paddingTop: 8, fontSize: 12, color: '#6b7280' }}>{t('wht.cert_authorized_sig')}</div>
                                    </div>
                                </div>

                                <div style={{ marginTop: 24, fontSize: 11, color: '#9ca3af', textAlign: 'center', borderTop: '1px dashed #d1d5db', paddingTop: 12 }}>
                                    {t('wht.cert_disclaimer')}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
