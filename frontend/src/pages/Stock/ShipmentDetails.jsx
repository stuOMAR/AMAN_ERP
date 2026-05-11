import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const ShipmentDetails = () => {
    const { t } = useTranslation();
    const { id } = useParams();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const [shipment, setShipment] = useState(null);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);

    useEffect(() => {
        fetchDetails();
    }, [id]);

    const fetchDetails = async () => {
        try {
            const res = await inventoryAPI.getShipmentDetails(id);
            setShipment(res.data);
        } catch (err) {
            showToast(t('stock.shipments.validation.error_load_details'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleDispatch = async () => {
        if (!window.confirm(t('stock.shipments.details.dispatch_confirm', 'هل تريد شحن هذه الشحنة؟'))) return;
        setActionLoading(true);
        try {
            await inventoryAPI.dispatchShipment(id);
            showToast(t('stock.shipments.details.dispatch_success', 'تم شحن الشحنة بنجاح'), 'success');
            fetchDetails();
        } catch (err) {
            showToast(err.response?.data?.detail || t('stock.shipments.validation.error_dispatch', 'فشل شحن الشحنة'), 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const handleConfirm = async () => {
        if (!window.confirm(t('stock.shipments.incoming_page.validation.confirm_dialog'))) return;
        setActionLoading(true);
        try {
            await inventoryAPI.confirmShipment(id);
            showToast(t('stock.shipments.incoming_page.validation.success_confirm'), 'success');
            fetchDetails();
        } catch (err) {
            showToast(err.response?.data?.detail || t('stock.shipments.incoming_page.validation.error_confirm'), 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const handleCancel = async () => {
        if (!window.confirm(t('stock.shipments.incoming_page.validation.cancel_dialog'))) return;
        setActionLoading(true);
        try {
            await inventoryAPI.cancelShipment(id);
            showToast(t('stock.shipments.incoming_page.validation.success_cancel'), 'success');
            fetchDetails();
        } catch (err) {
            showToast(err.response?.data?.detail || t('stock.shipments.incoming_page.validation.error_cancel'), 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const getStatusBadge = (status) => {
        const styles = {
            pending: { bg: '#FEF3C7', color: '#D97706', label: t('stock.shipments.status.pending') },
            dispatched: { bg: '#DBEAFE', color: '#2563EB', label: t('stock.shipments.status.dispatched', 'تم الشحن') },
            received: { bg: '#D1FAE5', color: '#059669', label: t('stock.shipments.status.received') },
            cancelled: { bg: '#FEE2E2', color: '#DC2626', label: t('stock.shipments.status.cancelled') }
        };
        const s = styles[status] || styles.pending;
        return (
            <span style={{
                background: s.bg,
                color: s.color,
                padding: '6px 16px',
                borderRadius: '16px',
                fontSize: '14px',
                fontWeight: '600'
            }}>
                {s.label}
            </span>
        );
    };

    if (loading) return <PageLoading />;
    if (!shipment) return <div className="p-8 text-center text-danger">{t('stock.shipments.not_found')}</div>;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🚚 {t('stock.shipments.view')} {shipment.shipment_ref}</h1>
                    <p className="workspace-subtitle">{t('stock.shipments.subtitle')}</p>
                </div>
                <div className="header-actions">
                    {getStatusBadge(shipment.status)}
                    <button className="btn btn-secondary" onClick={() => navigate('/stock/shipments')}>
                        {t('common.back')}
                    </button>
                </div>
            </div>

            {/* Action Buttons */}
            {shipment.status === 'pending' && (
                <div className="section-card" style={{ marginBottom: '20px', display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                    <button
                        className="btn btn-secondary"
                        onClick={handleCancel}
                        disabled={actionLoading}
                    >
                        {t('stock.shipments.incoming_page.actions.reject')}
                    </button>
                    <button
                        className="btn btn-primary"
                        style={{ background: '#2563EB' }}
                        onClick={handleDispatch}
                        disabled={actionLoading}
                    >
                        🚚 {t('stock.shipments.details.dispatch', 'شحن')}
                    </button>
                </div>
            )}

            {shipment.status === 'dispatched' && (
                <div className="section-card" style={{ marginBottom: '20px', display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                    <button
                        className="btn btn-primary"
                        style={{ background: '#059669' }}
                        onClick={handleConfirm}
                        disabled={actionLoading}
                    >
                        ✅ {t('stock.shipments.incoming_page.actions.confirm')}
                    </button>
                </div>
            )}

            {/* Info Cards */}
            <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('stock.shipments.form.from_warehouse')}</div>
                    <div className="metric-value" style={{ fontSize: '18px' }}>📍 {shipment.source_warehouse}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('stock.shipments.form.to_warehouse')}</div>
                    <div className="metric-value" style={{ fontSize: '18px' }}>🎯 {shipment.destination_warehouse}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('stock.shipments.table.date')}</div>
                    <div className="metric-value" style={{ fontSize: '16px' }}>
                        {formatShortDate(shipment.created_at)}
                    </div>
                </div>
                {shipment.shipped_at && (
                    <div className="metric-card" style={{ borderRight: '4px solid #2563EB' }}>
                        <div className="metric-label">{t('stock.shipments.status.dispatched', 'تم الشحن')}</div>
                        <div className="metric-value" style={{ fontSize: '16px', color: '#2563EB' }}>
                            {formatShortDate(shipment.shipped_at)}
                        </div>
                    </div>
                )}
                {shipment.received_at && (
                    <div className="metric-card" style={{ borderRight: '4px solid #059669' }}>
                        <div className="metric-label">{t('stock.shipments.status.received')}</div>
                        <div className="metric-value" style={{ fontSize: '16px', color: '#059669' }}>
                            {formatShortDate(shipment.received_at)}
                        </div>
                    </div>
                )}
            </div>

            {/* Items */}
            <div className="section-card">
                <h3 className="section-title">📦 {t('stock.shipments.form.shipped_products')}</h3>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('stock.details.table.product_code')}</th>
                            <th>{t('stock.details.table.product_name')}</th>
                            <th>{t('stock.shipments.form.quantity')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(shipment.items || []).map((item, idx) => (
                            <tr key={idx}>
                                <td className="text-muted">{item.product_code}</td>
                                <td className="font-medium">{item.product_name}</td>
                                <td className="font-bold">{item.quantity}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Notes */}
            {shipment.notes && (
                <div className="section-card" style={{ marginTop: '20px' }}>
                    <h3 className="section-title">📝 {t('stock.shipments.form.notes')}</h3>
                    <p>{shipment.notes}</p>
                </div>
            )}

            {/* Footer */}
            <div style={{ marginTop: '20px', display: 'flex', gap: '16px', fontSize: '13px', color: 'var(--text-muted)' }}>
                <span>{t('stock.shipments.incoming_page.by_user', { user: shipment.created_by_name })}</span>
                {shipment.received_by_name && <span>• {t('stock.shipments.status.received')} {t('common.by')}: {shipment.received_by_name}</span>}
            </div>
        </div>
    );
};

export default ShipmentDetails;
