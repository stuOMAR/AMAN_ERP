import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { deliveryOrdersAPI, salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import BackButton from '../../components/common/BackButton'
import DateInput from '../../components/common/DateInput';
import FormField from '../../components/common/FormField';

function DeliveryOrderForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [loading, setLoading] = useState(false)
    const [salesOrders, setSalesOrders] = useState([])
    const [form, setForm] = useState({
        party_id: '', so_id: '', do_date: new Date().toISOString().split('T')[0],
        shipping_date: '', shipping_address: '', shipping_method: '',
        notes: '', lines: []
    })

    useEffect(() => {
        salesAPI.listOrders({ status: 'confirmed', branch_id: currentBranch?.id })
            .then(res => setSalesOrders(res.data))
            .catch(() => showToast(t('common.error'), 'error'))
    }, [currentBranch])

    const handleSOChange = async (soId) => {
        if (!soId) { setForm(f => ({ ...f, so_id: '', party_id: '', lines: [] })); return }
        try {
            const res = await salesAPI.getOrder(soId)
            const so = res.data
            setForm(f => ({
                ...f, so_id: soId, party_id: so.customer_id || so.party_id,
                lines: (so.items || so.lines || []).map(l => ({
                    product_id: l.product_id, quantity: l.quantity - (l.delivered_quantity || 0),
                    unit_price: l.unit_price, tax_rate: l.tax_rate || 0,
                    product_name: l.product_name
                })).filter(l => l.quantity > 0)
            }))
        } catch (err) { showToast(t('common.error'), 'error') }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setLoading(true)
        try {
            const payload = { ...form, branch_id: currentBranch?.id }
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
        setForm(f => ({ ...f, lines: [...f.lines, { product_id: '', quantity: 1, unit_price: 0, tax_rate: 0 }] }))
    }

    const removeLine = (idx) => {
        setForm(f => ({ ...f, lines: f.lines.filter((_, i) => i !== idx) }))
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">🚚 {t('delivery_orders.create_new')}</h1>
            </div>

            <form onSubmit={handleSubmit}>
                <div className="card p-4">
                    <div className="form-grid-3">
                        <FormField label={t('delivery_orders.from_sales_order')}>
                            <select className="form-select" value={form.so_id} onChange={e => handleSOChange(e.target.value)}>
                                <option value="">{t('delivery_orders.manual_entry')}</option>
                                {salesOrders.map(so => (
                                    <option key={so.id} value={so.id}>{so.so_number} - {so.customer_name}</option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label={t('common.date')} required>
                            <DateInput className="form-input" value={form.do_date} onChange={e => setForm(f => ({ ...f, do_date: e.target.value }))} required />
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
                        {!form.so_id && <button type="button" className="btn btn-secondary btn-sm" onClick={addLine}>+ {t('common.add_line')}</button>}
                    </div>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('common.product')}</th>
                                <th>{t('common.quantity')}</th>
                                 <th>{t('common.unit_price')} ({currency})</th>
                                <th>{t('common.tax_rate')}</th>
                                {!form.so_id && <th></th>}
                            </tr>
                        </thead>
                        <tbody>
                            {form.lines.map((line, i) => (
                                <tr key={i}>
                                    <td>{line.product_name || <input type="number" className="form-input" value={line.product_id} onChange={e => updateLine(i, 'product_id', e.target.value)} placeholder={t('common.product_id')} />}</td>
                                    <td><input type="number" className="form-input" min="1" value={line.quantity} onChange={e => updateLine(i, 'quantity', Number(e.target.value))} style={{ width: 80 }} /></td>
                                     <td><input type="number" className="form-input" step="0.01" value={line.unit_price} onChange={e => updateLine(i, 'unit_price', Number(e.target.value))} style={{ width: 120 }} /> <small>{currency}</small></td>
                                    <td><input type="number" className="form-input" step="0.01" value={line.tax_rate} onChange={e => updateLine(i, 'tax_rate', Number(e.target.value))} style={{ width: 80 }} /></td>
                                    {!form.so_id && <td><button type="button" className="btn-icon text-danger" onClick={() => removeLine(i)}>🗑️</button></td>}
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
