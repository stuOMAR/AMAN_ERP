import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { treasuryAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { toastEmitter } from '../../utils/toastEmitter'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';

function TransferForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency() || ''

    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [accounts, setAccounts] = useState([])
    const [error, setError] = useState(null)

    const [form, setForm] = useState({
        transaction_date: new Date().toISOString().split('T')[0],
        amount: '',
        treasury_id: '',
        target_treasury_id: '',
        notes: '',
        reference_number: '',
        exchange_rate: '1'
    })

    useEffect(() => {
        const fetchAccounts = async () => {
            try {
                const branchId = currentBranch?.id || null
                const res = await treasuryAPI.listAccounts(branchId)
                setAccounts(res.data)
            } catch (err) {
                console.error("Failed to fetch accounts", err)
            } finally {
                setInitialLoad(false)
            }
        }
        const timer = setTimeout(() => {
            fetchAccounts()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (form.treasury_id && form.target_treasury_id && form.treasury_id === form.target_treasury_id) {
            setError(t('treasury.error_same_account'))
            return
        }
        setLoading(true)
        setError(null)
        try {
            await treasuryAPI.createTransfer({
                transaction_date: form.transaction_date,
                transaction_type: 'transfer',
                amount: form.amount,
                treasury_id: form.treasury_id ? parseInt(form.treasury_id, 10) : null,
                target_treasury_id: form.target_treasury_id ? parseInt(form.target_treasury_id, 10) : null,
                branch_id: currentBranch?.id || null,
                description: form.notes || form.reference_number || t('treasury.menu.transfer'),
                reference_number: form.reference_number || null,
                exchange_rate: form.exchange_rate || '1'
            })
            toastEmitter.emit(t('treasury.success_create_transfer'), 'success')
            navigate('/treasury')
        } catch (err) {
            const errorData = err.response?.data?.detail
            if (Array.isArray(errorData)) {
                setError(errorData.map(e => `${e.loc.join('.')}: ${e.msg}`).join(', '))
            } else if (typeof errorData === 'object') {
                setError(JSON.stringify(errorData))
            } else {
                setError(errorData || t('common.error_occurred'))
            }
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('treasury.menu.transfer')}</h1>
                <p className="workspace-subtitle">{t('treasury.subtitle')}</p>
            </div>

            {error && <div className="alert alert-danger mb-4">{error}</div>}

            <form onSubmit={handleSubmit}>
                <div className="card mb-4 p-4">
                    <h3 className="section-title">{t('common.details')}</h3>
                    <div className="form-row">
                        <div className="form-group" style={{ flex: 1 }}>
                            <CustomDatePicker
                                label={t('common.date')}
                                selected={form.transaction_date}
                                onChange={dateStr => setForm({ ...form, transaction_date: dateStr })}
                                required
                            />
                        </div>
                        <FormField label={t('common.amount')} required style={{ flex: 1 }}>
                            <div className="input-group">
                                <span className="input-group-text">
                                    {currency}
                                </span>
                                <input
                                    type="number"
                                    required
                                    className="form-input"
                                    placeholder="0.00"
                                    value={form.amount}
                                    onChange={e => setForm({ ...form, amount: e.target.value })}
                                />
                            </div>
                        </FormField>
                        <FormField label={t('common.exchange_rate', 'سعر الصرف')} style={{ flex: 1 }}>
                            <input
                                type="number"
                                className="form-input"
                                step="0.000001"
                                min="0"
                                value={form.exchange_rate}
                                onChange={e => setForm({ ...form, exchange_rate: e.target.value || '1' })}
                            />
                        </FormField>
                    </div>

                    <div className="form-row">
                        <FormField label={t('treasury.transfer_from')} required style={{ flex: 1 }}>
                            <select
                                required
                                className="form-input"
                                value={form.treasury_id}
                                onChange={e => setForm({ ...form, treasury_id: e.target.value })}
                            >
                                <option value="">{t('common.select')}</option>
                                {accounts.map(a => (
                                    <option key={a.id} value={a.id}>
                                        {a.name}
                                    </option>
                                ))}
                            </select>
                            {form.treasury_id && (
                                <div className="mt-2 text-sm">
                                    <span className="text-secondary">{t('treasury.available_balance')}: </span>
                                    <span className="fw-bold text-success">
                                        {formatNumber(accounts.find(a => a.id.toString() === form.treasury_id.toString())?.current_balance)} {currency}
                                    </span>
                                </div>
                            )}
                        </FormField>
                        <FormField label={t('treasury.transfer_to')} required style={{ flex: 1 }}>
                            <select
                                required
                                className="form-input"
                                value={form.target_treasury_id}
                                onChange={e => setForm({ ...form, target_treasury_id: e.target.value })}
                            >
                                <option value="">{t('common.select')}</option>
                                {accounts.filter(a => a.id.toString() !== form.treasury_id).map(a => (
                                    <option key={a.id} value={a.id}>
                                        {a.name}
                                    </option>
                                ))}
                            </select>
                            {form.target_treasury_id && (
                                <div className="mt-2 text-sm">
                                    <span className="text-secondary">{t('treasury.available_balance')}: </span>
                                    <span className="fw-bold text-success">
                                        {formatNumber(accounts.find(a => a.id.toString() === form.target_treasury_id.toString())?.current_balance)} {currency}
                                    </span>
                                </div>
                            )}
                        </FormField>
                    </div>

                    <FormField label={t('common.reference')} className="mt-3">
                        <input
                            type="text"
                            className="form-input"
                            placeholder={t('common.reference_placeholder')}
                            value={form.reference_number}
                            onChange={e => setForm({ ...form, reference_number: e.target.value })}
                        />
                    </FormField>

                    <FormField label={t('common.notes')} className="mt-3">
                        <textarea
                            className="form-input"
                            rows="3"
                            value={form.notes}
                            onChange={e => setForm({ ...form, notes: e.target.value })}
                        ></textarea>
                    </FormField>

                    <div style={{ display: 'flex', gap: '12px', marginTop: '24px', justifyContent: 'flex-end' }}>
                        <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={() => navigate('/treasury')}
                        >
                            {t('common.cancel')}
                        </button>
                        <button
                            type="submit"
                            className="btn btn-primary"
                            disabled={loading}
                        >
                            {loading ? t('common.saving') : t('common.save')}
                        </button>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default TransferForm
