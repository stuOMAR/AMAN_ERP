import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { salesAPI } from '../../utils/api';
import { getCurrency, hasPermission } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../../utils/format';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'


const SalesReturnDetails = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const { id } = useParams();
    const navigate = useNavigate();
    const currency = getCurrency();
    const [ret, setRet] = useState(null);
    const [loading, setLoading] = useState(true);
    const [approving, setApproving] = useState(false);
    const [cancelling, setCancelling] = useState(false);

    useEffect(() => {
        fetchData();
    }, [id]);

    const fetchData = async () => {
        try {
            const response = await salesAPI.getReturn(id);
            setRet(response.data);
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleApprove = async () => {
        if (!window.confirm(t('sales.returns.details.confirm_approve'))) return;

        try {
            setApproving(true);
            await salesAPI.approveReturn(id);
            showToast(t('sales.returns.details.success_approve'), 'success');
            fetchData();
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setApproving(false);
        }
    };

    const handleCancel = async () => {
        if (!window.confirm(t('common.confirm_cancel', 'هل أنت متأكد من الإلغاء؟'))) return;

        try {
            setCancelling(true);
            await salesAPI.cancelReturn(id);
            showToast(t('common.success'), 'success');
            fetchData();
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setCancelling(false);
        }
    };

    if (loading) return <div className="p-4 text-center"><PageLoading /></div>;
    if (!ret) return <div className="p-4 text-center text-red-500">{t('sales.returns.empty')}</div>;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div className="flex items-center gap-3">
                        <h1 className="workspace-title">{t('sales.returns.details.title')} #{ret.return_number}</h1>
                        <span className={`status-badge ${ret.status}`}>
                            {ret.status === 'approved' ? t('sales.returns.status.approved') :
                                ret.status === 'draft' ? t('sales.returns.status.draft') :
                                    ret.status === 'cancelled' ? t('sales.returns.status.cancelled') : ret.status}
                        </span>
                    </div>
                    <p className="workspace-subtitle">{t('sales.returns.details.date')}: {formatShortDate(ret.return_date)}</p>
                </div>
                <div className="header-actions">
                    <button onClick={() => window.print()} className="btn btn-secondary">
                        🖨️ {t('sales.returns.details.print')}
                    </button>
                    {ret.status === 'draft' && (
                        <button
                            onClick={handleApprove}
                            disabled={approving}
                            className="btn btn-primary"
                        >
                            {approving ? t('sales.returns.details.approving') : '✅ ' + t('sales.returns.details.approve')}
                        </button>
                    )}
                    {hasPermission('sales.approve_return') && ret.status !== 'cancelled' && (
                        <button
                            onClick={handleCancel}
                            disabled={cancelling}
                            className="btn btn-danger"
                        >
                            {cancelling ? t('common.loading', '...') : t('common.cancel')}
                        </button>
                    )}
                    <button onClick={() => navigate('/sales/returns')} className="btn btn-secondary">
                        {t('sales.returns.details.back_to_list')}
                    </button>
                </div>
            </div>

            <div className="card">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('sales.returns.details.customer')}:</h4>
                        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{ret.customer_name}</div>
                    </div>
                    <div style={{ textAlign: 'left' }}>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('sales.returns.details.original_invoice')}:</h4>
                        <div>{ret.invoice_number || t('sales.returns.details.not_linked')}</div>
                    </div>
                </div>

                <div className="invoice-items-container" style={{ border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '20%' }}>{t('sales.quotations.form.items.product')}</th>
                                <th style={{ width: '15%' }}>{t('sales.quotations.form.items.description')}</th>
                                <th style={{ width: '10%', textAlign: 'center' }}>{t('sales.quotations.form.items.quantity')}</th>
                                <th style={{ width: '12%' }}>{t('sales.quotations.form.items.price')}</th>
                                <th style={{ width: '10%' }}>{t('sales.quotations.form.items.tax')}</th>
                                <th style={{ width: '13%' }}>{t('sales.quotations.form.items.total')}</th>
                                <th style={{ width: '20%' }}>{t('sales.returns.details.reason')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {ret.items.map((item, index) => (
                                <tr key={index}>
                                    <td className="font-medium">{item.product_name || t('common.service')}</td>
                                    <td style={{ color: 'var(--text-secondary)' }}>{item.description}</td>
                                    <td style={{ textAlign: 'center' }}>{formatNumber(item.quantity, 0)}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(item.unit_price)} <small>{ret.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{item.tax_rate}%</td>
                                    <td style={{ textAlign: 'left' }} className="font-bold">{formatNumber(item.total)} <small>{ret.currency || currency}</small></td>
                                    <td>{item.reason || '-'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '32px' }}>
                    <div style={{ flex: 1, maxWidth: '500px' }}>
                        <h4 style={{ marginBottom: '8px' }}>{t('sales.returns.details.notes')}:</h4>
                        <p style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{ret.notes || t('sales.returns.details.no_notes')}</p>
                    </div>

                    <div style={{ width: '300px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.quotations.details.subtotal')}</span>
                            <span>{formatNumber(ret.subtotal)} <small>{ret.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.quotations.details.tax')}</span>
                            <span>{formatNumber(ret.tax_amount)} <small>{ret.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.2rem', color: 'var(--primary)' }}>
                            <span>{t('sales.quotations.details.grand_total')}</span>
                            <span>{formatNumber(ret.total)} <small>{ret.currency || currency}</small></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SalesReturnDetails;
