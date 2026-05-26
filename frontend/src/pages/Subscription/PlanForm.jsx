import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { subscriptionsAPI } from '../../services/subscriptions'
import { useTranslation } from 'react-i18next'
import BackButton from '../../components/common/BackButton'
import FormField from '../../components/common/FormField'
import { getCurrency } from '../../utils/auth'

function PlanForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { id } = useParams()
    const isEdit = Boolean(id)

    const [formData, setFormData] = useState({
        name: '',
        description: '',
        billing_frequency: 'monthly',
        base_amount: '',
        currency: getCurrency(),
        trial_period_days: 0,
        auto_renewal: true,
        is_active: true,
    })
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    useEffect(() => {
        if (isEdit) {
            const fetchPlan = async () => {
                try {
                    const response = await subscriptionsAPI.listPlans()
                    const plans = response.data?.items || response.data || []
                    const plan = plans.find(p => p.id === parseInt(id))
                    if (plan) {
                        setFormData({
                            name: plan.name || '',
                            description: plan.description || '',
                            billing_frequency: plan.billing_frequency || 'monthly',
                            base_amount: plan.base_amount || '',
                            currency: plan.currency || getCurrency(),
                            trial_period_days: plan.trial_period_days || 0,
                            auto_renewal: plan.auto_renewal ?? true,
                            is_active: plan.is_active ?? true,
                        })
                    }
                } catch (err) {
                    setError(t('common.error_loading'))
                    console.error(err)
                }
            }
            fetchPlan()
        }
    }, [id, isEdit, t])

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target
        setFormData(prev => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value,
        }))
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!formData.name || !formData.base_amount) {
            setError(t('common.required_field'))
            return
        }

        setLoading(true)
        setError('')
        try {
            const data = {
                ...formData,
                base_amount: formData.base_amount,
                trial_period_days: parseInt(formData.trial_period_days) || 0,
            }
            if (isEdit) {
                await subscriptionsAPI.updatePlan(id, data)
            } else {
                await subscriptionsAPI.createPlan(data)
            }
            navigate('/finance/subscriptions/plans')
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_saving'))
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        {isEdit ? t('subscription.edit_plan') : t('subscription.new_plan')}
                    </h1>
                    <p className="workspace-subtitle">{t('subscription.plans_subtitle')}</p>
                </div>
            </div>

            <div className="card" style={{ maxWidth: '900px', margin: '0 auto', padding: '32px', boxShadow: 'var(--shadow-lg)' }}>
                {error && <div className="alert alert-error mb-4">{error}</div>}

                <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div className="form-section card">
                        <h3 className="section-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--primary)' }}>
                            <span style={{ fontSize: '24px' }}>📋</span> {t('subscription.form.basic_info')}
                        </h3>
                        <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                            <FormField label={t('subscription.form.name')} required style={{ marginBottom: 0 }}>
                                <input
                                    type="text" name="name" className="form-input" required
                                    value={formData.name} onChange={handleChange}
                                />
                            </FormField>
                            <FormField label={t('subscription.form.currency')} style={{ marginBottom: 0 }}>
                                <input
                                    type="text" name="currency" className="form-input"
                                    value={formData.currency} onChange={handleChange} maxLength={3}
                                />
                            </FormField>
                        </div>
                        <div style={{ marginTop: '24px' }}>
                            <FormField label={t('subscription.form.description')} style={{ marginBottom: 0 }}>
                                <textarea
                                    name="description" className="form-input"
                                    value={formData.description} onChange={handleChange} rows={3}
                                />
                            </FormField>
                        </div>
                    </div>

                    <div className="form-section card">
                        <h3 className="section-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--primary)' }}>
                            <span style={{ fontSize: '24px' }}>💰</span> {t('subscription.form.billing_info')}
                        </h3>
                        <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '24px' }}>
                            <FormField label={t('subscription.form.billing_frequency')} style={{ marginBottom: 0 }}>
                                <select name="billing_frequency" className="form-input" value={formData.billing_frequency} onChange={handleChange}>
                                    <option value="monthly">{t('subscription.frequency.monthly')}</option>
                                    <option value="quarterly">{t('subscription.frequency.quarterly')}</option>
                                    <option value="annual">{t('subscription.frequency.annual')}</option>
                                </select>
                            </FormField>
                            <FormField label={t('subscription.form.base_amount')} required style={{ marginBottom: 0 }}>
                                <input
                                    type="text" inputMode="decimal" name="base_amount" className="form-input"
                                    required
                                    value={formData.base_amount} onChange={handleChange}
                                />
                            </FormField>
                            <FormField label={t('subscription.form.trial_period_days')} style={{ marginBottom: 0 }}>
                                <input
                                    type="number" name="trial_period_days" className="form-input"
                                    min="0" value={formData.trial_period_days} onChange={handleChange}
                                />
                            </FormField>
                        </div>
                        <div className="form-row" style={{ display: 'flex', gap: '32px', marginTop: '24px', alignItems: 'center' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                <input type="checkbox" name="auto_renewal" checked={formData.auto_renewal} onChange={handleChange} />
                                {t('subscription.form.auto_renewal')}
                            </label>
                            {isEdit && (
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input type="checkbox" name="is_active" checked={formData.is_active} onChange={handleChange} />
                                    {t('common.active')}
                                </label>
                            )}
                        </div>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '8px' }}>
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/finance/subscriptions/plans')}>
                            {t('common.cancel')}
                        </button>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? t('common.saving') : t('common.save')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}

export default PlanForm
