import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format'

function BuyingReturnDetails() {
    const { t } = useTranslation()
    const { id } = useParams()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const [returnn, setReturnn] = useState(null)
    const [loading, setLoading] = useState(true)
    const currency = getCurrency()

    useEffect(() => {
        const fetchDetails = async () => {
            try {
                const res = await purchasesAPI.getReturn(id)
                setReturnn(res.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
            }
        }
        fetchDetails()
    }, [id])

    if (loading) return <PageLoading />
    if (!returnn) return <div className="p-8 text-center text-error">{t('buying.returns.details.not_found')}</div>

    const { invoice, items } = returnn

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{t('buying.returns.details.title')} #{invoice.invoice_number}</h1>
                        <span className="status-badge approved">
                            {t('buying.returns.status.posted')}
                        </span>
                    </div>
                    <p className="workspace-subtitle">{t('buying.returns.details.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        🖨️ {t('buying.returns.details.print')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/buying/returns')}>
                        {t('buying.returns.details.back_to_list')}
                    </button>
                </div>
            </div>

            <div className="card">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('buying.returns.details.supplier')}:</h4>
                        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{invoice.supplier_name}</div>
                        <div style={{ color: 'var(--text-secondary)' }}>{invoice.supplier_phone}</div>
                    </div>
                    <div style={{ textAlign: 'left' }}>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('buying.returns.details.date')}:</h4>
                        <div style={{ fontSize: '18px' }}>
                            {formatShortDate(invoice.invoice_date)}
                        </div>
                        <div style={{ color: 'var(--text-secondary)' }}>{t('buying.returns.details.created_by')}: {t('common.admin')}</div>
                    </div>
                </div>

                <div className="invoice-items-container" style={{ border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '5%' }}>#</th>
                                <th style={{ width: '30%' }}>{t('buying.returns.form.items.product')}</th>
                                <th style={{ width: '10%', textAlign: 'center' }}>{t('buying.returns.form.items.quantity')}</th>
                                <th style={{ width: '20%' }}>{t('buying.returns.form.items.unit_price')}</th>
                                <th style={{ width: '10%' }}>{t('buying.returns.form.items.tax')}</th>
                                <th style={{ width: '20%' }}>{t('buying.returns.form.items.total')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((item, idx) => (
                                <tr key={idx}>
                                    <td>{idx + 1}</td>
                                    <td>
                                        <div className="font-medium">{item.product_name}</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{item.product_code}</div>
                                    </td>
                                    <td style={{ textAlign: 'center' }}>{formatNumber(item.quantity)}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(item.unit_price)} <small>{invoice.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{item.tax_rate}%</td>
                                    <td style={{ textAlign: 'left' }} className="font-bold">
                                        {formatNumber(item.total ?? item.line_total ?? 0)} <small>{invoice.currency || currency}</small>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '32px' }}>
                    <div style={{ flex: 1, maxWidth: '500px' }}>
                        <h4 style={{ marginBottom: '8px' }}>{t('buying.returns.details.notes')}:</h4>
                        <p style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{invoice.notes || t('buying.returns.details.no_notes')}</p>
                    </div>

                    <div style={{ width: '300px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.returns.form.summary.subtotal')}:</span>
                            <span>{formatNumber(invoice.subtotal)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.returns.form.summary.tax')}:</span>
                            <span>{formatNumber(invoice.tax_amount)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.2rem', color: 'var(--primary)' }}>
                            <span>{t('buying.returns.form.summary.grand_total')}:</span>
                            <span>{formatNumber(invoice.total)} <small>{invoice.currency || currency}</small></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default BuyingReturnDetails
