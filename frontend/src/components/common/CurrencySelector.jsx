import { useState, useEffect } from 'react'
import { currenciesAPI } from '../../utils/api'
import { fetchCurrentRate } from '../../hooks/useExchangeRate'
import { useTranslation } from 'react-i18next'
import { Spinner } from './LoadingStates'

export default function CurrencySelector({ value, onChange, className = '', label = '', disabled = false, required = false }) {
    const { t } = useTranslation()
    const [currencies, setCurrencies] = useState([])
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        const fetchCurrencies = async () => {
            try {
                setLoading(true)
                const response = await currenciesAPI.list()
                setCurrencies(response.data)

                // If no value is selected and we have currencies, select base by default
                if (!value && response.data.length > 0) {
                    const base = response.data.find(c => c.is_base) || response.data[0]
                    if (base) {
                        onChange(base.code, base.exchange_rate || 1.0)
                    }
                }
            } catch (error) {
                console.error('Error fetching currencies:', error)
            } finally {
                setLoading(false)
            }
        }
        fetchCurrencies()
    }, [])

    // T8.4: replace static `currencies.exchange_rate` with the live rate from
    // /accounting/currencies/current. Falls back gracefully on any error.
    const handleChange = async (e) => {
        const code = e.target.value
        const selected = currencies.find(c => c.code === code)
        const fallback = selected?.exchange_rate || 1.0
        // Push the fallback immediately for snappy UI, then refine.
        onChange(code, fallback)
        try {
            const live = await fetchCurrentRate(code)
            if (live && live !== fallback) onChange(code, live)
        } catch { /* keep fallback */ }
    }

    if (loading && currencies.length === 0) {
        return <Spinner size="sm" />
    }

    return (
        <div className={`form-group ${className}`}>
            {label && <label className="form-label">{label}</label>}
            <select
                className="form-input"
                value={value}
                onChange={handleChange}
                disabled={disabled}
                required={required}
            >
                {currencies.map(c => (
                    <option key={c.code} value={c.code}>
                        {c.code} - {c.name} {c.is_base ? `(${t('common.base_currency') || 'العملة الأساسية'})` : ''}
                    </option>
                ))}
            </select>
        </div>
    )
}
