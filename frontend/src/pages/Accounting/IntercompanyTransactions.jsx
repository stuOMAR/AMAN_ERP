import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI, currenciesAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton'
import '../../components/ModuleStyles.css'
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
import { calculateCrossExchangeRate, fetchCrossExchangeRate } from '../../hooks/useExchangeRate'

const normalizeCurrencyCode = (value, fallback = 'SAR') => {
    const code = String(value || '').trim().toUpperCase()
    return code || fallback
}

const buildCurrencyRateMap = (currencies) => currencies.reduce((acc, currency) => {
    const code = normalizeCurrencyCode(currency.code, '')
    const rate = Number(currency.current_rate ?? currency.rate ?? currency.exchange_rate)
    if (code && Number.isFinite(rate) && rate > 0) acc[code] = rate
    return acc
}, {})

const formatRateForInput = (rate) => {
    const value = Number(rate)
    if (!Number.isFinite(value) || value <= 0) return '1'
    return value.toFixed(8).replace(/\.?0+$/, '')
}

const calculateConvertedAmount = (amount, rate) => {
    const a = Number(amount)
    const r = Number(rate)
    if (!Number.isFinite(a) || !Number.isFinite(r) || a <= 0 || r <= 0) return 0
    return Number((a * r).toFixed(4))
}

