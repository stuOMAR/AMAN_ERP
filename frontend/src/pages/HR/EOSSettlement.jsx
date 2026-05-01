import { useState, useEffect } from 'react'
import { wpsAPI, hrAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import BackButton from '../../components/common/BackButton'

function EOSSettlement() {
    const { t } = useTranslation()
    const currency = getCurrency()
    const [employees, setEmployees] = useState([])
    const [selectedEmp, setSelectedEmp] = useState('')
    const [reason, setReason] = useState('termination')
    const [result, setResult] = useState(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        hrAPI.listEmployees({ status: 'active' }).then(r => setEmployees(r.data)).catch(() => toastEmitter.emit(t('common.error'), 'error'))
    }, [])

    const handleSettle = async () => {
        if (!selectedEmp) return
        setLoading(true)
        try {
            const res = await wpsAPI.settleEndOfService({
                employee_id: Number(selectedEmp),
                termination_reason: reason,
            })
            setResult(res.data)
            toastEmitter.emit(t('eos.settled_success'), 'success')
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setLoading(false) }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🏁 {t('eos.title')}</h1>
                    <p className="workspace-subtitle">{t('eos.subtitle')}</p>
                </div>
            </div>

            <div className="card p-4">
                <div className="alert alert-info mb-3">
                    ℹ️ {t('eos.info_note')}
                </div>
                <div className="form-grid-3">
                    <div className="form-group">
                        <label>{t('common.employee')} *</label>
                        <select className="form-select" value={selectedEmp} onChange={e => setSelectedEmp(e.target.value)}>
                            <option value="">{t('common.select')}</option>
                            {employees.map(emp => (
                                <option key={emp.id} value={emp.id}>{emp.full_name} ({emp.employee_code})</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>{t('eos.reason')} *</label>
                        <select className="form-select" value={reason} onChange={e => setReason(e.target.value)}>
                            <option value="termination">{t('eos.termination')}</option>
                            <option value="resignation">{t('eos.resignation')}</option>
                            <option value="retirement">{t('eos.retirement')}</option>
                            <option value="contract_end">{t('eos.contract_end')}</option>
                        </select>
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <button className="btn btn-primary" onClick={handleSettle} disabled={!selectedEmp || loading}>
                            {loading ? t('common.processing') : t('eos.calculate_settle')}
                        </button>
                    </div>
                </div>
            </div>

            {result && (
                <div className="card mt-4 p-4">
                    <h3 className="card-title mb-3">{t('eos.settlement_result')}</h3>
                    <div className="grid grid-2" style={{ gap: 16 }}>
                        <div className="detail-grid">
                            <div><strong>{t('eos.years_of_service')}:</strong> {result.service_years_display || result.service_years}</div>
                            <div><strong>{t('common.employee')}:</strong> {result.employee_name}</div>
                            <div><strong>{t('eos.reason')}:</strong> {t(`eos.${result.termination_reason}`, result.termination_reason)}</div>
                            <div><strong>{t('eos.join_date')}:</strong> {result.join_date}</div>
                            <div><strong>{t('eos.termination_date')}:</strong> {result.termination_date}</div>
                        </div>
                        <div className="detail-grid">
                            <div><strong>{t('eos.base_salary')}:</strong> {formatNumber(result.base_salary)} {currency}</div>
                            <div><strong>{t('eos.total_salary_used')}:</strong> {formatNumber(result.total_salary_used)} {currency}</div>
                            <div><strong>{t('eos.full_gratuity')}:</strong> {formatNumber(result.full_gratuity)} {currency}</div>
                            {Number(result.unpaid_leave_days) > 0 && (
                                <div className="text-warning">
                                    <strong>{t('eos.unpaid_leave_deduction')}:</strong> −{formatNumber(result.unpaid_leave_deduction)} {currency}
                                    <span className="text-muted text-xs ms-1">({result.unpaid_leave_days} {t('eos.days')})</span>
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="mt-4 p-3 bg-light rounded text-center">
                        <div className="text-muted">{t('eos.final_gratuity')}</div>
                        <div className="text-2xl font-bold text-primary">
                            {formatNumber(result.final_gratuity)} {currency}
                        </div>
                        {result.notes && <div className="text-xs text-muted mt-1">{result.notes}</div>}
                    </div>
                </div>
            )}
        </div>
    )
}

export default EOSSettlement
