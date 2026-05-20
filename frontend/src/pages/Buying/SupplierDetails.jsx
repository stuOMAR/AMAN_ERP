import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { ArrowRight, FileText, Banknote, Calendar, CreditCard, Building, Edit2, Clock, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format'

export default function SupplierDetails() {
    const { t } = useTranslation()
    const { id } = useParams()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [data, setData] = useState({ supplier: {}, invoices: [], payments: [], receipts: [] })
    const [activeTab, setActiveTab] = useState('invoices')
    const [balanceView, setBalanceView] = useState('supplier')
    const currency = getCurrency()

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await purchasesAPI.getSupplierTransactions(id, currentBranch?.id)
                setData(response.data)
            } catch (error) {
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
                setInitialLoad(false)
            }
        }
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [id, currentBranch?.id])

    if (initialLoad && !data) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <button
                        onClick={() => navigate('/buying/suppliers')}
                        className="btn btn-icon"
                        style={{ background: 'var(--bg-secondary)', width: '40px', height: '40px', borderRadius: '50%' }}
                    >
                        <ArrowRight size={20} />
                    </button>
                    <div>
                        <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Building style={{ color: 'var(--primary)' }} size={24} />
                            {data.supplier?.name}
                        </h1>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <p className="workspace-subtitle">{t('buying.suppliers.details.subtitle')}</p>
                            <button
                                onClick={() => navigate(`/buying/suppliers/${id}/edit`)}
                                className="btn btn-secondary btn-sm"
                                style={{ padding: '4px 12px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}
                            >
                                <Edit2 size={14} />
                                {t('common.edit')}
                            </button>
                        </div>
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
                        <span style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'block' }}>{t('buying.suppliers.details.total_purchases')}</span>
                        <span style={{
                            fontSize: '20px',
                            fontWeight: '700',
                            color: 'var(--primary)',
                            direction: 'ltr',
                            display: 'block'
                        }}>
                            {formatNumber(data.supplier?.total_purchases || 0)} {currency}
                        </span>
                    </div>

                    <div style={{
                        padding: '8px 16px',
                        background: 'var(--bg-secondary)',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        textAlign: 'center',
                        position: 'relative',
                        minWidth: '200px'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('buying.suppliers.details.current_balance')}</span>
                            {/* Toggle Button */}
                            {data.supplier?.currency && data.supplier?.currency !== currency && (
                                <button
                                    onClick={() => setBalanceView(prev => prev === 'supplier' ? 'base' : 'supplier')}
                                    style={{
                                        background: 'none', border: '1px solid var(--border)', borderRadius: '12px',
                                        padding: '2px 8px', fontSize: '10px', cursor: 'pointer',
                                        color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px'
                                    }}
                                    title={t('common.switch_currency')}
                                >
                                    <Clock size={10} />
                                    {balanceView === 'supplier' ? data.supplier.currency : currency}
                                </button>
                            )}
                        </div>

                        {balanceView === 'supplier' ? (
                            <span style={{
                                fontSize: '20px',
                                fontWeight: '700',
                                color: data.supplier?.balance > 0 ? 'var(--error)' : 'var(--success)',
                                direction: 'ltr',
                                display: 'block',
                                marginTop: '4px'
                            }}>
                                {formatNumber(data.supplier?.balance || 0)} {data.supplier?.currency || currency}
                            </span>
                        ) : (
                            <span style={{
                                fontSize: '20px',
                                fontWeight: '700',
                                color: data.supplier?.balance_bc > 0 ? 'var(--error)' : 'var(--success)',
                                direction: 'ltr',
                                display: 'block',
                                marginTop: '4px'
                            }}>
                                {formatNumber(data.supplier?.balance_bc || 0)} {currency}
                                <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 'normal' }}>
                                    (Rate: {data.supplier?.exchange_rate})
                                </div>
                            </span>
                        )}
                    </div>
                </div>
            </div>

            {/* Party Sites */}
            {data.supplier?.party_sites && data.supplier.party_sites.length > 0 && (
                <div style={{ marginBottom: '24px' }}>
                    <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Globe size={16} />
                        {t('buying.suppliers.details.party_sites', 'Sites & Currencies')}
                    </h3>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                        {data.supplier.party_sites.map(site => (
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
                                    {formatNumber(site.site_balance || 0)} {site.currency}
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
                    {t('buying.suppliers.details.tabs.invoices')}
                    <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                        {data.invoices?.length || 0}
                    </span>
                </button>
                <button
                    onClick={() => setActiveTab('payments')}
                    style={{
                        padding: '12px 4px',
                        display: 'flex', alignItems: 'center', gap: '8px',
                        borderBottom: activeTab === 'payments' ? '2px solid var(--primary)' : '2px solid transparent',
                        color: activeTab === 'payments' ? 'var(--primary)' : 'var(--text-secondary)',
                        fontWeight: activeTab === 'payments' ? '600' : '400',
                        cursor: 'pointer',
                        background: 'none',
                        borderTop: 'none', borderLeft: 'none', borderRight: 'none'
                    }}
                >
                    <Banknote size={18} />
                    {t('buying.suppliers.details.tabs.payments')}
                    <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                        {data.payments?.length || 0}
                    </span>
                </button>
                <button
                    onClick={() => setActiveTab('receipts')}
                    style={{
                        padding: '12px 4px',
                        display: 'flex', alignItems: 'center', gap: '8px',
                        borderBottom: activeTab === 'receipts' ? '2px solid var(--success)' : '2px solid transparent',
                        color: activeTab === 'receipts' ? 'var(--success)' : 'var(--text-secondary)',
                        fontWeight: activeTab === 'receipts' ? '600' : '400',
                        cursor: 'pointer',
                        background: 'none',
                        borderTop: 'none', borderLeft: 'none', borderRight: 'none'
                    }}
                >
                    <Banknote size={18} style={{ color: 'var(--success)' }} />
                    {t('buying.suppliers.details.tabs.receipts')}
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
                                <th>{t('buying.suppliers.details.table.invoice_number')}</th>
                                <th>{t('buying.suppliers.details.table.date')}</th>
                                <th>{t('buying.suppliers.details.table.total')}</th>
                                <th>{t('buying.suppliers.details.table.paid')}</th>
                                <th>{t('buying.suppliers.details.table.status')}</th>
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
                                    <td style={{ fontWeight: '600' }}>{formatNumber(inv.total || 0)} {inv.currency}</td>
                                    <td style={{ color: 'var(--success)' }}>{formatNumber(inv.paid || 0)} {inv.currency}</td>
                                    <td>
                                        <span className={`badge ${inv.status === 'paid' ? 'badge-success' :
                                            inv.status === 'partial' ? 'badge-warning' :
                                                'badge-danger'
                                            }`}>
                                            {inv.status === 'paid' ? t('buying.suppliers.details.status.paid') :
                                                inv.status === 'partial' ? t('buying.suppliers.details.status.partial') :
                                                    t('buying.suppliers.details.status.unpaid')}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                            {data.invoices?.length === 0 && (
                                <tr>
                                    <td colSpan="5" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        {t('buying.suppliers.details.empty.invoices')}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                )}

                {activeTab === 'payments' && (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('buying.suppliers.details.table.voucher_number')}</th>
                                <th>{t('buying.suppliers.details.table.date')}</th>
                                <th>{t('buying.suppliers.details.table.amount')}</th>
                                <th>{t('buying.suppliers.details.table.method')}</th>
                                <th>{t('buying.suppliers.details.table.status')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.payments?.map(pay => (
                                <tr key={pay.id} className="hover-row">
                                    <td className="font-medium text-success">{pay.voucher_number}</td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <Calendar size={14} style={{ color: 'var(--text-secondary)' }} />
                                            {formatShortDate(pay.date)}
                                        </div>
                                    </td>
                                    <td style={{ fontWeight: '600' }}>{formatNumber(pay.amount || 0)} {pay.currency}</td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <CreditCard size={14} style={{ color: 'var(--text-secondary)' }} />
                                            {pay.method === 'cash' ? t('buying.suppliers.details.status.cash') :
                                                pay.method === 'bank' ? t('buying.suppliers.details.status.bank') :
                                                    t('buying.suppliers.details.status.cheque')}
                                        </div>
                                    </td>
                                    <td>
                                        <span className={`badge ${pay.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                                            {pay.status === 'posted' ? t('buying.suppliers.details.status.posted') : t('buying.suppliers.details.status.draft')}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                            {data.payments?.length === 0 && (
                                <tr>
                                    <td colSpan="5" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        {t('buying.suppliers.details.empty.payments')}
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
                                <th>{t('buying.suppliers.details.table.voucher_number')}</th>
                                <th>{t('buying.suppliers.details.table.date')}</th>
                                <th>{t('buying.suppliers.details.table.amount')}</th>
                                <th>{t('buying.suppliers.details.table.method')}</th>
                                <th>{t('buying.suppliers.details.table.status')}</th>
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
                                    <td style={{ fontWeight: '600' }}>{formatNumber(rec.amount || 0)} {rec.currency}</td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <CreditCard size={14} style={{ color: 'var(--text-secondary)' }} />
                                            {rec.method === 'cash' ? t('buying.suppliers.details.status.cash') :
                                                rec.method === 'bank' ? t('buying.suppliers.details.status.bank') :
                                                    t('buying.suppliers.details.status.cheque')}
                                        </div>
                                    </td>
                                    <td>
                                        <span className={`badge ${rec.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                                            {rec.status === 'posted' ? t('buying.suppliers.details.status.posted') : t('buying.suppliers.details.status.draft')}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                            {data.receipts?.length === 0 && (
                                <tr>
                                    <td colSpan="5" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        {t('buying.suppliers.details.empty.receipts')}
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
