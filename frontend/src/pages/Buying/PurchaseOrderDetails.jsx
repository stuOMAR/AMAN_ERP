import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { purchasesAPI } from '../../utils/api';
import { getCurrency, hasPermission } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../../utils/format';
import '../../components/ModuleStyles.css';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'


function PurchaseOrderDetails() {
    const { t } = useTranslation();
    const { id } = useParams();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const [order, setOrder] = useState(null);
    const [loading, setLoading] = useState(true);
    const [approving, setApproving] = useState(false);
    const currency = getCurrency();

    useEffect(() => {
        fetchOrder();
    }, [id]);

    const fetchOrder = async () => {
        try {
            setLoading(true);
            const response = await purchasesAPI.getOrder(id);
            setOrder(response.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleApprove = async () => {
        if (!window.confirm(t('buying.orders.confirm_approve'))) return;
        try {
            setApproving(true);
            await purchasesAPI.approveOrder(id);
            fetchOrder();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setApproving(false);
        }
    };

    const getStatusBadge = (status) => {
        const styles = {
            draft: { bg: '#f3f4f6', color: '#374151', label: t('buying.orders.status.draft') },
            approved: { bg: '#dbeafe', color: '#1d4ed8', label: t('buying.orders.status.approved') },
            partial: { bg: '#fef3c7', color: '#d97706', label: t('buying.orders.status.partial') },
            received: { bg: '#d1fae5', color: '#059669', label: t('buying.orders.status.received') },
            cancelled: { bg: '#fee2e2', color: '#dc2626', label: t('buying.orders.status.cancelled') }
        };
        const style = styles[status] || styles.draft;
        return (
            <span style={{
                backgroundColor: style.bg,
                color: style.color,
                padding: '6px 16px',
                borderRadius: '16px',
                fontSize: '14px',
                fontWeight: '600'
            }}>
                {style.label}
            </span>
        );
    };

    if (loading) {
        return <PageLoading />;
    }

    if (!order) {
        return <div className="workspace fade-in p-8 text-center">{t('buying.orders.not_found')}</div>;
    }

    const hasRemainingToInvoice = order.items?.some(item => Number(item.remaining_to_invoice || 0) > 0);

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📋 {order.po_number}</h1>
                    <p className="workspace-subtitle">{order.supplier_name}</p>
                </div>
                <div className="header-actions" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {getStatusBadge(order.status)}
                    {order.status === 'draft' && hasPermission('buying.approve') && (
                        <button
                            className="btn btn-success"
                            onClick={handleApprove}
                            disabled={approving}
                        >
                            ✓ {approving ? '...' : t('buying.orders.approve')}
                        </button>
                    )}
                    {(order.status === 'approved' || order.status === 'partial') && hasPermission('buying.receive') && (
                        <button
                            className="btn btn-primary"
                            onClick={() => navigate(`/buying/orders/${id}/receive`)}
                        >
                            📥 {t('buying.orders.receive')}
                        </button>
                    )}
                    {(order.status === 'approved' || order.status === 'partial' || order.status === 'received') && hasPermission('buying.create') && hasRemainingToInvoice && (
                        <button
                            className="btn btn-success"
                            onClick={() => navigate('/buying/invoices/new', { state: { fromOrder: order } })}
                        >
                            🧾 {t('buying.orders.create_invoice')}
                        </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => navigate('/buying/orders')}>
                        {t('common.back')}
                    </button>
                </div>
            </div>

            {/* Order Info */}
            <div className="card mb-4">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
                    <div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('buying.orders.table.date')}</div>
                        <div style={{ fontWeight: '500' }}>{formatShortDate(order.order_date)}</div>
                    </div>
                    {order.expected_date && (
                        <div>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('buying.orders.expected_date')}</div>
                            <div style={{ fontWeight: '500' }}>{formatShortDate(order.expected_date)}</div>
                        </div>
                    )}
                    <div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('buying.orders.table.total')}</div>
                        <div style={{ fontWeight: '600', fontSize: '18px', color: 'var(--primary)' }}>
                            {formatNumber(order.total)} {currency}
                        </div>
                    </div>
                    {/* Financial Summary (New) */}
                    <div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('buying.orders.item.received_value')}</div>
                        {(() => {
                            const receivedValue = order.items?.reduce((sum, item) => sum + ((item.received_quantity || 0) * item.unit_price), 0) || 0;
                            return (
                                <div style={{ fontWeight: '600', fontSize: '18px', color: receivedValue > 0 ? 'var(--success)' : 'var(--text-muted)' }}>
                                    {formatNumber(receivedValue)} {currency}
                                    {receivedValue > 0 && <span style={{ fontSize: '12px', marginRight: '8px', color: 'var(--text-secondary)', fontWeight: 'normal' }}>({t('buying.orders.item.accrued')})</span>}
                                </div>
                            );
                        })()}
                    </div>
                </div>
            </div>

            {/* Items Table */}
            <div className="card">
                <h3 style={{ marginBottom: '16px' }}>{t('buying.orders.items')}</h3>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('buying.orders.item.product')}</th>
                            <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_ordered')}</th>
                            <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_received')}</th>
                            <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_remaining')}</th>
                            <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_to_invoice', 'Remaining to invoice')}</th>
                            <th style={{ textAlign: 'left' }}>{t('buying.orders.item.unit_price')}</th>
                            <th style={{ textAlign: 'left' }}>{t('buying.orders.item.total')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {order.items?.map((item, idx) => {
                            const received = item.received_quantity || 0;
                            const remaining = item.quantity - received;
                            const remainingToInvoice = Number(item.remaining_to_invoice || 0);
                            return (
                                <tr key={idx}>
                                    <td>
                                        <div style={{ fontWeight: '500' }}>{item.product_name || item.description}</div>
                                    </td>
                                    <td style={{ textAlign: 'center' }}>{item.quantity}</td>
                                    <td style={{ textAlign: 'center', color: received > 0 ? 'var(--success)' : 'var(--text-muted)' }}>
                                        {received}
                                    </td>
                                    <td style={{ textAlign: 'center', color: remaining > 0 ? 'var(--warning)' : 'var(--success)' }}>
                                        {remaining}
                                    </td>
                                    <td style={{ textAlign: 'center', color: remainingToInvoice > 0 ? 'var(--warning)' : 'var(--success)' }}>
                                        {remainingToInvoice}
                                    </td>
                                    <td>{formatNumber(item.unit_price)} <small>{currency}</small></td>
                                    <td style={{ fontWeight: '500' }}>{formatNumber(item.total)} <small>{currency}</small></td>
                                </tr>
                            );
                        })}
                    </tbody>
                    <tfoot>
                        <tr>
                            <td colSpan="6" style={{ textAlign: 'left', fontWeight: '600' }}>{t('common.total')}</td>
                            <td style={{ fontWeight: '600', fontSize: '16px' }}>
                                {formatNumber(order.total)} {currency}
                            </td>
                        </tr>
                    </tfoot>
                </table>
            </div>

            {/* Notes */}
            {order.notes && (
                <div className="card mt-4">
                    <h3 style={{ marginBottom: '8px' }}>{t('common.notes')}</h3>
                </div>
            )}

            {/* Related Documents */}
            {order.related_documents && (
                <div className="card mt-4">
                    <h3 style={{ marginBottom: '16px' }}>{t('buying.orders.details.related_docs.title')}</h3>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>

                        {/* 1. Inventory Transactions */}
                        <div style={{ background: 'var(--bg-secondary)', padding: '16px', borderRadius: '8px' }}>
                            <h4 style={{ marginBottom: '12px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                                📦 {t('buying.orders.details.related_docs.inventory')}
                            </h4>
                            {order.related_documents.inventory_transactions?.length > 0 ? (
                                <ul style={{ listStyle: 'none', padding: 0 }}>
                                    {order.related_documents.inventory_transactions.map((tx, idx) => (
                                        <li key={idx} style={{ marginBottom: '8px', fontSize: '14px', display: 'flex', justifyContent: 'space-between' }}>
                                            <span>
                                                <span style={{ fontWeight: 'bold' }}>{tx.quantity}</span> x {tx.product_name}
                                            </span>
                                            <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                                                {formatShortDate(tx.date)}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p style={{ color: 'var(--text-muted)', fontSize: '14px' }}>{t('buying.orders.details.related_docs.no_inventory')}</p>
                            )}
                        </div>

                        {/* 2. Journal Entries (Accruals) */}
                        <div style={{ background: 'var(--bg-secondary)', padding: '16px', borderRadius: '8px' }}>
                            <h4 style={{ marginBottom: '12px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                                📒 {t('buying.orders.details.related_docs.journals')}
                            </h4>
                            {order.related_documents.journal_entries?.length > 0 ? (
                                <ul style={{ listStyle: 'none', padding: 0 }}>
                                    {order.related_documents.journal_entries.map((je, idx) => (
                                        <li key={idx} style={{ marginBottom: '8px', fontSize: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <div>
                                                <div style={{ fontWeight: '500' }}>#{je.entry_number}</div>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{je.description}</div>
                                            </div>
                                            <div style={{ textAlign: 'left' }}>
                                                <div style={{ fontWeight: 'bold' }}>{formatNumber(je.amount)} <small>{currency}</small></div>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{formatShortDate(je.date)}</div>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p style={{ color: 'var(--text-muted)', fontSize: '14px' }}>{t('buying.orders.details.related_docs.no_journals')}</p>
                            )}
                        </div>

                        {/* 3. Invoices */}
                        <div style={{ background: 'var(--bg-secondary)', padding: '16px', borderRadius: '8px' }}>
                            <h4 style={{ marginBottom: '12px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                                🧾 {t('buying.orders.details.related_docs.invoices')}
                            </h4>
                            {order.related_documents.invoices?.length > 0 ? (
                                <ul style={{ listStyle: 'none', padding: 0 }}>
                                    {order.related_documents.invoices.map((inv, idx) => (
                                        <li key={idx} style={{ marginBottom: '8px', fontSize: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <div>
                                                <div style={{ fontWeight: '500' }}>#{inv.invoice_number}</div>
                                                <span className={`status-badge ${inv.status}`} style={{ fontSize: '10px', padding: '2px 6px' }}>{inv.status}</span>
                                            </div>
                                            <div style={{ textAlign: 'left' }}>
                                                <div style={{ fontWeight: 'bold' }}>{formatNumber(inv.total)} <small>{currency}</small></div>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{formatShortDate(inv.invoice_date)}</div>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p style={{ color: 'var(--text-muted)', fontSize: '14px' }}>{t('buying.orders.details.related_docs.no_invoices')}</p>
                            )}
                        </div>

                    </div>
                </div>
            )}
        </div>
    );
}

export default PurchaseOrderDetails;
