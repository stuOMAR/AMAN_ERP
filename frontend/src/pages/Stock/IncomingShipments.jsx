import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { toastEmitter } from '../../utils/toastEmitter';

import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const IncomingShipments = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [shipments, setShipments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchIncoming();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchIncoming = async () => {
        try {
            setLoading(true);
            const res = await inventoryAPI.getIncomingShipments({ branch_id: currentBranch?.id });
            setShipments(res.data);
        } catch (err) {
            console.error("Failed to load incoming shipments", err);
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleConfirm = async (id) => {
        if (!window.confirm(t('stock.shipments.incoming_page.validation.confirm_dialog'))) return;

        try {
            await inventoryAPI.confirmShipment(id);
            toastEmitter.emit(t('stock.shipments.incoming_page.validation.success_confirm'), 'success');
            fetchIncoming();
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('stock.shipments.incoming_page.validation.error_confirm'), 'error');
        }
    };

    const handleCancel = async (id) => {
        if (!window.confirm(t('stock.shipments.incoming_page.validation.cancel_dialog'))) return;

        try {
            await inventoryAPI.cancelShipment(id);
            toastEmitter.emit(t('stock.shipments.incoming_page.validation.success_cancel'), 'success');
            fetchIncoming();
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('stock.shipments.incoming_page.validation.error_cancel'), 'error');
        }
    };

    if (initialLoad) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📥 {t('stock.shipments.incoming_page.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.shipments.incoming_page.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <Link to="/stock/shipments" className="btn btn-secondary">
                        {t('stock.shipments.incoming_page.back_to_shipments')}
                    </Link>
                </div>
            </div>

            {!currentBranch ? (
                <div className="section-card" style={{ textAlign: 'center', padding: '48px' }}>
                    <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>🏢</div>
                    <h3 style={{ fontWeight: '600', marginBottom: '8px' }}>{t('common.select_branch_first')}</h3>
                    <p className="text-muted">{t('common.select_branch_to_see_incoming')}</p>
                </div>
            ) : shipments.length === 0 ? (
                <div className="section-card" style={{ textAlign: 'center', padding: '48px' }}>
                    <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>📭</div>
                    <h3 style={{ fontWeight: '600', marginBottom: '8px' }}>{t('stock.shipments.incoming_page.empty_title')}</h3>
                    <p className="text-muted">{t('stock.shipments.incoming_page.empty_subtitle')}</p>
                </div>
            ) : (
                <div style={{ display: 'grid', gap: '20px' }}>
                    {shipments.map(s => (
                        <div key={s.id} className="section-card" style={{ borderRight: '4px solid #F59E0B' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                                <div>
                                    <h3 style={{ fontWeight: '700', color: 'var(--primary)', marginBottom: '4px' }}>
                                        🚚 {s.shipment_ref}
                                    </h3>
                                    <p className="text-muted" style={{ fontSize: '14px' }}>
                                        {t('stock.shipments.incoming_page.from_to', { source: s.source_warehouse, dest: s.destination_warehouse })}
                                    </p>
                                    <p className="text-muted" style={{ fontSize: '12px' }}>
                                        {t('stock.shipments.incoming_page.by_user', { user: s.created_by_name })} • {formatShortDate(s.created_at)}
                                    </p>
                                </div>
                                <span style={{
                                    background: '#FEF3C7',
                                    color: '#D97706',
                                    padding: '6px 14px',
                                    borderRadius: '16px',
                                    fontSize: '13px',
                                    fontWeight: '600'
                                }}>
                                    {t('stock.shipments.incoming_page.waiting_confirmation')}
                                </span>
                            </div>

                            {/* Items */}
                            <div style={{ background: 'var(--bg-secondary)', borderRadius: '8px', padding: '12px', marginBottom: '16px' }}>
                                <table className="data-table" style={{ marginBottom: 0 }}>
                                    <thead>
                                        <tr>
                                            <th>{t('stock.shipments.incoming_page.table.product')}</th>
                                            <th>{t('stock.shipments.incoming_page.table.quantity')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(s.items || []).map((item, idx) => (
                                            <tr key={idx}>
                                                <td>{item.product_name}</td>
                                                <td className="font-bold">{item.quantity}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Actions */}
                            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                                <button
                                    className="btn btn-secondary"
                                    onClick={() => handleCancel(s.id)}
                                >
                                    {t('stock.shipments.incoming_page.actions.reject')}
                                </button>
                                <button
                                    className="btn btn-primary"
                                    style={{ background: '#059669' }}
                                    onClick={() => handleConfirm(s.id)}
                                >
                                    {t('stock.shipments.incoming_page.actions.confirm')}
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default IncomingShipments;
