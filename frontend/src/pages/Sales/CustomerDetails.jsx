import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { FileText, Banknote, Calendar, CreditCard, Building, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { getCurrency } from '../../utils/auth'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'


export default function CustomerDetails() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const { id } = useParams()
    const { currentBranch } = useBranch()
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState({ customer: {}, invoices: [], receipts: [] })
    const [activeTab, setActiveTab] = useState('invoices')
    const currency = getCurrency()

    useEffect(() => {
        const fetchData = async () => {
            setLoading(true)
            try {
                const response = await salesAPI.getCustomerTransactions(id, currentBranch?.id)
                setData(response.data)
            } catch (error) {
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [id, currentBranch?.id])

    if (loading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                    <div>
                        <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Building style={{ color: 'var(--primary)' }} size={24} />
                            {data.customer?.name}
                        </h1>
                        <p className="workspace-subtitle">{t('sales.customer_details.subtitle')}</p>
                    </div>
                </div>

                <div style={{ display: 'flex', gap: '16px' }}>
                    <div style={{
                        padding: '8px 16px',
                        background: 'var(--bg-secondary)',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        textAlign: 'center'
                    }}>
                        <span style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'block' }}>{t('sales.customer_details.total_sales')}</span>
                        <span style={{
                            fontSize: '20px',
                            fontWeight: '700',
                            color: 'var(--primary)',
                            direction: 'ltr',
                            display: 'block'
                        }}>
                            {formatNumber(data.customer?.total_sales || 0)} {currency}
                        </span>
                    </div>

                    <div style={{
                        padding: '8px 16px',
                        background: 'var(--bg-secondary)',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        textAlign: 'center'
                    }}>
                        <span style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'block' }}>{t('sales.customer_details.current_balance')}</span>
                        <span style={{
                            fontSize: '20px',
                            fontWeight: '700',
                            color: data.customer?.balance > 0 ? 'var(--error)' : 'var(--success)',
                            direction: 'ltr',
                            display: 'block'
                        }}>
                            {formatNumber(data.customer?.balance)} {data.customer?.balance_currency || currency}
                        </span>
                    </div>
                </div>
            </div>

            {/* Party Sites */}
            {data.customer?.party_sites && data.customer.party_sites.length > 0 && (
                <div style={{ marginBottom: '24px' }}>
                    <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Globe size={16} />
                        {t('sales.customer_details.party_sites', 'Sites & Currencies')}
                    </h3>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                        {data.customer.party_sites.map(site => (
                            <div key={site.id} style={{
                                padding: '12px 16px',
                                background: site.is_default ? 'var(--primary-light)' : 'var(--bg-secondary)',
                                borderRadius: 'var(--radius)',
                                border: `1px solid ${site.is_default ? 'var(--primary)' : 'var(--border)'}`,
                                minWidth: '180px'
                            }}>
                                <div style={{ fontWeight: '600', fontSize: '14px' }}>{site.site_name}</div>
                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                                    {site.currency}
                                    {site.is_default && ' ★'}
                                </div>
                                <div style={{
                                    fontSize: '16px', fontWeight: '700', marginTop: '8px',
                                    color: site.site_balance > 0 ? 'var(--error)' : 'var(--success)'
                                }}>
                                    {formatNumber(site.site_balance)} {site.currency}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Tabs */}
            <div style={{ borderBottom: '1px solid var(--border)', marginBottom: '24px', display: 'flex', gap: '24px' }}>
                <button
                    onClick={() => setActiveTab('invoices')}
                    style={{
                        padding: '12px 4px',
                        display: 'flex', alignItems: 'center', gap: '8px',
                        borderBottom: activeTab === 'invoices' ? '2px solid var(--primary)' : '2px solid transparent',
                        color: activeTab === 'invoices' ? 'var(--primary)' : 'var(--text-secondary)',
                        fontWeight: activeTab === 'invoices' ? '600' : '400',
                        cursor: 'pointer',
                        background: 'none',
                        borderTop: 'none', borderLeft: 'none', borderRight: 'none'
                    }}
                >
                    <FileText size={18} />
                    {t('sales.customer_details.tabs.invoices')}
                    <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                        {data.invoices?.length || 0}
                    </span>
                </button>
                <button
                    onClick={() => setActiveTab('receipts')}
                    style={{
                        padding: '12px 4px',
                        display: 'flex', alignItems: 'center', gap: '8px',
                        borderBottom: activeTab === 'receipts' ? '2px solid var(--primary)' : '2px solid transparent',
                        color: activeTab === 'receipts' ? 'var(--primary)' : 'var(--text-secondary)',
                        fontWeight: activeTab === 'receipts' ? '600' : '400',
                        cursor: 'pointer',
                        background: 'none',
                        borderTop: 'none', borderLeft: 'none', borderRight: 'none'
                    }}
                >
                    <Banknote size={18} />
                    {t('sales.customer_details.tabs.receipts')}
                    <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                        {data.receipts?.length || 0}
                    </span>
                </button>
            </div>

            {/* Content */}
            <div className="data-table-container">
                {activeTab === 'invoices' && (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('sales.invoices.table.number')}</th>
                                <th>{t('sales.invoices.table.date')}</th>
                                <th>{t('sales.invoices.table.total')}</th>
                                <th>{t('sales.invoices.details.paid_amount')}</th>
                                <th>{t('sales.invoices.table.status')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.invoices?.map(inv => (
                                <tr key={inv.id} className="hover-row">
                                    <td className="font-medium text-primary">{inv.invoice_number}</td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <Calendar size={14} style={{ color: 'var(--text-secondary)' }} />
                                            {formatShortDate(inv.date)}
                                        </div>
                                    </td>
                                    <td style={{ fontWeight: '600' }}>{formatNumber(inv.total)} {inv.currency || currency}</td>
                                    <td style={{ color: 'var(--success)' }}>{formatNumber(inv.paid_amount || 0)} {inv.currency || currency}</td>
                                    <td>
                                        <span className={`badge ${inv.status === 'paid' ? 'badge-success' :
                                            inv.status === 'partial' ? 'badge-warning' :
                                                'badge-danger'
                                            }`}>
                                            {inv.status === 'paid' ? t('sales.invoices.status.paid') :
                                                inv.status === 'partial' ? t('sales.invoices.status.partial') :
                                                    t('sales.invoices.status.unpaid')}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                            {data.invoices?.length === 0 && (
                                <tr>
                                    <td colSpan="5" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        {t('sales.customer_details.no_invoices')}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                )}

                {activeTab === 'receipts' && (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('sales.customer_details.receipt_table.voucher')}</th>
                                <th>{t('sales.customer_details.receipt_table.date')}</th>
                                <th>{t('sales.customer_details.receipt_table.amount')}</th>
                                <th>{t('sales.customer_details.receipt_table.method')}</th>
                                <th>{t('sales.customer_details.receipt_table.status')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.receipts?.map(rec => (
                                <tr key={rec.id} className="hover-row">
                                    <td className="font-medium text-success">{rec.voucher_number}</td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <Calendar size={14} style={{ color: 'var(--text-secondary)' }} />
                                            {formatShortDate(rec.date)}
                                        </div>
                                    </td>
                                    <td style={{ fontWeight: '600' }}>{formatNumber(rec.amount)} {currency}</td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <CreditCard size={14} style={{ color: 'var(--text-secondary)' }} />
                                            {rec.method === 'cash' ? t('sales.invoices.form.payment.cash') :
                                                rec.method === 'bank' ? t('sales.invoices.form.payment.bank') :
                                                    t('sales.invoices.form.payment.check')}
                                        </div>
                                    </td>
                                    <td>
                                        <span className={`badge ${rec.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                                            {rec.status === 'posted' ? t('sales.customer_details.receipt_status.posted') : t('sales.customer_details.receipt_status.draft')}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                            {data.receipts?.length === 0 && (
                                <tr>
                                    <td colSpan="5" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        {t('sales.customer_details.no_receipts')}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}
