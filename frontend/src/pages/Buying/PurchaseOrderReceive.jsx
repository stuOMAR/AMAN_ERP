import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { purchasesAPI, inventoryAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useTranslation } from 'react-i18next';
import '../../components/ModuleStyles.css';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import Decimal from 'decimal.js';

function PurchaseOrderReceive() {
    const { t } = useTranslation();
    const { id } = useParams();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [order, setOrder] = useState(null);
    const [warehouses, setWarehouses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [selectedWarehouse, setSelectedWarehouse] = useState('');
    const [receiveQtys, setReceiveQtys] = useState({});


    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer)
    }, [id]);

    const fetchData = async () => {
        try {
            setLoading(true);
            const orderRes = await purchasesAPI.getOrder(id);
            setOrder(orderRes.data);

            // Use the PO branch, or fallback to the current context branch
            const branchId = orderRes.data.branch_id || currentBranch?.id;

            const warehousesRes = await inventoryAPI.listWarehouses({ branch_id: branchId });
            setWarehouses(warehousesRes.data || []);

            // Initialize receive quantities
            const initialQtys = {};
            orderRes.data.items?.forEach(item => {
                const remaining = new Decimal(item.quantity || 0).minus(item.received_quantity || 0);
                initialQtys[item.id] = remaining.gt(0) ? remaining.toString() : '0';
            });
            setReceiveQtys(initialQtys);
        } catch (err) {
            showToast(t('common.error_occurred'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleQtyChange = (itemId, value) => {
        // Allow empty string for easier typing
        if (value === '') {
            setReceiveQtys(prev => ({ ...prev, [itemId]: '' }));
            return;
        }

        try {
            const val = new Decimal(value);
            setReceiveQtys(prev => ({
                ...prev,
                [itemId]: val.toString()
            }));
        } catch {
            return;
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!selectedWarehouse) {
            showToast(t('buying.receive.select_warehouse'), 'error');
            return;
        }

        const itemsToReceive = [];
        for (const [lineId, qty] of Object.entries(receiveQtys)) {
            const numericQty = new Decimal(qty || 0);
            if (numericQty.gt(0)) {
                const item = order.items?.find(i => i.id === parseInt(lineId));
                const remaining = item ? new Decimal(item.quantity || 0).minus(item.received_quantity || 0) : new Decimal(0);

                if (numericQty.gt(remaining)) {
                    showToast(`${t('common.error')}: ${t('buying.receive.qty_to_receive')} (${numericQty.toString()}) > ${t('buying.orders.item.qty_remaining')} (${remaining.toString()}) - ${item?.product_name}`, 'error');
                    return;
                }

                itemsToReceive.push({
                    line_id: parseInt(lineId),
                    received_quantity: numericQty.toString()
                });
            }
        }

        if (itemsToReceive.length === 0) {
            showToast(t('buying.receive.no_items'), 'error');
            return;
        }

        try {
            setSubmitting(true);
            await purchasesAPI.receiveOrder(id, {
                items: itemsToReceive,
                warehouse_id: parseInt(selectedWarehouse)
            });
            navigate(`/buying/orders/${id}`);
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const handleReceiveAll = () => {
        const allQtys = {};
        order.items?.forEach(item => {
            const remaining = item.quantity - (item.received_quantity || 0);
            allQtys[item.id] = remaining > 0 ? remaining : 0;
        });
        setReceiveQtys(allQtys);
    };

    if (initialLoad && !order) {
        return <PageLoading />;
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📥 {t('buying.receive.title')}</h1>
                    <p className="workspace-subtitle">{order.po_number} - {order.supplier_name}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => navigate(`/buying/orders/${id}`)}>
                        {t('common.cancel')}
                    </button>
                </div>
            </div>

            <form onSubmit={handleSubmit}>
                {/* Warehouse Selection */}
                <div className="card mb-4">
                    <div className="form-group">
                        <label className="form-label">{t('buying.receive.warehouse')} *</label>
                        <select
                            className="form-select"
                            value={selectedWarehouse}
                            onChange={(e) => setSelectedWarehouse(e.target.value)}
                            required
                            style={{ color: '#1e293b', backgroundColor: '#ffffff' }}
                        >
                            <option value="" style={{ color: '#1e293b' }}>{t('buying.receive.select_warehouse')}</option>
                            {warehouses.map(wh => (
                                <option key={wh.id} value={wh.id} style={{ color: '#1e293b' }}>
                                    {wh.name || wh.warehouse_name}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>

                {/* Items to Receive */}
                <div className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h3>{t('buying.receive.items')}</h3>
                        <button type="button" className="btn btn-sm btn-secondary" onClick={handleReceiveAll}>
                            {t('buying.receive.receive_all')}
                        </button>
                    </div>

                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('buying.orders.item.product')}</th>
                                <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_ordered')}</th>
                                <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_received')}</th>
                                <th style={{ textAlign: 'center' }}>{t('buying.orders.item.qty_remaining')}</th>
                                <th style={{ textAlign: 'center', width: '150px' }}>{t('buying.receive.qty_to_receive')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {order.items?.map((item) => {
                                const received = item.received_quantity || 0;
                                const remaining = item.quantity - received;
                                const receiveQty = receiveQtys[item.id] || 0;

                                return (
                                    <tr key={item.id}>
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
                                        <td>
                                            <input
                                                type="number"
                                                className="form-input"
                                                style={{ textAlign: 'center', width: '100%', backgroundColor: remaining <= 0 ? '#f3f4f6' : '#fff' }}
                                                min="0"
                                                value={receiveQty}
                                                onChange={(e) => handleQtyChange(item.id, e.target.value)}
                                                disabled={remaining <= 0}
                                                placeholder="0"
                                            />
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>

                {/* Submit Button */}
                <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                    <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => navigate(`/buying/orders/${id}`)}
                    >
                        {t('common.cancel')}
                    </button>
                    <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={submitting}
                    >
                        {submitting ? t('common.saving') : t('buying.receive.confirm')}
                    </button>
                </div>
            </form>
        </div>
    );
}

export default PurchaseOrderReceive;
