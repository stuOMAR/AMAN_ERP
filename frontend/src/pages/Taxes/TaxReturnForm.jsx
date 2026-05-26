import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { taxesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { useBranch } from '../../context/BranchContext'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';

function makeIdempotencyKey(prefix) {
    if (window.crypto?.randomUUID) return `${prefix}:${window.crypto.randomUUID()}`
    return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`
}

function isNegativeAmount(value) {
    return String(value || '0').trim().startsWith('-')
}

function absoluteAmount(value) {
    const text = String(value || '0.00').trim()
    return text.startsWith('-') ? text.slice(1) : text
}

function TaxReturnForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [success, setSuccess] = useState(null)

    const now = new Date()
    const currentYear = now.getFullYear()
    const currentMonth = now.getMonth() + 1

    const [form, setForm] = useState({
        period_type: 'monthly', // monthly or quarterly
        year: currentYear,
        month: currentMonth,
        quarter: Math.ceil(currentMonth / 3),
        tax_type: 'vat',
        due_date: '',
        notes: ''
    })

    const getPeriodString = () => {
        if (form.period_type === 'quarterly') {
            return `${form.year}-Q${form.quarter}`
        }
        return `${form.year}-${String(form.month).padStart(2, '0')}`
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError(null)
        setSuccess(null)
        setLoading(true)

        try {
            const payload = {
                tax_period: getPeriodString(),
                tax_type: form.tax_type,
                due_date: form.due_date || null,
                notes: form.notes || null,
                branch_id: currentBranch?.id || null
            }
            const preview = await taxesAPI.previewReturn(payload)
            const submittedTaxDue = preview.data?.submitted_tax_due || preview.data?.summary?.net_payable
            if (submittedTaxDue == null) {
                throw new Error('submitted_tax_due_missing')
            }
            const idempotencyKey = makeIdempotencyKey(`tax-return:${payload.tax_period}`)
            const res = await taxesAPI.createReturn({
                ...payload,
                submitted_tax_due: String(submittedTaxDue)
            }, idempotencyKey)
            setSuccess(res.data)
        } catch (err) {
            setError(err.response?.data?.detail || t('errors.generic'))
        } finally {
            setLoading(false)
        }
    }

    const months = [
        { value: 1, label: t('months.jan') },
        { value: 2, label: t('months.feb') },
        { value: 3, label: t('months.mar') },
        { value: 4, label: t('months.apr') },
        { value: 5, label: t('months.may') },
        { value: 6, label: t('months.jun') },
        { value: 7, label: t('months.jul') },
        { value: 8, label: t('months.aug') },
        { value: 9, label: t('months.sep') },
        { value: 10, label: t('months.oct') },
        { value: 11, label: t('months.nov') },
        { value: 12, label: t('months.dec') }
    ]

    const quarters = [
        { value: 1, label: t('taxes.q1') },
        { value: 2, label: t('taxes.q2') },
        { value: 3, label: t('taxes.q3') },
        { value: 4, label: t('taxes.q4') }
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📝 {t('taxes.new_return_title')}</h1>
                    <p className="workspace-subtitle">{t('taxes.new_return_subtitle')}</p>
                </div>
            </div>

            {error && <div className="alert alert-danger mt-4">{error}</div>}

            {success ? (
                <div className="card mt-4">
                    <div style={{ textAlign: 'center', padding: '40px 20px' }}>
                        <div style={{ fontSize: '48px', marginBottom: '16px' }}>✅</div>
                        <h2 style={{ color: 'var(--success)' }}>{t('taxes.return_created')}</h2>
                        <p style={{ fontFamily: 'monospace', fontSize: '18px', margin: '8px 0' }}>{success.return_number}</p>

                        {success.summary && (
                            <div className="metrics-grid mt-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', maxWidth: '800px', margin: '24px auto' }}>
                                <div className="metric-card">
                                    <div className="metric-label">{t('taxes.output_vat')}</div>
                                    <div className="metric-value text-secondary">{formatNumber(success.summary.output_vat || '0.00')}</div>
                                </div>
                                <div className="metric-card">
                                    <div className="metric-label">{t('taxes.input_vat')}</div>
                                    <div className="metric-value text-primary">{formatNumber(success.summary.input_vat || '0.00')}</div>
                                </div>
                                <div className="metric-card">
                                    <div className="metric-label">{t('taxes.net_payable')}</div>
                                    <div className={`metric-value ${isNegativeAmount(success.summary.net_payable) ? 'text-success' : 'text-error'}`}>
                                        {formatNumber(absoluteAmount(success.summary.net_payable || '0.00'))} {currency}
                                    </div>
                                    <div className="metric-change">
                                        {isNegativeAmount(success.summary.net_payable) ? (t('taxes.refundable')) : (t('taxes.payable'))}
                                    </div>
                                </div>
                            </div>
                        )}

                        <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '24px' }}>
                            <button className="btn btn-primary" onClick={() => navigate(`/taxes/returns/${success.id}`)}>
                                👁️ {t('taxes.view_return')}
                            </button>
                            <button className="btn btn-secondary" onClick={() => navigate('/taxes')}>
                                🏠 {t('taxes.back_to_taxes')}
                            </button>
                        </div>
                    </div>
                </div>
            ) : (
                <form onSubmit={handleSubmit}>
                    {/* Period Settings Card */}
                    <div className="card mt-4">
                        <div >
                            <div className="d-flex align-items-center gap-2 mb-3">
                                <div style={{ background: '#eff6ff', width: '32px', height: '32px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <span style={{ fontSize: '18px' }}>📅</span>
                                </div>
                                <h5 className="mb-0 fw-semibold">{t('taxes.period_settings')}</h5>
                            </div>

                            <div className="form-row">
                                <FormField label={t('taxes.period_type')} required style={{ flex: 1 }}>
                                    <select className="form-input" value={form.period_type}
                                        onChange={e => setForm({...form, period_type: e.target.value})}>
                                        <option value="monthly">{t('taxes.monthly')}</option>
                                        <option value="quarterly">{t('taxes.quarterly')}</option>
                                    </select>
                                </FormField>

                                <FormField label={t('taxes.year')} required style={{ flex: 1 }}>
                                    <select className="form-input" value={form.year}
                                        onChange={e => setForm({...form, year: parseInt(e.target.value)})}>
                                        {[currentYear - 2, currentYear - 1, currentYear, currentYear + 1].map(y => (
                                            <option key={y} value={y}>{y}</option>
                                        ))}
                                    </select>
                                </FormField>
                            </div>

                            <div className="form-row">
                                {form.period_type === 'monthly' ? (
                                    <FormField label={t('taxes.month')} required style={{ flex: 1 }}>
                                        <select className="form-input" value={form.month}
                                            onChange={e => setForm({...form, month: parseInt(e.target.value)})}>
                                            {months.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                                        </select>
                                    </FormField>
                                ) : (
                                    <FormField label={t('taxes.quarter')} required style={{ flex: 1 }}>
                                        <select className="form-input" value={form.quarter}
                                            onChange={e => setForm({...form, quarter: parseInt(e.target.value)})}>
                                            {quarters.map(q => <option key={q.value} value={q.value}>{q.label}</option>)}
                                        </select>
                                    </FormField>
                                )}

                                <FormField label={t('taxes.tax_type')} style={{ flex: 1 }}>
                                    <select className="form-input" value={form.tax_type}
                                        onChange={e => setForm({...form, tax_type: e.target.value})}>
                                        <option value="vat">{t('taxes.vat')}</option>
                                        <option value="income">{t('taxes.income_tax')}</option>
                                        <option value="withholding">{t('taxes.withholding')}</option>
                                    </select>
                                </FormField>
                            </div>

                            <div className="form-row">
                                <div className="form-group" style={{ flex: 1 }}>
                                    <CustomDatePicker
                                        label={t('taxes.due_date')}
                                        selected={form.due_date}
                                        onChange={(val) => setForm({...form, due_date: val})}
                                        placeholder="YYYY/MM/DD"
                                    />
                                </div>
                                <FormField label={t('taxes.selected_period')} style={{ flex: 1 }}>
                                    <input className="form-input" value={getPeriodString()} readOnly
                                        style={{ fontFamily: 'monospace', fontWeight: 'bold', background: 'var(--bg-secondary)' }} />
                                </FormField>
                            </div>

                            <FormField label={t('taxes.notes')}>
                                <textarea className="form-input" rows="3" value={form.notes}
                                    onChange={e => setForm({...form, notes: e.target.value})}
                                    placeholder={t('taxes.notes_placeholder')} />
                            </FormField>

                            <div className="alert alert-info mt-3">
                                ℹ️ {t('taxes.auto_calc_note')}
                            </div>

                            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '16px' }}>
                                <button type="button" className="btn btn-outline-secondary" onClick={() => navigate('/taxes')}>
                                    {t('common.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={loading}>
                                    {loading ? (t('common.creating')) : (t('taxes.create_return'))}
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
            )}
        </div>
    )
}

export default TaxReturnForm
