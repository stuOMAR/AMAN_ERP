import { useState, useEffect } from 'react'
import { taxesAPI, companiesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { useBranch } from '../../context/BranchContext'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function VATReport() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [report, setReport] = useState(null)
    const [currency, setCurrency] = useState('')
    const [dates, setDates] = useState({
        start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
        end: new Date().toISOString().split('T')[0]
    })

    const fetchReport = async () => {
        try {
            setLoading(true)
            const [reportRes, companyRes] = await Promise.all([
                taxesAPI.getVATReport({
                    branch_id: currentBranch?.id,
                    start_date: dates.start,
                    end_date: dates.end
                }),
                companiesAPI.getCurrentCompany(localStorage.getItem('company_id'))
            ])
            setReport(reportRes.data)
            setCurrency(reportRes.data.display_currency || companyRes.data.currency || '')
        } catch (err) {
            setError(t('accounting.vat.load_error'))
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchReport()
    }, [currentBranch, dates])

    if (loading && !report) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <div>
                        <h1 className="workspace-title">📊 {t('accounting.vat_report.title')}</h1>
                        <p className="workspace-subtitle">{t('accounting.vat_report.subtitle')}</p>
                    </div>
                    <div style={{ display: 'flex', gap: '12px' }}>
                        <CustomDatePicker
                            label={t('common.start_date')}
                            selected={dates.start}
                            onChange={(d) => setDates({ ...dates, start: d })}
                        />
                        <CustomDatePicker
                            label={t('common.end_date')}
                            selected={dates.end}
                            onChange={(d) => setDates({ ...dates, end: d })}
                        />
                        <button className="btn btn-secondary" onClick={() => window.print()} style={{ alignSelf: 'flex-end', height: '42px' }}>
                            🖨️ {t('common.print')}
                        </button>
                    </div>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            {report && (
                <>
                    <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('accounting.vat_report.output_vat')}</div>
                            <div className="metric-value text-secondary">{formatNumber(report.output_vat.vat)} <small>{currency}</small></div>
                            <div className="metric-change">{t('accounting.vat_report.taxable_amount')}: {formatNumber(report.output_vat.taxable)}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('accounting.vat_report.input_vat')}</div>
                            <div className="metric-value text-primary">{formatNumber(report.input_vat.vat)} <small>{currency}</small></div>
                            <div className="metric-change">{t('accounting.vat_report.taxable_amount')}: {formatNumber(report.input_vat.taxable)}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('accounting.vat_report.net_vat')}</div>
                            <div className={`metric-value ${report.net_vat_payable >= 0 ? 'text-error' : 'text-success'}`}>
                                {formatNumber(Math.abs(report.net_vat_payable))} <small>{currency}</small>
                            </div>
                            <div className="metric-change">{report.net_vat_payable >= 0 ? (t('accounting.vat_report.payable')) : (t('accounting.vat_report.refundable'))}</div>
                        </div>
                    </div>

                    <div className="card">
                        <h3 className="section-title">{t('accounting.vat.declaration_details')}</h3>
                        <table className="data-table mt-4">
                            <thead>
                                <tr style={{ background: 'var(--bg-secondary)' }}>
                                    <th>{t('accounting.vat.item')}</th>
                                    <th style={{ textAlign: 'left' }}>{t('accounting.vat.taxable_amount')}</th>
                                    <th style={{ textAlign: 'left' }}>{t('accounting.vat.tax_amount')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td style={{ fontWeight: 'bold' }}>{t('accounting.vat.sales_basic_15')}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(report.output_vat.taxable)} {currency}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(report.output_vat.vat)} {currency}</td>
                                </tr>
                                <tr style={{ borderBottom: '2px solid var(--border-color)' }}>
                                    <td style={{ fontWeight: 'bold' }}>{t('accounting.vat.output_total')}</td>
                                    <td style={{ textAlign: 'left', fontWeight: 'bold' }}>{formatNumber(report.output_vat.taxable)} {currency}</td>
                                    <td style={{ textAlign: 'left', fontWeight: 'bold', color: 'var(--text-secondary)' }}>{formatNumber(report.output_vat.vat)} {currency}</td>
                                </tr>
                                <tr>
                                    <td style={{ fontWeight: 'bold' }}>{t('accounting.vat.purchases_basic_15')}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(report.input_vat.taxable)} {currency}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(report.input_vat.vat)} {currency}</td>
                                </tr>
                                <tr style={{ borderBottom: '2px solid var(--border-color)' }}>
                                    <td style={{ fontWeight: 'bold' }}>{t('accounting.vat.input_total')}</td>
                                    <td style={{ textAlign: 'left', fontWeight: 'bold' }}>{formatNumber(report.input_vat.taxable)} {currency}</td>
                                    <td style={{ textAlign: 'left', fontWeight: 'bold', color: 'var(--primary)' }}>{formatNumber(report.input_vat.vat)} {currency}</td>
                                </tr>
                                <tr style={{ background: 'var(--bg-secondary)', fontSize: '1.2rem' }}>
                                    <td style={{ fontWeight: 'bold' }}>{t('accounting.vat.net_tax')}</td>
                                    <td></td>
                                    <td style={{ textAlign: 'left', fontWeight: 'bold', color: report.net_vat_payable >= 0 ? 'var(--text-error)' : 'var(--text-success)' }}>
                                        {formatNumber(report.net_vat_payable)} {currency}
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    )
}

export default VATReport
