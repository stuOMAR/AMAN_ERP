import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { purchasesAPI, inventoryAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { useTranslation } from 'react-i18next'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import useInvoiceCalc from '../../hooks/useInvoiceCalc'

function BuyingOrderForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [suppliers, setSuppliers] = useState([])
    const [supplierGroups, setSupplierGroups] = useState([])
    const [products, setProducts] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const [formData, setFormData] = useState({
        supplier_id: '',
        party_site_id: '',
        order_date: new Date().toISOString().split('T')[0],
        expected_date: '',
        notes: ''
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, total: 0 }
    ])

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [suppRes, groupsRes, prodRes] = await Promise.all([
                    inventoryAPI.listSuppliers(),
                    purchasesAPI.listSupplierGroups(),
                    inventoryAPI.listProducts()
                ])
                setSuppliers(suppRes.data)
                setSupplierGroups(groupsRes.data)
                setProducts(prodRes.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
            }
        }
        fetchData()
    }, [])

    const handleAddItem = () => {
        setItems([
            ...items,
            { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, total: 0 }
        ])
    }

    const handleItemChange = (index, field, value) => {
        const newItems = items.map((item, i) => {
            if (i === index) {
                const updatedItem = { ...item }

                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value))
                    if (product) {
                        updatedItem.description = product.item_name || ''
                        // Use last_buying_price if available, otherwise fall back to buying_price
                        updatedItem.unit_price = product.last_buying_price || product.buying_price || 0
                        // Auto-fill tax rate from product data
                        updatedItem.tax_rate = null // Resolved by backend engine

                        // Try applying item-level effect from group
                        const supplier = suppliers.find(s => s.id === parseInt(formData.supplier_id));
                        if (supplier && supplier.group_id) {
                            const group = supplierGroups.find(g => g.id === supplier.group_id);
                            if (group && group.application_scope === 'line' && group.discount_percentage > 0) {
                                if (group.effect_type === 'discount') {
                                    updatedItem.discount_percent = group.discount_percentage;
                                } else if (group.effect_type === 'markup') {
                                    // Markup applied by increasing unit_price
                                    updatedItem.unit_price = updatedItem.unit_price * (1 + (group.discount_percentage / 100));
                                }
                            }
                        }
                    }
                }

                // Calculate discount logic
                const qty = Number(field === 'quantity' ? value : updatedItem.quantity) || 0
                const price = Number(field === 'unit_price' ? value : updatedItem.unit_price) || 0
                let discount = Number(updatedItem.discount) || 0
                let discountPercent = Number(updatedItem.discount_percent) || 0

                if (field === 'discount_percent') {
                    discountPercent = Number(value) || 0
                    discount = (qty * price) * (discountPercent / 100)
                    updatedItem.discount = discount
                } else if (field === 'quantity' || field === 'unit_price') {
                    discount = (qty * price) * (discountPercent / 100)
                    updatedItem.discount = discount
                }

                updatedItem.discount_percent = discountPercent
                updatedItem.discount = discount

                updatedItem[field] = value

                // Recalculate total immediately for UI if needed, but calculateTotals does it on render/submit
                // But we update state, so it's fine.
                // However, item.total is used in render, so we should update it:
                const taxRate = Number(field === 'tax_rate' ? value : updatedItem.tax_rate) || 0
                const subtotal = qty * price
                const taxable = subtotal - discount
                const tax = taxable * (taxRate / 100)
                updatedItem.total = taxable + tax

                return updatedItem
            }
            return item
        })
        setItems(newItems)
    }

    // Backend-powered calculations
    const { totals: backendTotals, previewDebounced, quickCalc } = useInvoiceCalc()

    const calculateTotals = () => {
        // Use backend totals if available
        if (backendTotals) {
            return {
                subtotal: backendTotals.subtotal,
                discount: backendTotals.totalDiscount,
                tax: backendTotals.totalTax,
                total: backendTotals.grandTotal,
            }
        }
        // Fallback to local calculation
        let subtotal = 0;
        let discount = 0;
        let tax = 0;
        let total = 0;

        let globalEffectType = 'discount';
        let globalEffectPercent = 0;

        // Find group effects on total
        const supplier = suppliers.find(s => s.id === parseInt(formData.supplier_id));
        if (supplier && supplier.group_id) {
            const group = supplierGroups.find(g => g.id === supplier.group_id);
            if (group && group.application_scope === 'total' && group.discount_percentage > 0) {
                globalEffectType = group.effect_type;
                globalEffectPercent = Number(group.discount_percentage);
            }
        }

        items.forEach(item => {
            const qty = Number(item.quantity) || 0;
            const price = Number(item.unit_price) || 0;
            const lineDiscount = Number(item.discount) || 0;
            const lineSubtotal = qty * price;

            subtotal += lineSubtotal;
            discount += lineDiscount;
        });

        let totalAfterLineDiscounts = subtotal - discount;
        let globalDiscountAmount = 0;
        let globalMarkupAmount = 0;

        if (globalEffectPercent > 0) {
            if (globalEffectType === 'discount') {
                globalDiscountAmount = totalAfterLineDiscounts * (globalEffectPercent / 100);
            } else if (globalEffectType === 'markup') {
                globalMarkupAmount = totalAfterLineDiscounts * (globalEffectPercent / 100);
            }
        }

        let baseForTax = totalAfterLineDiscounts - globalDiscountAmount + globalMarkupAmount;

        items.forEach(item => {
            const qty = Number(item.quantity) || 0;
            const price = Number(item.unit_price) || 0;
            const lineDiscount = Number(item.discount) || 0;
            const taxRate = Number(item.tax_rate) || 0;

            const weight = (qty * price - lineDiscount) / totalAfterLineDiscounts || 0;
            const itemBase = (qty * price - lineDiscount)
                - (globalDiscountAmount * weight)
                + (globalMarkupAmount * weight);
            tax += itemBase * (taxRate / 100);
        });

        total = baseForTax + tax;

        return {
            subtotal,
            discount: discount + globalDiscountAmount,
            tax,
            total,
            globalEffectType,
            globalEffectPercent,
            globalMarkupAmount
        };
    }

    // Call backend for accurate calculations
    useEffect(() => {
        if (items.length > 0 && items.some(i => i.quantity > 0 && i.unit_price > 0)) {
            previewDebounced({
                lines: items.map(i => ({
                    quantity: Number(i.quantity) || 0,
                    unit_price: Number(i.unit_price) || 0,
                    tax_rate: Number(i.tax_rate) || 0,
                    discount: Number(i.discount) || 0,
                })),
                currency,
            })
        }
    }, [items])

    const handleSubmit = async (e) => {
        e.preventDefault()

        if (!formData.supplier_id) {
            setError(t('buying.orders.form.error_supplier'))
            return
        }
        if (items.some(item => !item.product_id)) {
            setError(t('buying.orders.form.error_product'))
            return
        }
        if (!formData.order_date) {
            setError(t('buying.orders.form.error_dates'))
            return
        }

        setLoading(true)
        setError(null)
        try {
            const totals = calculateTotals();
            const payload = {
                supplier_id: parseInt(formData.supplier_id),
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                branch_id: currentBranch?.id,
                order_date: formData.order_date,
                expected_date: formData.expected_date || null,
                notes: formData.notes,
                effect_type: totals.globalEffectType,
                effect_percentage: totals.globalEffectPercent,
                markup_amount: totals.globalMarkupAmount,
                items: items.map(item => ({
                    product_id: parseInt(item.product_id),
                    description: item.description || '',
                    quantity: String(item.quantity || 0),
                    unit_price: String(item.unit_price || 0),
                    discount: String(item.discount || 0),
                    tax_rate: String(item.tax_rate || 0),
                    markup: 0 // Handled at line level unit_price
                }))
            }
            await purchasesAPI.createOrder(payload)
            navigate('/buying/orders')
        } catch (err) {
            const detail = err.response?.data?.detail
            if (typeof detail === 'string') {
                setError(detail)
            } else if (Array.isArray(detail)) {
                setError(detail.map(e => e.msg).join(', '))
            } else if (typeof detail === 'object') {
                setError(JSON.stringify(detail))
            } else {
                setError(t('buying.orders.form.error_saving'))
            }
        } finally {
            setLoading(false)
        }
    }

    const totals = calculateTotals()

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('buying.orders.form.title_new')}</h1>
                <p className="workspace-subtitle">{t('buying.orders.form.subtitle_new')}</p>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}

            <form onSubmit={handleSubmit} className="card">
                {/* Header Information */}
                <div className="form-row">
                    <FormField label={t('buying.orders.form.supplier')} required style={{ flex: 2 }}>
                        <select
                            className="form-input"
                            required
                            value={formData.supplier_id || ''}
                            onChange={e => {
                                setFormData({ ...formData, supplier_id: e.target.value });
                                // Reset items discount when supplier changes
                                setItems(prevItems => prevItems.map(item => {
                                    let updated = { ...item };
                                    if (item.product_id) {
                                        const product = products.find(p => p.id === parseInt(item.product_id));
                                        if (product) {
                                            updated.unit_price = product.last_buying_price || product.buying_price || 0;
                                            updated.discount_percent = 0;
                                            updated.discount = 0;
                                        }

                                        const supplier = suppliers.find(s => s.id === parseInt(e.target.value));
                                        if (supplier && supplier.group_id) {
                                            const group = supplierGroups.find(g => g.id === supplier.group_id);
                                            if (group && group.application_scope === 'line' && group.discount_percentage > 0) {
                                                if (group.effect_type === 'discount') {
                                                    updated.discount_percent = group.discount_percentage;
                                                    updated.discount = (updated.quantity * updated.unit_price) * (group.discount_percentage / 100);
                                                } else if (group.effect_type === 'markup') {
                                                    updated.unit_price = updated.unit_price * (1 + (group.discount_percentage / 100));
                                                }
                                            }
                                        }

                                        // Recalculate line total
                                        const qty = Number(updated.quantity) || 0;
                                        const price = Number(updated.unit_price) || 0;
                                        const discount = Number(updated.discount) || 0;
                                        const taxRate = Number(updated.tax_rate) || 0;
                                        const taxable = (qty * price) - discount;
                                        updated.total = taxable + (taxable * (taxRate / 100));
                                    }
                                    return updated;
                                }));
                            }}
                        >
                            <option value="">{t('buying.orders.form.supplier_placeholder')}</option>
                            {suppliers.map(s => (
                                <option key={s.id} value={s.id}>{s.name || s.supplier_name}</option>
                            ))}
                        </select>
                    </FormField>
                    <FormField>
                        <CustomDatePicker
                            label={t('buying.orders.form.order_date')}
                            selected={formData.order_date}
                            onChange={(dateStr) => setFormData({ ...formData, order_date: dateStr })}
                            required
                        />
                    </FormField>
                    <FormField>
                        <CustomDatePicker
                            label={t('buying.orders.form.expected_date')}
                            selected={formData.expected_date}
                            onChange={(dateStr) => setFormData({ ...formData, expected_date: dateStr })}
                            required
                        />
                    </FormField>
                </div>

                {/* Items Section */}
                <div className="invoice-items-container" style={{
                    margin: '24px 0',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    overflow: 'hidden',
                    boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
                }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '35%' }}>{t('buying.orders.form.items.product')}</th>
                                <th style={{ width: '10%' }}>{t('buying.orders.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('buying.orders.form.items.unit_price')}</th>
                                <th style={{ width: '10%' }}>{t('buying.orders.form.items.discount')} (%)</th>
                                <th style={{ width: '10%' }}>{t('buying.orders.form.items.tax_rate')}</th>
                                <th style={{ width: '15%' }}>{t('buying.orders.form.items.total')}</th>
                                <th style={{ width: '5%' }}></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((item, index) => (
                                <tr key={index}>
                                    <td style={{ verticalAlign: 'top' }}>
                                        <select
                                            className="form-input"
                                            style={{ marginBottom: '6px' }}
                                            value={item.product_id || ''}
                                            onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                            required
                                        >
                                            <option value="">{t('buying.orders.form.items.product_placeholder')}</option>
                                            {products.map(p => (
                                                <option key={p.id} value={p.id}>{p.item_name}</option>
                                            ))}
                                        </select>
                                        <input
                                            type="text"
                                            className="form-input text-small"
                                            placeholder={t('buying.orders.form.items.desc_placeholder')}
                                            value={item.description}
                                            onChange={e => handleItemChange(index, 'description', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="number" className="form-input" min="1" step="any"
                                            value={item.quantity}
                                            onChange={e => handleItemChange(index, 'quantity', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="number" className="form-input" min="0" step="0.01"
                                            value={item.unit_price}
                                            onChange={e => handleItemChange(index, 'unit_price', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="number" className="form-input" min="0" max="100" step="0.01"
                                            value={item.discount_percent}
                                            onChange={e => handleItemChange(index, 'discount_percent', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="number" className="form-input" value={item.tax_rate}
                                            onChange={e => handleItemChange(index, 'tax_rate', e.target.value)}
                                        />
                                    </td>
                                    <td className="font-bold">
                                        {item.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                    </td>
                                    <td>
                                        <button
                                            type="button"
                                            onClick={() => items.length > 1 && setItems(items.filter((_, i) => i !== index))}
                                            className="btn-icon danger"
                                            style={{ color: 'var(--error)' }}
                                            title={t('common.delete')}
                                        >
                                            🗑️
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    <div style={{ padding: '12px', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border-color)' }}>
                        <button type="button" onClick={handleAddItem} className="btn btn-secondary btn-sm">
                            <span style={{ marginLeft: '8px' }}>+</span>
                            {t('buying.orders.form.items.add_line')}
                        </button>
                    </div>
                </div>

                {/* Footer Section */}
                <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start', marginTop: '12px' }}>
                    <div style={{ flex: 1 }}>
                        <FormField label={t('buying.orders.form.notes.label')} className="font-bold">
                            <textarea
                                className="form-input" rows="6"
                                placeholder={t('buying.orders.form.notes.placeholder')}
                                value={formData.notes}
                                onChange={e => setFormData({ ...formData, notes: e.target.value })}
                            ></textarea>
                        </FormField>
                    </div>

                    <div style={{
                        width: '340px',
                        padding: '24px',
                        background: 'var(--bg-secondary)',
                        borderRadius: '12px',
                        border: '1px solid var(--border-color)'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('buying.orders.form.summary.subtotal')}</span>
                            <span className="font-medium">{totals.subtotal.toLocaleString(undefined, { minimumFractionDigits: 2 })} <small>{currency}</small></span>
                        </div>
                        {totals.globalEffectPercent > 0 && totals.globalEffectType === 'markup' && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px', color: 'var(--text-success)' }}>
                                <span>زيادة (مجموعة) ({totals.globalEffectPercent}%)</span>
                                <span>{totals.globalMarkupAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })} <small>{currency}</small></span>
                            </div>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('buying.orders.form.summary.discount')}</span>
                            <span className="font-medium text-error">-{totals.discount.toLocaleString(undefined, { minimumFractionDigits: 2 })} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('buying.orders.form.summary.tax')}</span>
                            <span className="font-medium">{totals.tax.toLocaleString(undefined, { minimumFractionDigits: 2 })} <small>{currency}</small></span>
                        </div>

                        <div style={{ borderTop: '1.5px solid var(--border-color)', margin: '16px 0' }}></div>

                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontWeight: 'bold',
                            fontSize: '22px',
                            color: 'var(--primary)',
                            marginBottom: '24px'
                        }}>
                            <span>{t('buying.orders.form.summary.grand_total')}</span>
                            <span>{totals.total.toLocaleString(undefined, { minimumFractionDigits: 2 })} <small>{currency}</small></span>
                        </div>

                        <div className="form-actions" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <button
                                type="submit"
                                className="btn btn-primary"
                                style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600' }}
                                disabled={loading}
                            >
                                {loading ? t('buying.orders.form.saving') : t('buying.orders.form.submit')}
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                style={{ width: '100%', padding: '12px' }}
                                onClick={() => navigate('/buying/orders')}
                            >
                                {t('buying.orders.form.cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default BuyingOrderForm