function IntercompanyTransactions() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency() || 'SAR'
    const [transactions, setTransactions] = useState([])
    const [eliminationReport, setEliminationReport] = useState(null)
    const [loading, setLoading] = useState(true)
    const [tab, setTab] = useState('list')
    const [showForm, setShowForm] = useState(false)
    const [entities, setEntities] = useState([])
    const [currencies, setCurrencies] = useState([])
    const [currencyRates, setCurrencyRates] = useState({})
    const [form, setForm] = useState({
        source_entity_id: '',
        target_entity_id: '',
        transaction_type: 'sale',
        description: '',
        // The actual money currency / amount being moved.
        transaction_currency: currency,
        amount: '',
        // Functional currencies derived from each entity (read-only).
        source_currency: currency,
        target_currency: currency,
        // Cross rates: txn → source_func, txn → target_func.
        source_rate: '1',
        target_rate: '1',
        reference: '',
    })

    useEffect(() => { fetchData(); fetchEntities(); fetchCurrencies() }, [currentBranch])

    const fetchEntities = async () => {
        try {
            const res = await accountingAPI.listEntityGroups()
            setEntities(res.data || [])
        } catch (err) {
            console.error('Failed to fetch entities', err)
        }
    }

    const fetchCurrencies = async () => {
        try {
            const res = await currenciesAPI.list()
            const list = Array.isArray(res.data) ? res.data : []
            setCurrencies(list)
            setCurrencyRates(buildCurrencyRateMap(list))
        } catch (err) {
            console.error('Failed to fetch currencies', err)
        }
    }

    // Auto-detect source entity from current branch
    const branchSourceEntity = useMemo(() => entities.find(e =>
        e.branch_id === currentBranch?.id ||
        e.name?.includes(currentBranch?.branch_name || currentBranch?.name)
    ), [entities, currentBranch])
    const sourceEntity = useMemo(
        () => entities.find(e => String(e.id) === String(form.source_entity_id)) || branchSourceEntity,
        [entities, form.source_entity_id, branchSourceEntity],
    )
    const targetEntity = useMemo(
        () => entities.find(e => String(e.id) === String(form.target_entity_id)),
        [entities, form.target_entity_id],
    )
    const txnCurrency = normalizeCurrencyCode(form.transaction_currency, currentBranch?.default_currency || currency)
    const sourceCurrency = normalizeCurrencyCode(form.source_currency, txnCurrency)
    const targetCurrency = normalizeCurrencyCode(form.target_currency, txnCurrency)
    const sourceFuncAmount = calculateConvertedAmount(form.amount, form.source_rate)
    const targetFuncAmount = calculateConvertedAmount(form.amount, form.target_rate)

    useEffect(() => {
        if (!form.source_entity_id && branchSourceEntity?.id) {
            setForm(prev => prev.source_entity_id ? prev : { ...prev, source_entity_id: String(branchSourceEntity.id) })
        }
    }, [branchSourceEntity?.id, form.source_entity_id])

    useEffect(() => {
        const nextSourceCurrency = normalizeCurrencyCode(sourceEntity?.group_currency, currentBranch?.default_currency || currency)
        const nextTargetCurrency = normalizeCurrencyCode(targetEntity?.group_currency, nextSourceCurrency)
        setForm(prev => {
            const next = {}
            if (sourceEntity && prev.source_currency !== nextSourceCurrency) next.source_currency = nextSourceCurrency
            if (targetEntity && prev.target_currency !== nextTargetCurrency) next.target_currency = nextTargetCurrency
            return Object.keys(next).length ? { ...prev, ...next } : prev
        })
    }, [sourceEntity, targetEntity, currentBranch?.default_currency, currency])

    useEffect(() => {
        const localSrc = calculateCrossExchangeRate(currencyRates[txnCurrency], currencyRates[sourceCurrency])
        const localTgt = calculateCrossExchangeRate(currencyRates[txnCurrency], currencyRates[targetCurrency])
        if (Object.keys(currencyRates).length > 0) {
            setForm(prev => ({
                ...prev,
                source_rate: formatRateForInput(localSrc),
                target_rate: formatRateForInput(localTgt),
            }))
        }

        let cancelled = false
        Promise.all([
            fetchCrossExchangeRate(txnCurrency, sourceCurrency),
            fetchCrossExchangeRate(txnCurrency, targetCurrency),
        ]).then(([s, t]) => {
            if (cancelled) return
            setForm(prev => ({
                ...prev,
                source_rate: formatRateForInput(s),
                target_rate: formatRateForInput(t),
            }))
        }).catch(() => {})
        return () => { cancelled = true }
    }, [txnCurrency, sourceCurrency, targetCurrency, currencyRates])

    const fetchData = async () => {
        try {
            setLoading(true)
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await accountingAPI.listIntercompanyTransactions(params)
            setTransactions(res.data)
        } catch (err) {
            console.error('Failed to fetch intercompany transactions', err)
        } finally {
            setLoading(false)
        }
    }

    const fetchElimination = async () => {
        try {
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await accountingAPI.getIntercompanyEliminationReport(params)
            setEliminationReport(res.data)
            setTab('elimination')
        } catch (err) {
            showToast(err.response?.data?.detail || 'Error', 'error')
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!sourceEntity || !targetEntity) {
            showToast(t('intercompany.entity_required', 'اختر الكيان المصدر والكيان الهدف'), 'error')
            return
        }
        if (sourceEntity.id === targetEntity.id) {
            showToast(t('intercompany.same_entity_error', 'لا يمكن اختيار نفس الكيان كمصدر وهدف'), 'error')
            return
        }
        const txnAmount = Number(form.amount)
        const srcRate = Number(form.source_rate)
        const tgtRate = Number(form.target_rate)
        if (!Number.isFinite(txnAmount) || txnAmount <= 0 || !Number.isFinite(srcRate) || srcRate <= 0 || !Number.isFinite(tgtRate) || tgtRate <= 0) {
            showToast(t('intercompany.invalid_amount_or_rate', 'تحقق من المبلغ وسعر الصرف'), 'error')
            return
        }
        const crossRate = targetFuncAmount > 0 ? Number((sourceFuncAmount / targetFuncAmount).toFixed(8)) : 1
        try {
            await accountingAPI.createIntercompanyTransaction({
                source_entity_id: sourceEntity.id,
                target_entity_id: parseInt(form.target_entity_id, 10),
                transaction_type: form.transaction_type,
                description: form.description,
                source_amount: sourceFuncAmount,
                source_currency: sourceCurrency,
                target_amount: targetFuncAmount,
                target_currency: targetCurrency,
                transaction_currency: txnCurrency,
                transaction_amount: txnAmount,
                exchange_rate: crossRate || 1,
                reference_document: form.reference || undefined,
            })
            setShowForm(false)
            setForm({
                source_entity_id: sourceEntity?.id ? String(sourceEntity.id) : '',
                target_entity_id: '',
                transaction_type: 'sale',
                description: '',
                transaction_currency: txnCurrency,
                amount: '',
                source_currency: sourceCurrency,
                target_currency: sourceCurrency,
                source_rate: '1',
                target_rate: '1',
                reference: '',
            })
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || 'Error', 'error')
        }
    }

    const handleProcess = async (id) => {
        if (!confirm(t('accounting.confirm_process'))) return
        try {
            await accountingAPI.processIntercompanyTransaction(id)
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || 'Error', 'error')
        }
    }

    const getStatusBadge = (status) => {
        const map = { pending: 'badge-warning', processed: 'badge-success', eliminated: 'badge-info' }
        return map[status] || 'badge-secondary'
    }

    if (loading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('accounting.intercompany')}</h1>
                    <p className="workspace-subtitle">{t('accounting.intercompany_desc')}</p>
                </div>
            </div>

            {/* Tabs + Actions */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div className="tabs">
                    <button className={`tab ${tab === 'list' ? 'active' : ''}`} onClick={() => setTab('list')}>
                        {t('accounting.ic_transactions')}
                    </button>
                    <button className={`tab ${tab === 'elimination' ? 'active' : ''}`} onClick={fetchElimination}>
                        {t('accounting.elimination_report')}
                    </button>
                </div>
                <button className="btn btn-primary btn-sm" onClick={() => setShowForm(!showForm)}>
                    {showForm ? t('common.cancel') : t('accounting.add_ic_transaction')}
                </button>
            </div>

            {/* Create Form */}
            {showForm && (
                <div className="section-card" style={{ marginBottom: 16 }}>
                    <h3 className="section-title">{t('accounting.new_ic_transaction')}</h3>

                    {/* Source entity info */}
                    <div style={{
                        padding: '8px 12px', background: '#f0fdf4', border: '1px solid #bbf7d0',
                        borderRadius: '6px', marginBottom: 12, fontSize: '13px', color: '#166534'
                    }}>
                        <strong>الكيان المصدر:</strong> {sourceEntity?.name || currentBranch?.branch_name || 'غير محدد'} ({sourceCurrency})
                        {'  '}→{'  '}
                        <strong>الكيان الهدف:</strong> {targetEntity?.name || 'غير محدد'} ({targetCurrency})
                    </div>

                    <form onSubmit={handleSubmit}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.source_entity', 'الكيان المصدر')} *</label>
                                <select className="form-input" required value={form.source_entity_id}
                                    onChange={e => setForm({ ...form, source_entity_id: e.target.value })}>
                                    <option value="">اختر الكيان المصدر</option>
                                    {entities.filter(e => String(e.id) !== String(form.target_entity_id)).map(entity => (
                                        <option key={entity.id} value={entity.id}>
                                            {entity.name} ({normalizeCurrencyCode(entity.group_currency, currentBranch?.default_currency || currency)})
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.target_entity', 'الكيان الهدف')} *</label>
                                <select className="form-input" required value={form.target_entity_id}
                                    onChange={e => setForm({ ...form, target_entity_id: e.target.value })}>
                                    <option value="">اختر الكيان الهدف</option>
                                    {entities.filter(e => String(e.id) !== String(form.source_entity_id)).map(entity => (
                                        <option key={entity.id} value={entity.id}>
                                            {entity.name} ({normalizeCurrencyCode(entity.group_currency, sourceCurrency)})
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.transaction_type', 'النوع')}</label>
                                <select className="form-input" value={form.transaction_type}
                                    onChange={e => setForm({ ...form, transaction_type: e.target.value })}>
                                    <option value="sale">{t('accounting.ic_sale', 'بيع')}</option>
                                    <option value="purchase">{t('accounting.ic_purchase', 'شراء')}</option>
                                    <option value="service">{t('accounting.ic_service', 'خدمة')}</option>
                                    <option value="transfer">{t('accounting.ic_transfer', 'تحويل')}</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.transaction_currency', 'عملة المعاملة')} *</label>
                                <select className="form-input" required value={form.transaction_currency}
                                    onChange={e => setForm({ ...form, transaction_currency: e.target.value })}>
                                    {currencies.length === 0 && <option value={currency}>{currency}</option>}
                                    {currencies.map(c => (
                                        <option key={c.code} value={c.code}>
                                            {c.code} — {c.name || c.name_en || c.code}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.transaction_amount', 'مبلغ المعاملة')} *</label>
                                <input className="form-input" type="number" step="0.0001" min="0.0001" required value={form.amount}
                                    onChange={e => setForm({ ...form, amount: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.source_currency', 'عملة المصدر الوظيفية')}</label>
                                <input className="form-input" value={sourceCurrency} readOnly />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.source_rate', 'معدّل المصدر')}</label>
                                <input className="form-input" type="number" step="0.00000001" value={form.source_rate} readOnly />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.source_func_amount', 'القيمة بدفاتر المصدر')}</label>
                                <input className="form-input" type="number" step="0.0001" value={form.amount ? sourceFuncAmount.toFixed(4) : ''} readOnly />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.target_currency', 'عملة الهدف الوظيفية')}</label>
                                <input className="form-input" value={targetCurrency} readOnly />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.target_rate', 'معدّل الهدف')}</label>
                                <input className="form-input" type="number" step="0.00000001" value={form.target_rate} readOnly />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('intercompany.target_func_amount', 'القيمة بدفاتر الهدف')}</label>
                                <input className="form-input" type="number" step="0.0001" value={form.amount ? targetFuncAmount.toFixed(4) : ''} readOnly />
                            </div>
                            <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                <label className="form-label">{t('common.description')} *</label>
                                <input className="form-input" required value={form.description}
                                    onChange={e => setForm({ ...form, description: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.reference', 'المرجع')}</label>
                                <input className="form-input" value={form.reference}
                                    onChange={e => setForm({ ...form, reference: e.target.value })}
                                    placeholder={t('accounting.auto_generated')} />
                            </div>
                        </div>
                        <div style={{ marginTop: 12 }}>
                            <button type="submit" className="btn btn-primary btn-sm">{t('common.save')}</button>
                        </div>
                    </form>
                </div>
            )}

            {/* Transactions List */}
            {tab === 'list' && (
                <div className="section-card">
                    <h3 className="section-title">{t('accounting.ic_transactions', 'المعاملات')} ({transactions.length})</h3>
                    {transactions.length === 0 ? (
                        <p style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>
                            {t('common.no_data')}
                        </p>
                    ) : (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>المرجع</th>
                                        <th>الكيانات</th>
                                        <th>النوع</th>
                                        <th>مبلغ المصدر</th>
                                        <th>مبلغ الهدف</th>
                                        <th>الحالة</th>
                                        <th>التاريخ</th>
                                        <th>الإجراءات</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {transactions.map(tx => (
                                        <tr key={tx.id}>
                                            <td>{tx.id}</td>
                                            <td style={{ fontWeight: 600 }}>{tx.reference_document}</td>
                                            <td>{tx.source_entity_name} → {tx.target_entity_name}</td>
                                            <td>
                                                <span className="badge badge-info">
                                                    {t(`accounting.ic_${tx.transaction_type}`, tx.transaction_type)}
                                                </span>
                                            </td>
                                            <td>{formatNumber(tx.source_amount)} {tx.source_currency}</td>
                                            <td>{formatNumber(tx.target_amount)} {tx.target_currency}</td>
                                            <td>
                                                <span className={`badge ${getStatusBadge(tx.elimination_status)}`}>
                                                    {tx.elimination_status === 'pending' ? 'معلّقة' :
                                                     tx.elimination_status === 'processed' ? 'معالجة' :
                                                     tx.elimination_status === 'eliminated' ? 'مُستبعدة' : tx.elimination_status}
                                                </span>
                                            </td>
                                            <td style={{ color: '#9ca3af', fontSize: '0.85rem' }}>
                                                {tx.created_at ? new Date(tx.created_at).toLocaleDateString('ar-SA') : '—'}
                                            </td>
                                            <td>
                                                {tx.elimination_status === 'pending' && (
                                                    <button className="btn btn-success btn-sm" onClick={() => handleProcess(tx.id)}>
                                                        {t('accounting.process')}
                                                    </button>
                                                )}
                                                {tx.elimination_status === 'processed' && (
                                                    <span style={{ color: '#22c55e', fontSize: '0.85rem' }}>✓ معالجة</span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {/* Elimination Report */}
            {tab === 'elimination' && eliminationReport && (
                <>
                    {/* Totals */}
                    <div className="metrics-grid" style={{ marginBottom: 16 }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('accounting.total_intercompany')}</div>
                            <div className="metric-value text-primary">{formatNumber(eliminationReport.totals?.total_intercompany || 0)} <small>{currency}</small></div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('accounting.total_eliminated')}</div>
                            <div className="metric-value text-success">{formatNumber(eliminationReport.totals?.total_eliminated || 0)} <small>{currency}</small></div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('accounting.pending_elimination')}</div>
                            <div className="metric-value text-warning">{formatNumber(eliminationReport.totals?.pending_elimination || 0)} <small>{currency}</small></div>
                        </div>
                    </div>

                    {/* By Company */}
                    <div className="section-card">
                        <h3 className="section-title">{t('accounting.elimination_by_company')}</h3>
                        {eliminationReport.by_company?.length === 0 ? (
                            <p style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>{t('common.no_data', 'لا توجد بيانات')}</p>
                        ) : (
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('accounting.target_company')}</th>
                                            <th>{t('accounting.transaction_type')}</th>
                                            <th>{t('common.count')}</th>
                                            <th>{t('accounting.total_amount')}</th>
                                            <th>{t('accounting.processed_amount')}</th>
                                            <th>{t('accounting.pending_amount')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {eliminationReport.by_company.map((row, i) => (
                                            <tr key={i}>
                                                <td style={{ fontWeight: 600 }}>{row.target_company_id}</td>
                                                <td><span className="badge badge-info">{row.transaction_type}</span></td>
                                                <td>{row.txn_count}</td>
                                                <td>{formatNumber(row.total_amount)} {currency}</td>
                                                <td style={{ color: '#22c55e' }}>{formatNumber(row.processed_amount || 0)} {currency}</td>
                                                <td style={{ color: '#f97316' }}>{formatNumber(row.pending_amount || 0)} {currency}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}

export default IntercompanyTransactions
