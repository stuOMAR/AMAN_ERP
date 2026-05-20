import React, { useState, useEffect } from 'react';
import { RotateCcw, Search, Check, X } from 'lucide-react';
import api from '../../../utils/api';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../../context/ToastContext';
import { formatShortDate } from '../../../utils/dateUtils';
import { formatNumber } from '../../../utils/format';
import { Spinner } from '../../../components/common/LoadingStates';
import useInvoiceCalc from '../../../hooks/useInvoiceCalc';


const POSReturns = ({ onClose, onComplete }) => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [step, setStep] = useState(1); // 1: search, 2: select items, 3: confirm
    const [orderNumber, setOrderNumber] = useState('');
    const [order, setOrder] = useState(null);
    const [items, setItems] = useState([]);
    const [selectedItems, setSelectedItems] = useState([]);
    const [refundMethod, setRefundMethod] = useState('cash');
    const [notes, setNotes] = useState('');
    const [loading, setLoading] = useState(false);

    const searchOrder = async () => {
        if (!orderNumber.trim()) return;
        setLoading(true);
        try {
            // Search by order number
            const res = await api.get(`/pos/orders/${orderNumber}/details`);
            setOrder(res.data.order);
            setItems(res.data.items.map(item => ({
                ...item,
                returnQty: 0,
                maxQty: item.quantity
            })));
            setStep(2);
        } catch (err) {
            showToast(t('pos.order_not_found'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const { totals: backendTotals, previewDebounced } = useInvoiceCalc();

    // Stream selected return items to backend for authoritative total
    useEffect(() => {
        const selectedLines = items.filter(i => i.returnQty > 0);
        if (selectedLines.length > 0) {
            previewDebounced({
                lines: selectedLines.map(i => ({
                    product_id: i.product_id || null,
                    quantity: String(i.returnQty),
                    unit_price: String(i.unit_price || '0'),
                    tax_rate: i.tax_rate != null ? String(i.tax_rate) : null,
                    discount: '0',
                })),
                currency: order?.currency || 'SAR',
            });
        }
    }, [items, order, previewDebounced]);



    const handleSubmit = async () => {
        const returnItems = items.filter(i => i.returnQty > 0).map(i => ({
            item_id: i.id,
            quantity: i.returnQty,
            reason: ''
        }));

        if (returnItems.length === 0) {
            showToast(t('pos.select_items_to_return'), 'warning');
            return;
        }

        setLoading(true);
        try {
            const res = await api.post(`/pos/orders/${order.id}/return`, {
                order_id: order.id,
                items: returnItems,
                refund_method: refundMethod,
                notes: notes
            });
            showToast(t('pos.return_success'), 'success');
            onComplete?.(res.data);
            onClose();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="returns-modal">
            <div className="returns-content">
                <div className="returns-header">
                    <h3><RotateCcw size={20} /> {t('pos.returns')}</h3>
                    <button className="close-btn" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                {step === 1 && (
                    <div className="search-step">
                        <p className="step-desc">{t('pos.enter_order_number')}</p>
                        <div className="search-box">
                            <input
                                type="text"
                                value={orderNumber}
                                onChange={(e) => setOrderNumber(e.target.value)}
                                placeholder={t('pos.order_number')}
                                onKeyPress={(e) => e.key === 'Enter' && searchOrder()}
                                autoFocus
                            />
                            <button
                                className="btn btn-primary"
                                onClick={searchOrder}
                                disabled={loading}
                            >
                                {loading ? (
                                    <Spinner size="sm"/>
                                ) : (
                                    <>
                                        <Search size={18} />
                                        <span>{t('common.search')}</span>
                                    </>
                                )}
                            </button>
                        </div>
                    </div>
                )}

                {step === 2 && order && (
                    <div className="select-items-step">
                        <div className="order-summary">
                            <span>#{order.order_number}</span>
                            <span>{order.customer_name}</span>
                            <span>{formatShortDate(order.created_at)}</span>
                        </div>

                        <div className="items-list">
                            {items.map(item => (
                                <div key={item.id} className="return-item">
                                    <div className="item-info">
                                        <span className="item-name">{item.name}</span>
                                        <span className="item-price">{item.unit_price} × {item.quantity}</span>
                                    </div>
                                    <div className="item-qty-controls">
                                        <button onClick={() => updateReturnQty(item.id, -1)}>-</button>
                                        <span className={item.returnQty > 0 ? 'has-qty' : ''}>
                                            {item.returnQty}
                                        </span>
                                        <button onClick={() => updateReturnQty(item.id, 1)}>+</button>
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="refund-options">
                            <label>{t('pos.refund_method')}</label>
                            <div className="method-buttons">
                                <button
                                    className={`method-btn ${refundMethod === 'cash' ? 'active' : ''}`}
                                    onClick={() => setRefundMethod('cash')}
                                >
                                    {t('pos.cash')}
                                </button>
                                <button
                                    className={`method-btn ${refundMethod === 'card' ? 'active' : ''}`}
                                    onClick={() => setRefundMethod('card')}
                                >
                                    {t('pos.card')}
                                </button>
                            </div>
                        </div>

                        <textarea
                            placeholder={t('pos.return_notes')}
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            rows={2}
                        />

                        <div className="return-summary">
                            <div className="total-refund">
                                <span>{t('pos.refund_amount')}</span>
                                <span className="amount">{backendTotals ? formatNumber(backendTotals.grandTotal) : '—'} {t('common.currency')}</span>
                            </div>
                        </div>

                        <div className="action-buttons">
                            <button className="btn btn-ghost" onClick={() => setStep(1)}>
                                {t('common.back')}
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={handleSubmit}
                                disabled={loading || !backendTotals || backendTotals.grandTotal === '0.00'}
                            >
                                {loading ? (
                                    <Spinner size="sm"/>
                                ) : (
                                    <><Check size={18} /> {t('pos.confirm_return')}</>
                                )}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default POSReturns;
