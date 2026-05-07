import { useState, useEffect } from 'react'
import { taxesAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'


function TaxAudit() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [startDate, setStartDate] = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
    const [endDate, setEndDate] = useState(new Date())
    const [data, setData] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const fetchData = async () => {
        try {
            setLoading(true)
            setError(null)
            const response = await taxesAPI.getTaxAudit({
                start_date: startDate.toISOString().split('T')[0],
                end_date: endDate.toISOString().split('T')[0],
                branch_id: currentBranch?.id
            })
            setData(response.data)
        } catch (err) {
            console.error("Failed to fetch tax audit", err)
            setError(t('errors.fetch_failed'))
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchData()
    }, [currentBranch, startDate, endDate])

    return (
        <div className="workspace fade-in">
            <div className="workspace-header display-flex justify-between align-center">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('reports.tax_audit.title')}</h1>
                    <p className="workspace-subtitle">{t('reports.tax_audit.subtitle')}</p>
                </div>
                <div className="display-flex gap-2">
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        {t('common.print')}
                    </button>
                    <button className="btn btn-primary" onClick={fetchData}>
                        {t('common.refresh')}
                    </button>
                </div>
            </div>

            <div className="card mb-4 mt-4">
                <div className="card-body">
                    <div className="display-flex gap-4 align-center">
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.start_date')}</label>
                            <CustomDatePicker
                                selected={startDate}
                                onChange={date => setStartDate(date)}
                                className="form-input"
                            />
                        </div>
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.end_date')}</label>
                            <CustomDatePicker
                                selected={endDate}
                                onChange={date => setEndDate(date)}
                                className="form-input"
                            />
                        </div>
                    </div>
                </div>
            </div>

            {loading ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : (
                <div className="card">
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('common.date')}</th>
                                    <th>{t('common.number')}</th>
                                    <th>{t('common.type')}</th>
                                    <th>{t('common.party')}</th>
                                    <th>{t('reports.tax_audit.tax_number')}</th>
                                    <th style={{ textAlign: 'left' }}>{t('reports.tax_audit.taxable')}</th>
                                    <th style={{ textAlign: 'left' }}>{t('reports.tax_audit.vat')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.map((item) => (
                                    <tr key={item.id} style={{ cursor: 'pointer' }}>
                                        <td style={{ whiteSpace: 'nowrap' }}>{formatShortDate(item.date)}</td>
                                        <td>
                                            <span className="fw-bold" style={{ color: 'var(--primary)' }}>{item.number}</span>
                                        </td>
                                        <td>
                                            <span style={{ 
                                                background: item.type.includes('sales') ? 'rgba(34, 197, 94, 0.1)' : 'rgba(59, 130, 246, 0.1)', 
                                                color: item.type.includes('sales') ? 'rgb(34, 197, 94)' : 'rgb(59, 130, 246)', 
                                                padding: '4px 10px', 
                                                borderRadius: '6px', 
                                                fontSize: '12px', 
                                                fontWeight: '600' 
                                            }}>
                                                {t(`common.${item.type}`) || item.type}
                                            </span>
                                        </td>
                                        <td>{item.party || <span className="text-muted">—</span>}</td>
                                        <td style={{ fontFamily: 'monospace' }}>{item.tax_number || <span className="text-muted">—</span>}</td>
                                        <td style={{ textAlign: 'left', whiteSpace: 'nowrap' }}>{formatNumber(item.taxable)} <small>{currency}</small></td>
                                        <td style={{ textAlign: 'left', fontWeight: '700', whiteSpace: 'nowrap' }}>{formatNumber(item.vat)} <small>{currency}</small></td>
                                    </tr>
                                ))}
                                {data.length === 0 && (
                                    <tr>
                                        <td colSpan="7" className="text-center p-5 text-muted">
                                            {t('common.no_data')}
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    )
}

export default TaxAudit
