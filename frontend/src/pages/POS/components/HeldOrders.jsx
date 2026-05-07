import React, { useState, useEffect } from 'react';
import { Clock, Package, User, Trash2, Play, X } from 'lucide-react';
import api from '../../../utils/api';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../../context/ToastContext';
import { formatDateTime } from '../../../utils/dateUtils';
import { formatNumber } from '../../../utils/format';
import { Spinner } from '../../../components/common/LoadingStates'


const HeldOrders = ({ onResume, onClose }) => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [heldOrders, setHeldOrders] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetchHeldOrders();
    }, []);

    const fetchHeldOrders = async () => {
        try {
            const res = await api.get('/pos/orders/held');
            setHeldOrders(res.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleResume = async (orderId) => {
        try {
            const res = await api.post(`/pos/orders/${orderId}/resume`);
            onResume(res.data);
            showToast(t('pos.order_resumed'), 'success');
        } catch (err) {
            showToast(t('common.error'), 'error');
        }
    };

    const handleCancel = async (orderId) => {
        const confirmed = window.confirm(t('pos.confirm_cancel_held'));

        if (!confirmed) {
            return;
        }

        try {
            await api.delete(`/pos/orders/${orderId}/cancel-held`);

            setHeldOrders(heldOrders.filter(o => o.id !== orderId));
            showToast(t('pos.order_cancelled'), 'success');
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const formatTime = (dateStr) => {
        const date = new Date(dateStr);
        return formatDateTime(date);
    };

    return (
        <div className="held-orders-modal">
            <div className="held-orders-content">
                <div className="held-orders-header">
                    <h3><Clock size={20} /> {t('pos.held_orders')}</h3>
                    <button className="close-btn" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                {loading ? (
                    <div className="loading-state">
                        <Spinner size="sm"/>
                    </div>
                ) : heldOrders.length === 0 ? (
                    <div className="empty-state">
                        <Package size={48} />
                        <p>{t('pos.no_held_orders')}</p>
                    </div>
                ) : (
                    <div className="held-orders-list">
                        {heldOrders.map(order => (
                            <div key={order.id} className="held-order-card">
                                <div className="order-info">
                                    <div className="order-number">#{order.order_number}</div>
                                    <div className="order-meta">
                                        <span><User size={14} /> {order.customer_name}</span>
                                        <span><Clock size={14} /> {formatTime(order.created_at)}</span>
                                        <span><Package size={14} /> {order.items_count} {t('pos.items')}</span>
                                    </div>
                                    <div className="order-total">
                                        {formatNumber(order.total_amount)} {t('common.currency')}
                                    </div>
                                </div>
                                <div className="order-actions">
                                    <button
                                        className="btn btn-success btn-sm"
                                        onClick={() => handleResume(order.id)}
                                    >
                                        <Play size={16} /> {t('pos.resume')}
                                    </button>
                                    <button
                                        className="btn btn-error btn-sm"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleCancel(order.id);
                                        }}
                                        title={t('common.delete')}
                                    >
                                        <Trash2 size={16} />
                                        <span>{t('common.delete')}</span>
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default HeldOrders;
