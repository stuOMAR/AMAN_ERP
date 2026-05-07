import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { accountingAPI, currenciesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { calculateCrossExchangeRate, fetchCrossExchangeRate } from '../../hooks/useExchangeRate'
import BackButton from '../../components/common/BackButton'
import FormField from '../../components/common/FormField'
import { useToast } from '../../context/ToastContext'

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

function TransactionForm() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const companyCurrency = normalizeCurrencyCode(getCurrency(), 'SAR')
    const [entities, setEntities] = useState([])
    const [currencies, setCurrencies] = useState([])
    const [currencyRates, setCurrencyRates] = useState({})
    const [loading, setLoading] = useState(false)
    const [form, setForm] = useState({
        source_entity_id: '',
        target_entity_id: '',
        transaction_type: 'sale',
        // The actual money currency + amount being moved.
        transaction_currency: companyCurrency,
        transaction_amount: '',
        // Functional currencies of each branch (read-only, derived from
        // entity.group_currency).
        source_currency: companyCurrency,
        target_currency: companyCurrency,
        // Cross rates: txn → each functional currency.
        source_rate: '1',
        target_rate: '1',
        reference_document: '',
    })

    useEffect(() => {
        let cancelled = false
        accountingAPI.listEntityGroups()
            .then(res => { if (!cancelled) setEntities(Array.isArray(res.data) ? res.data : []) })
            .catch(() => {})
        currenciesAPI.list()
            .then(res => {
                if (cancelled) return
                const list = Array.isArray(res.data) ? res.data : []
                setCurrencies(list)
                setCurrencyRates(buildCurrencyRateMap(list))
            })
            .catch(() => {})
        return () => { cancelled = true }
    }, [])

    const sourceEntity = useMemo(
        () => entities.find(ent => String(ent.id) === String(form.source_entity_id)),
        [entities, form.source_entity_id],
    )
    const targetEntity = useMemo(
        () => entities.find(ent => String(ent.id) === String(form.target_entity_id)),
        [entities, form.target_entity_id],
    )

    // 1) Sync each branch's functional currency from its entity record.
    useEffect(() => {
        const nextSource = normalizeCurrencyCode(sourceEntity?.group_currency, companyCurrency)
        const nextTarget = normalizeCurrencyCode(targetEntity?.group_currency, nextSource)
        setForm(prev => {
            const patch = {}
            if (sourceEntity && prev.source_currency !== nextSource) patch.source_currency = nextSource
            if (targetEntity && prev.target_currency !== nextTarget) patch.target_currency = nextTarget
            return Object.keys(patch).length ? { ...prev, ...patch } : prev
        })
    }, [sourceEntity, targetEntity, companyCurrency])

    // 2) Recompute cross rates whenever the txn currency or either functional
    //    currency changes. Local map first (instant), then refine via API.
    useEffect(() => {
        const txn = normalizeCurrencyCode(form.transaction_currency, companyCurrency)
        const srcF = normalizeCurrencyCode(form.source_currency, txn)
        const tgtF = normalizeCurrencyCode(form.target_currency, txn)

        const localSrc = calculateCrossExchangeRate(currencyRates[txn], currencyRates[srcF])
        const localTgt = calculateCrossExchangeRate(currencyRates[txn], currencyRates[tgtF])
        if (Object.keys(currencyRates).length > 0) {
            setForm(prev => ({
                ...prev,
                source_rate: formatRateForInput(localSrc),
                target_rate: formatRateForInput(localTgt),
            }))
        }

        let cancelled = false
        Promise.all([
            fetchCrossExchangeRate(txn, srcF),
            fetchCrossExchangeRate(txn, tgtF),
        ]).then(([srcRate, tgtRate]) => {
            if (cancelled) return
            setForm(prev => ({
                ...prev,
                source_rate: formatRateForInput(srcRate),
                target_rate: formatRateForInput(tgtRate),
            }))
        }).catch(() => {})
        return () => { cancelled = true }
    }, [form.transaction_currency, form.source_currency, form.target_currency, currencyRates, companyCurrency])

    const sourceFuncAmount = calculateConvertedAmount(form.transaction_amount, form.source_rate)
    const targetFuncAmount = calculateConvertedAmount(form.transaction_amount, form.target_rate)

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (form.source_entity_id === form.target_entity_id) {
            showToast(t('intercompany.same_entity_error'), 'error')
            return
        }
        if (!sourceEntity || !targetEntity) {
            showToast(t('intercompany.entity_required', 'اختر الكيان المصدر والكيان الهدف'), 'error')
            return
        }
        const txnAmount = Number(form.transaction_amount)
        if (!Number.isFinite(txnAmount) || txnAmount <= 0) {
            showToast(t('intercompany.invalid_amount_or_rate', 'تحقق من المبلغ وسعر الصرف'), 'error')
            return
        }
        const srcRate = Number(form.source_rate)
        const tgtRate = Number(form.target_rate)
        if (!Number.isFinite(srcRate) || srcRate <= 0 || !Number.isFinite(tgtRate) || tgtRate <= 0) {
            showToast(t('intercompany.invalid_amount_or_rate', 'تحقق من المبلغ وسعر الصرف'), 'error')
            return
        }
        const txnCurrency = normalizeCurrencyCode(form.transaction_currency, companyCurrency)
        const srcCurrency = normalizeCurrencyCode(form.source_currency, txnCurrency)
        const tgtCurrency = normalizeCurrencyCode(form.target_currency, txnCurrency)
        const crossRate = targetFuncAmount > 0 ? Number((sourceFuncAmount / targetFuncAmount).toFixed(8)) : 1
        try {
            setLoading(true)
            await accountingAPI.createICTransactionV2({
                source_entity_id: parseInt(form.source_entity_id, 10),
                target_entity_id: parseInt(form.target_entity_id, 10),
                transaction_type: form.transaction_type,
                // Source booking values (in source functional currency)
                source_amount: sourceFuncAmount,
                source_currency: srcCurrency,
                // Target booking values (in target functional currency)
                target_amount: targetFuncAmount,
                target_currency: tgtCurrency,
                // The actual money moved
                transaction_currency: txnCurrency,
                transaction_amount: txnAmount,
                exchange_rate: crossRate || 1,
                reference_document: form.reference_document,
            })
            showToast(t('intercompany.transaction_created'), 'success')
            navigate('/accounting/intercompany/transactions')
        } catch (e) {
            showToast(e.response?.data?.detail || t('intercompany.create_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const updateField = (field, value) => setForm(prev => ({ ...prev, [field]: value }))

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('intercompany.new_transaction')}</h1>
            </div>

            <form onSubmit={handleSubmit} className="card" style={{ padding: 16 }}>
                <div className="form-row">
                    <FormField label={t('intercompany.source_entity')} required>
                        <select className="form-input" required value={form.source_entity_id}
                            onChange={e => updateField('source_entity_id', e.target.value)}>
                            <option value="">{t('common.select')}</option>
                            {entities.filter(ent => String(ent.id) !== String(form.target_entity_id)).map(ent => (
                                <option key={ent.id} value={ent.id}>
                                    {ent.name} ({normalizeCurrencyCode(ent.group_currency, companyCurrency)})
                                </option>
                            ))}
                        </select>
                    </FormField>
                    <FormField label={t('intercompany.target_entity')} required>
                        <select className="form-input" required value={form.target_entity_id}
                            onChange={e => updateField('target_entity_id', e.target.value)}>
                            <option value="">{t('common.select')}</option>
                            {entities.filter(ent => String(ent.id) !== String(form.source_entity_id)).map(ent => (
                                <option key={ent.id} value={ent.id}>
                                    {ent.name} ({normalizeCurrencyCode(ent.group_currency, companyCurrency)})
                                </option>
                            ))}
                        </select>
                    </FormField>
                </div>

                <div className="form-row">
                    <FormField label={t('intercompany.type')}>
                        <select className="form-input" value={form.transaction_type}
                            onChange={e => updateField('transaction_type', e.target.value)}>
                            <option value="sale">{t('intercompany.type_sale')}</option>
                            <option value="purchase">{t('intercompany.type_purchase')}</option>
                            <option value="service">{t('intercompany.type_service')}</option>
                            <option value="loan">{t('intercompany.type_loan')}</option>
                            <option value="transfer">{t('intercompany.type_transfer')}</option>
                        </select>
                    </FormField>
                    <FormField label={t('intercompany.transaction_currency', 'عملة المعاملة')} required>
                        <select className="form-input" required value={form.transaction_currency}
                            onChange={e => updateField('transaction_currency', e.target.value)}>
                            {currencies.length === 0 && (
                                <option value={companyCurrency}>{companyCurrency}</option>
                            )}
                            {currencies.map(c => (
                                <option key={c.code} value={c.code}>
                                    {c.code} — {c.name || c.name_en || c.code}
                                </option>
                            ))}
                        </select>
                    </FormField>
                    <FormField label={t('intercompany.transaction_amount', 'مبلغ المعاملة')} required>
                        <input className="form-input" type="number" step="0.0001" min="0.0001" required
                            value={form.transaction_amount}
                            onChange={e => updateField('transaction_amount', e.target.value)} />
                    </FormField>
                </div>

                <div className="form-row">
                    <FormField label={t('intercompany.source_currency', 'العملة الوظيفية للمصدر')}>
                        <input className="form-input" type="text" value={form.source_currency} readOnly />
                    </FormField>
                    <FormField label={t('intercompany.source_rate', 'سعر الصرف (المعاملة → المصدر)')}>
                        <input className="form-input" type="number" step="0.00000001" value={form.source_rate} readOnly />
                    </FormField>
                    <FormField label={t('intercompany.source_func_amount', 'القيمة بدفاتر المصدر')}>
                        <input className="form-input" type="number" step="0.0001"
                            value={form.transaction_amount ? sourceFuncAmount.toFixed(4) : ''} readOnly />
                    </FormField>
                </div>

                <div className="form-row">
                    <FormField label={t('intercompany.target_currency', 'العملة الوظيفية للهدف')}>
                        <input className="form-input" type="text" value={form.target_currency} readOnly />
                    </FormField>
                    <FormField label={t('intercompany.target_rate', 'سعر الصرف (المعاملة → الهدف)')}>
                        <input className="form-input" type="number" step="0.00000001" value={form.target_rate} readOnly />
                    </FormField>
                    <FormField label={t('intercompany.target_func_amount', 'القيمة بدفاتر الهدف')}>
                        <input className="form-input" type="number" step="0.0001"
                            value={form.transaction_amount ? targetFuncAmount.toFixed(4) : ''} readOnly />
                    </FormField>
                </div>

                <div className="form-row">
                    <FormField label={t('intercompany.reference')} style={{ flex: 1 }}>
                        <input className="form-input" type="text" value={form.reference_document}
                            onChange={e => updateField('reference_document', e.target.value)} />
                    </FormField>
                </div>

                <div style={{ marginTop: 16 }}>
                    <button type="submit" className="btn btn-success" disabled={loading}>
                        {loading ? t('common.saving') : t('intercompany.create_transaction')}
                    </button>
                    <button type="button" className="btn btn-secondary" style={{ marginInlineEnd: 8 }}
                        onClick={() => navigate('/accounting/intercompany/transactions')}>
                        {t('common.cancel')}
                    </button>
                </div>
            </form>
        </div>
    )
}

export default TransactionForm
