import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { deliveryOrdersAPI, salesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import BackButton from '../../components/common/BackButton'
import DateInput from '../../components/common/DateInput';
import FormField from '../../components/common/FormField';
import Decimal from 'decimal.js';

function DeliveryOrderForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [salesOrders, setSalesOrders] = useState([])
    const [form, setForm] = useState({
        party_id: '', sales_order_id: '', delivery_date: new Date().toISOString().split('T')[0],
        shipping_date: '', shipping_address: '', shipping_method: '',
        warehouse_id: '', notes: '', lines: []
    })

    useEffect(() => {
        const timer = setTimeout(() => {
            salesAPI.listOrders({ status: 'confirmed', branch_id: currentBranch?.id })
                .then(res => setSalesOrders(res.data))
                .catch(() => showToast(t('common.error'), 'error'))
                .finally(() => setInitialLoad(false))
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const handleSOChange = async (soId) => {
        if (!soId) { setForm(f => ({ ...f, sales_order_id: '', party_id: '', warehouse_id: '', lines: [] })); return }
        try {
            const res = await salesAPI.getOrder(soId)
            const so = res.data
            setForm(f => ({
                ...f,
                sales_order_id: soId,
                party_id: so.customer_id || so.party_id,
                warehouse_id: so.warehouse_id || f.warehouse_id,
                lines: (so.items || so.lines || []).map(l => {
                    const remainingStr = l.remaining_quantity || '0';
                    return {
                        so_line_id: l.id,
                        product_id: l.product_id,
                        ordered_qty: String(l.quantity || remainingStr),
                        delivered_qty: remainingStr,
                        unit: l.unit || '',
                        product_name: l.product_name
                    };
                }).filter(l => {
                    try { return new Decimal(l.delivered_qty || '0').gt(0) } catch { return false }
                })
            }))
        } catch (err) { showToast(t('common.error'), 'error') }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setLoading(true)
        try {
            const payload = {
                delivery_date: form.delivery_date,
                sales_order_id: form.sales_order_id ? parseInt(form.sales_order_id, 10) : null,
                party_id: form.party_id ? parseInt(form.party_id, 10) : null,
                warehouse_id: form.warehouse_id ? parseInt(form.warehouse_id, 10) : null,
                branch_id: currentBranch?.id || null,
                shipping_method: form.shipping_method,
                delivery_address: form.shipping_address,
                notes: form.notes,
                lines: form.lines.map(line => ({
                    product_id: line.product_id ? parseInt(line.product_id, 10) : null,
                    so_line_id: line.so_line_id ? parseInt(line.so_line_id, 10) : null,
                    description: line.description || line.product_name || '',
                    ordered_qty: String(line.ordered_qty || '0'),
                    delivered_qty: String(line.delivered_qty || '0'),
                    unit: line.unit || null,
                })),
            }
            const res = await deliveryOrdersAPI.create(payload)
            showToast(t('delivery_orders.created_success'), 'success')
            navigate(`/sales/delivery-orders/${res.data.id}`)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const updateLine = (idx, field, value) => {
        setForm(f => ({
            ...f, lines: f.lines.map((l, i) => i === idx ? { ...l, [field]: value } : l)
        }))
    }

    const addLine = () => {
        setForm(f => ({ ...f, lines: [...f.lines, { product_id: '', ordered_qty: '0', delivered_qty: '1', unit: '' }] }))
    }

    const removeLine = (idx) => {
        setForm(f => ({ ...f, lines: f.lines.filter((_, i) => i !== idx) }))
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">🚚 {t('delivery_orders.create_new')}</h1>
            </div>

            <form onSubmit={handleSubmit}>
                <div className="card p-4">
                    <div className="form-grid-3">
                        <FormField label={t('delivery_orders.from_sales_order')}>
                            <select className="form-select" value={form.sales_order_id} onChange={e => handleSOChange(e.target.value)}>
                                <option value="">{t('delivery_orders.manual_entry')}</option>
                                {salesOrders.map(so => (
                                    <option key={so.id} value={so.id}>{so.so_number} - {so.customer_name}</option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label={t('common.date')} required>
                            <DateInput className="form-input" value={form.delivery_date} onChange={e => setForm(f => ({ ...f, delivery_date: e.target.value }))} required />
                        </FormField>
                        <FormField label={t('delivery_orders.shipping_date')}>
                            <DateInput className="form-input" value={form.shipping_date} onChange={e => setForm(f => ({ ...f, shipping_date: e.target.value }))} />
                        </FormField>
                    </div>
                    <div className="form-grid-2 mt-3">
                        <FormField label={t('delivery_orders.shipping_address')}>
                            <textarea className="form-input" rows="2" value={form.shipping_address} onChange={e => setForm(f => ({ ...f, shipping_address: e.target.value }))} />
                        </FormField>
                        <FormField label={t('delivery_orders.shipping_method')}>
                            <input type="text" className="form-input" value={form.shipping_method} onChange={e => setForm(f => ({ ...f, shipping_method: e.target.value }))} />
                        </FormField>
                    </div>
                </div>

                <div className="card mt-4 p-4">
                    <div className="flex justify-between items-center mb-3">
                        <h3 className="card-title">{t('common.items')}</h3>
                        {!form.sales_order_id && <button type="button" className="btn btn-secondary btn-sm" onClick={addLine}>+ {t('common.add_line')}</button>}
                    </div>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('common.product')}</th>
                                <th>{t('delivery_orders.ordered_qty')}</th>
                                <th>{t('common.quantity')}</th>
                                {!form.sales_order_id && <th></th>}
                            </tr>
                        </thead>
                        <tbody>
                            {form.lines.map((line, i) => (
                                <tr key={i}>
                                    <td>{line.product_name || <input type="number" className="form-input" value={line.product_id} onChange={e => updateLine(i, 'product_id', e.target.value)} placeholder={t('common.product_id')} />}</td>
                                    <td><input type="text" inputMode="decimal" className="form-input" value={line.ordered_qty} onChange={e => updateLine(i, 'ordered_qty', e.target.value)} style={{ width: 100 }} /></td>
                                    <td><input type="text" inputMode="decimal" className="form-input" min="1" value={line.delivered_qty} onChange={e => updateLine(i, 'delivered_qty', e.target.value)} style={{ width: 100 }} /></td>
                                    {!form.sales_order_id && <td><button type="button" className="btn-icon text-danger" onClick={() => removeLine(i)}>🗑️</button></td>}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div className="mt-4 flex gap-2">
                    <button type="submit" className="btn btn-primary" disabled={loading || form.lines.length === 0}>
                        {loading ? t('common.saving') : t('common.save')}
                    </button>
                    <button type="button" className="btn btn-secondary" onClick={() => navigate('/sales/delivery-orders')}>
                        {t('common.cancel')}
                    </button>
                </div>
            </form>
        </div>
    )
}

export default DeliveryOrderForm
