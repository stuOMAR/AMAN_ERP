
import React, { useState, useEffect } from 'react';
import { manufacturingAPI, inventoryAPI } from '../../utils/api';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toastEmitter } from '../../utils/toastEmitter';
import {
    FaClipboardList, FaPlus, FaEye, FaTimesCircle
} from 'react-icons/fa';
import '../../components/ModuleStyles.css';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const ProductionOrders = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [orders, setOrders] = useState([]);
    const [products, setProducts] = useState([]);
    const [boms, setBoms] = useState([]);
    const [routes, setRoutes] = useState([]);
    const [warehouses, setWarehouses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);

    // Form Data
    const [formData, setFormData] = useState({
        product_id: '',
        bom_id: '',
        route_id: '',
        quantity: 1,
        start_date: new Date().toISOString().split('T')[0],
        due_date: new Date().toISOString().split('T')[0],
        warehouse_id: '', // Source
        destination_warehouse_id: '',
        notes: ''
    });

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        try {
            setLoading(true);
            const [ordersRes, productsRes, bomsRes, routesRes, whRes] = await Promise.all([
                manufacturingAPI.listOrders(),
                inventoryAPI.listProducts(),
                manufacturingAPI.listBOMs(),
                manufacturingAPI.listRoutes(),
                inventoryAPI.listWarehouses()
            ]);

            setOrders(ordersRes.data);
            const prods = productsRes.data?.products || productsRes.data;
            setProducts(Array.isArray(prods) ? prods : []);
            setBoms(bomsRes.data);
            setRoutes(routesRes.data);
            setWarehouses(whRes.data?.warehouses || whRes.data || []);
            setLoading(false);
        } catch (error) {
            toastEmitter.emit(t('common.error'), 'error');
            setLoading(false);
        }
    };

    // Filter BOMs and Routes based on selected Product
    const filteredBOMs = formData.product_id
        ? boms.filter(b => b.product_id === parseInt(formData.product_id))
        : [];

    const filteredRoutes = formData.product_id
        ? routes.filter(r => r.product_id === parseInt(formData.product_id) || !r.product_id) // Default routes (null product_id) too? Maybe.
        : [];

    const handleProductChange = (e) => {
        const pid = e.target.value;
        setFormData({
            ...formData,
            product_id: pid,
            bom_id: '',
            route_id: ''
        });

        // Auto-select BOM if only one exists
        const productBoms = boms.filter(b => b.product_id === parseInt(pid));
        if (productBoms.length === 1) {
            setFormData(prev => ({ ...prev, bom_id: productBoms[0].id }));
            if (productBoms[0].route_id) {
                setFormData(prev => ({ ...prev, route_id: productBoms[0].route_id }));
            }
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const payload = {
                ...formData,
                product_id: parseInt(formData.product_id),
                bom_id: parseInt(formData.bom_id),
                route_id: formData.route_id ? parseInt(formData.route_id) : null,
                quantity: formData.quantity,
                warehouse_id: formData.warehouse_id ? parseInt(formData.warehouse_id) : null,
                destination_warehouse_id: formData.destination_warehouse_id ? parseInt(formData.destination_warehouse_id) : null,
            };

            await manufacturingAPI.createOrder(payload);
            toastEmitter.emit(t('common.created_successfully'), 'success');
            setShowModal(false);
            fetchData();

            // Reset form
            setFormData({
                product_id: '',
                bom_id: '',
                route_id: '',
                quantity: 1,
                start_date: new Date().toISOString().split('T')[0],
                due_date: new Date().toISOString().split('T')[0],
                warehouse_id: '',
                destination_warehouse_id: '',
                notes: ''
            });

        } catch (error) {
            toastEmitter.emit(t('common.error'), 'error');
        }
    };

    const getStatusBadge = (status) => {
        const classMap = {
            draft: 'badge-ghost',
            planned: 'badge-info',
            confirmed: 'badge-primary',
            in_progress: 'badge-warning',
            completed: 'badge-success',
            cancelled: 'badge-danger'
        };
        return <span className={`badge ${classMap[status] || 'badge-ghost'}`}>{t(`status.${status}`, t(status))}</span>;
    };

    if (loading) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title flex items-center gap-2">
                        <FaClipboardList /> {t('manufacturing.production_orders')}
                    </h1>
                    <p className="workspace-subtitle">{t('manufacturing.production_orders_desc')}</p>
                </div>
                <div className="header-actions">
                    <button
                        onClick={() => setShowModal(true)}
                        className="btn btn-primary"
                    >
                        <FaPlus /> {t('manufacturing.new_order')}
                    </button>
                </div>
            </div>

            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('common.id')}</th>
                            <th>{t('products.product')}</th>
                            <th>{t('manufacturing.bom')}</th>
                            <th>{t('common.quantity')}</th>
                            <th>{t('common.status_title')}</th>
                            <th>{t('common.due_date')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {orders.length === 0 ? (
                            <tr>
                                <td colSpan="7" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                                    {t('no_orders_found')}
                                </td>
                            </tr>
                        ) : (
                            orders.map((order) => (
                                <tr key={order.id}>
                                    <td><span style={{ fontFamily: 'monospace', fontWeight: 700, color: 'var(--primary)' }}>{order.order_number}</span></td>
                                    <td>{order.product_name}</td>
                                    <td style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>{order.bom_name}</td>
                                    <td style={{ fontWeight: 700 }}>
                                        {order.produced_quantity} / {order.quantity}
                                    </td>
                                    <td>{getStatusBadge(order.status)}</td>
                                    <td style={{ fontSize: '13px' }}>{formatDate(order.due_date)}</td>
                                    <td>
                                        <button
                                            className="table-action-btn"
                                            title={t('common.view')}
                                            onClick={() => navigate(`/manufacturing/orders/${order.id}`)}
                                        >
                                            <FaEye />
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {showModal && (
                <div className="modal-overlay">
                    <div className="modal-content max-w-2xl">
                        <div className="modal-header">
                            <h2 className="modal-title">{t('manufacturing.new_order')}</h2>
                            <button onClick={() => setShowModal(false)} className="btn-icon">
                                <FaTimesCircle className="text-gray-500" />
                            </button>
                        </div>
                        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                            <div className="modal-body">
                                <div className="row">
                                    <div className="col-md-12 form-group">
                                        <label className="form-label">{t('products.product')}</label>
                                        <select
                                            className="form-input"
                                            required
                                            value={formData.product_id}
                                            onChange={handleProductChange}
                                        >
                                            <option value="">{t('common.select')}</option>
                                            {products.map(p => (
                                                <option key={p.id} value={p.id}>{p.product_name} ({p.product_code})</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                <div className="row">
                                    <div className="col-md-6 form-group">
                                        <label className="form-label">{t('manufacturing.bom')}</label>
                                        <select
                                            className="form-input"
                                            required
                                            value={formData.bom_id}
                                            onChange={(e) => setFormData({ ...formData, bom_id: e.target.value })}
                                            disabled={!formData.product_id}
                                        >
                                            <option value="">{t('common.select')}</option>
                                            {filteredBOMs.map(b => (
                                                <option key={b.id} value={b.id}>{b.name || b.code} (Yield: {b.yield_quantity})</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="col-md-6 form-group">
                                        <label className="form-label">{t('manufacturing.routing')}</label>
                                        <select
                                            className="form-input"
                                            value={formData.route_id}
                                            onChange={(e) => setFormData({ ...formData, route_id: e.target.value })}
                                        >
                                            <option value="">{t('manufacturing.default_route')}</option>
                                            {filteredRoutes.map(r => (
                                                <option key={r.id} value={r.id}>{r.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                <div className="row">
                                    <div className="col-md-6 form-group">
                                        <label className="form-label">{t('common.quantity')}</label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            min="0"
                                            className="form-input"
                                            required
                                            value={formData.quantity}
                                            onChange={(e) => setFormData({ ...formData, quantity: e.target.value })}
                                        />
                                    </div>
                                    <div className="col-md-6 form-group">
                                        <label className="form-label">{t('common.due_date')}</label>
                                        <input
                                           
                                            className="form-input"
                                            required
                                            value={formatDate(formData.due_date)}
                                            onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                                        />
                                    </div>
                                </div>

                                <div className="row">
                                    <div className="col-md-6 form-group">
                                        <label className="form-label">{t('stock.source_warehouse')}</label>
                                        <select
                                            className="form-input"
                                            value={formData.warehouse_id}
                                            onChange={(e) => setFormData({ ...formData, warehouse_id: e.target.value })}
                                        >
                                            <option value="">{t('common.select')}</option>
                                            {warehouses.map(w => (
                                                <option key={w.id} value={w.id}>{w.name}</option>
                                            ))}
                                        </select>
                                        <small className="text-gray-500">{t('manufacturing.raw_materials_source')}</small>
                                    </div>
                                    <div className="col-md-6 form-group">
                                        <label className="form-label">{t('stock.destination_warehouse')}</label>
                                        <select
                                            className="form-input"
                                            value={formData.destination_warehouse_id}
                                            onChange={(e) => setFormData({ ...formData, destination_warehouse_id: e.target.value })}
                                        >
                                            <option value="">{t('common.select')}</option>
                                            {warehouses.map(w => (
                                                <option key={w.id} value={w.id}>{w.name}</option>
                                            ))}
                                        </select>
                                        <small className="text-gray-500">{t('manufacturing.finished_goods_destination')}</small>
                                    </div>
                                </div>
                                <div className="row">
                                    <div className="col-md-12 form-group">
                                        <label className="form-label">{t('common.notes')}</label>
                                        <textarea
                                            className="form-input"
                                            rows="2"
                                            value={formData.notes}
                                            onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                                        />
                                    </div>
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button
                                    type="button"
                                    onClick={() => setShowModal(false)}
                                    className="btn btn-secondary"
                                >
                                    {t('common.cancel')}
                                </button>
                                <button
                                    type="submit"
                                    className="btn btn-primary"
                                >
                                    {t('common.create')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default ProductionOrders;
