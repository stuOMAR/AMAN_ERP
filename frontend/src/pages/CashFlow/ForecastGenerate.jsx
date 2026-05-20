import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cashflowAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import BackButton from '../../components/common/BackButton'
import FormField from '../../components/common/FormField'

function ForecastGenerate() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [formData, setFormData] = useState({
        name: '',
        horizon_days: 90,
        mode: 'contractual',
    })

    const handleChange = (field, value) => {
        setFormData(prev => ({ ...prev, [field]: value }))
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            setLoading(true)
            setError(null)
            const response = await cashflowAPI.generate({
                name: formData.name.trim(),
                horizon_days: parseInt(formData.horizon_days, 10),
                mode: formData.mode,
            })
            navigate(`/finance/cashflow/${response.data.id}`)
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_saving'))
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('cashflow.generate_title')}</h1>
                <p className="workspace-subtitle">{t('cashflow.generate_subtitle')}</p>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <div className="card">
                <form onSubmit={handleSubmit}>
                    <FormField label={t('cashflow.form.name')} required>
                        <input
                            type="text"
                            className="form-input"
                            value={formData.name}
                            onChange={(e) => handleChange('name', e.target.value)}
                            required
                            maxLength={200}
                        />
                    </FormField>

                    <FormField label={t('cashflow.form.horizon_days')}>
                        <select
                            className="form-input"
                            value={formData.horizon_days}
                            onChange={(e) => handleChange('horizon_days', e.target.value)}
                        >
                            <option value="30">30 {t('cashflow.form.days')}</option>
                            <option value="60">60 {t('cashflow.form.days')}</option>
                            <option value="90">90 {t('cashflow.form.days')}</option>
                            <option value="180">180 {t('cashflow.form.days')}</option>
                            <option value="365">365 {t('cashflow.form.days')}</option>
                        </select>
                    </FormField>

                    <FormField label={t('cashflow.form.mode')}>
                        <select
                            className="form-input"
                            value={formData.mode}
                            onChange={(e) => handleChange('mode', e.target.value)}
                        >
                            <option value="contractual">{t('cashflow.mode.contractual')}</option>
                            <option value="expected">{t('cashflow.mode.expected')}</option>
                        </select>
                    </FormField>

                    <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem' }}>
                        <button type="submit" className="btn btn-primary" disabled={loading || !formData.name}>
                            {loading ? t('common.loading') : t('cashflow.form.generate')}
                        </button>
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/finance/cashflow')}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}

export default ForecastGenerate
