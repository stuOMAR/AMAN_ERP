import { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { formatNumber } from '../../utils/format'
import { Printer, CreditCard, Calendar, User, FileText, CheckCircle, Info } from 'lucide-react'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function ReceiptDetails() {
    const { t } = useTranslation();
    const { id } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const [voucher, setVoucher] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const currency = getCurrency();

    // Determine type from URL
    const isRefund = location.pathname.includes('/payments');

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = isRefund
                    ? await salesAPI.getPayment(id)
                    : await salesAPI.getReceipt(id);
                setVoucher(response.data);
            } catch (err) {
                setError(t('sales.receipts.form.errors.fetch_failed'));
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [id, isRefund]);

    if (loading) return <PageLoading />;
    if (error) return <div className="workspace fade-in"><div className="alert alert-error">{error}</div></div>;
    if (!voucher) return <div className="workspace fade-in"><div className="alert alert-warning">{t('sales.returns.empty')}</div></div>;

    const totalAllocated = voucher.total_allocated ?? null;
    const moneyOrDash = (value) => value !== null && value !== undefined && value !== '' ? formatNumber(value) : '—';

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{voucher.voucher_number}</h1>
                        <span className={`badge ${voucher.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                            {voucher.status === 'posted' ? (
                                <><CheckCircle size={12} style={{ marginLeft: '4px' }} /> {t('sales.receipts.status.posted')}</>
                            ) : (
                                <><FileText size={12} style={{ marginLeft: '4px' }} /> {t('sales.receipts.status.draft')}</>
                            )}
                        </span>
                    </div>
                    <p className="workspace-subtitle">
                        {isRefund ? t('sales.payments.details.subtitle') : t('sales.receipts.details.subtitle')} {voucher.customer_name}
                    </p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        <Printer size={18} style={{ marginLeft: '8px' }} />
                        {t('sales.receipts.details.print')}
                    </button>

                </div>
            </div>

            <div className="section-card mb-6">
                <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '32px', marginBottom: '40px' }}>
                    <div style={{
                        padding: '20px',
                        background: isRefund ? 'rgba(239, 68, 68, 0.05)' : 'rgba(16, 185, 129, 0.05)',
                        borderRadius: '12px',
                        border: `1px solid ${isRefund ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)'}`
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                            <User size={18} className={isRefund ? "text-danger" : "text-success"} />
                            <h4 style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>{t('sales.receipts.table.customer')}</h4>
                        </div>
                        <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: isRefund ? 'var(--danger)' : 'var(--success)' }}>{voucher.customer_name}</div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <Calendar size={16} className="text-muted" />
                                <span className="text-secondary">{t('sales.receipts.table.date')}</span>
                            </div>
                            <span className="font-medium">{formatShortDate(voucher.voucher_date)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <CreditCard size={16} className="text-muted" />
                                <span className="text-secondary">{t('sales.receipts.table.payment_method')}</span>
                            </div>
                            <span className="badge badge-secondary" style={{ fontSize: '13px' }}>
                                {voucher.payment_method === 'cash' ? t('sales.receipts.payment_methods.cash') :
                                    voucher.payment_method === 'bank' ? t('sales.receipts.payment_methods.bank') :
                                        t('sales.receipts.payment_methods.check')}
                            </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span className="text-secondary">{t('sales.receipts.table.amount')}</span>
                            <span style={{ fontSize: '1.4rem', fontWeight: '800', color: isRefund ? 'var(--danger)' : 'var(--success)' }}>
                                {isRefund ? '-' : '+'}{formatNumber(voucher.amount)} <small>{currency}</small>
                            </span>
                        </div>
                    </div>
                </div>

                {(voucher.check_number || voucher.reference) && (
                    <div style={{ padding: '20px', background: 'var(--bg-main)', borderRadius: '12px', border: '1px solid var(--border-color)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '32px', marginBottom: '40px' }}>
                        {voucher.check_number && (
                            <div>
                                <div className="text-secondary text-xs font-bold mb-1" style={{ textTransform: 'uppercase' }}>{t('sales.receipts.form.check_number')}</div>
                                <div className="font-medium" style={{ fontSize: '15px' }}>{voucher.check_number}</div>
                            </div>
                        )}
                        {voucher.check_date && (
                            <div>
                                <div className="text-secondary text-xs font-bold mb-1" style={{ textTransform: 'uppercase' }}>{t('sales.receipts.form.check_date')}</div>
                                <div className="font-medium" style={{ fontSize: '15px' }}>{formatShortDate(voucher.check_date)}</div>
                            </div>
                        )}
                        {voucher.reference && (
                            <div>
                                <div className="text-secondary text-xs font-bold mb-1" style={{ textTransform: 'uppercase' }}>{t('sales.receipts.details.reference')}</div>
                                <div className="font-medium" style={{ fontSize: '15px' }}>{voucher.reference}</div>
                            </div>
                        )}
                    </div>
                )}

                <div style={{ marginTop: '24px' }}>
                    <h3 className="section-title">
                        {t('sales.receipts.form.allocation_title')}
                    </h3>

                    {voucher.allocations && voucher.allocations.length > 0 ? (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('sales.receipts.details.allocation_table.invoice_number')}</th>
                                        <th style={{ textAlign: 'left' }}>{t('sales.receipts.details.allocation_table.allocated_amount')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {voucher.allocations.map((alloc, index) => (
                                        <tr key={index} onClick={() => navigate(`/sales/invoices/${alloc.invoice_id}`)} className="hover-row" style={{ cursor: 'pointer' }}>
                                            <td className="font-medium text-primary">{alloc.invoice_number}</td>
                                            <td style={{ textAlign: 'left' }} className={`font-bold ${isRefund ? 'text-danger' : 'text-success'}`}>
                                                {isRefund ? '-' : '+'}{formatNumber(alloc.allocated_amount)} <small>{currency}</small>
                                            </td>
                                        </tr>
                                    ))}
                                    <tr style={{ background: 'var(--bg-main)', fontWeight: 'bold' }}>
                                        <td>{t('sales.receipts.form.summary.allocated')}</td>
                                        <td style={{ textAlign: 'left' }} className={isRefund ? "text-danger" : "text-success"}>
                                            {isRefund ? '-' : '+'}{moneyOrDash(totalAllocated)} <small>{currency}</small>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div style={{ padding: '48px', textAlign: 'center', background: 'var(--bg-main)', borderRadius: '12px', border: '1px dashed var(--border-color)', color: 'var(--text-secondary)' }}>
                            <Info size={32} style={{ margin: '0 auto 16px', opacity: 0.5 }} />
                            <p>{t('sales.receipts.details.no_allocation')}</p>
                        </div>
                    )}
                </div>

                {voucher.notes && (
                    <div style={{ marginTop: '40px', padding: '24px', background: 'rgba(37, 99, 235, 0.05)', borderRadius: '12px', border: '1px solid rgba(37, 99, 235, 0.1)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                            <FileText size={16} className="text-primary" />
                            <h4 style={{ fontSize: '14px', margin: 0 }}>{t('sales.receipts.form.notes')}</h4>
                        </div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', margin: 0, whiteSpace: 'pre-wrap' }}>{voucher.notes}</p>
                    </div>
                )}
            </div>
        </div>
    );
}

export default ReceiptDetails;
