import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { salesAPI, inventoryAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { useTranslation } from 'react-i18next'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import useInvoiceCalc from '../../hooks/useInvoiceCalc'

function SalesQuotationForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const currency = getCurrency()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [customers, setCustomers] = useState([])
    const [products, setProducts] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const [formData, setFormData] = useState({
        customer_id: '',
        party_site_id: '',
        quotation_date: new Date().toISOString().split('T')[0],
        expiry_date: '',
        notes: '',
        terms_conditions: t('sales.quotations.form.default_terms')
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, total: 0 }
    ])

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [custRes, prodRes] = await Promise.all([
                    salesAPI.listCustomers(),
                    inventoryAPI.listProducts()
                ])
                setCustomers(custRes.data)
                setProducts(prodRes.data)
            } catch (err) {
                const detail = err.response?.data?.detail || t('common.error')
                setError(detail)
                showToast(detail, 'error')
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
                const updatedItem = { ...item, [field]: value }

                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value))
                    if (product) {
                        updatedItem.description = product.product_name || product.item_name || ''
                        updatedItem.unit_price = product.selling_price || 0
                        updatedItem.tax_rate = null // Resolved by backend engine
                    }
                }

                const qty = Number(updatedItem.quantity) || 0
                const price = Number(updatedItem.unit_price) || 0
                let discount = Number(updatedItem.discount) || 0
                let discountPercent = Number(updatedItem.discount_percent) || 0

                // If updating percent, recalculate amount
                if (field === 'discount_percent') {
                    discountPercent = Number(value) || 0
                    discount = (qty * price) * (discountPercent / 100)
                    updatedItem.discount = discount
                }
                // If updating quantity/price, recalculate amount from percent
                else if (field === 'quantity' || field === 'unit_price') {
                    discount = (qty * price) * (discountPercent / 100)
                    updatedItem.discount = discount
                }

                updatedItem.discount_percent = discountPercent
                updatedItem.discount = discount // Ensure amount is up to date

                const taxRate = Number(updatedItem.tax_rate) || 0
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
        return items.reduce((acc, item) => {
            const qty = Number(item.quantity) || 0
            const price = Number(item.unit_price) || 0
            const discount = Number(item.discount) || 0
            const taxRate = Number(item.tax_rate) || 0
            const lineSubtotal = qty * price
            const taxable = lineSubtotal - discount
            const lineTax = taxable * (taxRate / 100)
            acc.subtotal += lineSubtotal
            acc.discount += discount
            acc.tax += lineTax
            acc.total += (taxable + lineTax)
            return acc
        }, { subtotal: 0, discount: 0, tax: 0, total: 0 })
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

        if (!formData.customer_id) {
            setError(t('sales.quotations.form.errors.customer_required'))
            return
        }
        if (items.some(item => !item.product_id)) {
            setError(t('sales.quotations.form.errors.product_required'))
            return
        }
        if (items.some(item => Number(item.quantity) <= 0)) {
            setError(t('sales.quotations.form.errors.quantity_required', 'يجب أن تكون كمية كل صنف أكبر من صفر'))
            return
        }
        if (items.some(item => Number(item.unit_price) < 0)) {
            setError(t('sales.quotations.form.errors.price_required', 'سعر الوحدة لا يمكن أن يكون سالباً'))
            return
        }

        setLoading(true)
        setError(null)
        try {
            const payload = {
                customer_id: parseInt(formData.customer_id),
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                quotation_date: formData.quotation_date,
                expiry_date: formData.expiry_date || null,
                notes: formData.notes,
                terms_conditions: formData.terms_conditions,
                branch_id: currentBranch?.id,
                items: items.map(item => ({
                    product_id: parseInt(item.product_id),
                    description: item.description || '',
                    quantity: String(item.quantity || 0),
                    unit_price: String(item.unit_price || 0),
                    discount: String(item.discount || 0),
                    tax_rate: String(item.tax_rate || 0)
                }))
            }
            await salesAPI.createQuotation(payload)
            navigate('/sales/quotations')
        } catch (err) {
            const detail = err.response?.data?.detail
            if (typeof detail === 'string') {
                setError(detail)
            } else if (Array.isArray(detail)) {
                setError(detail.map(e => e.msg).join(', '))
            } else if (typeof detail === 'object') {
                setError(JSON.stringify(detail))
            } else {
                setError(t('sales.quotations.form.errors.create_failed'))
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
                <div className="header-title">
                    <h1 className="workspace-title">{t('sales.quotations.form.create_title')}</h1>
                    <p className="workspace-subtitle">{t('sales.quotations.form.create_subtitle')}</p>
                </div>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}
            {!error && products.length === 0 && (
                <div className="alert alert-warning mb-4">
                    لا توجد أصناف متاحة للاختيار. يجب تعريف الصنف ITM-001 أو أي صنف نشط في المخزون قبل إصدار عرض السعر.
                </div>
            )}

            <form onSubmit={handleSubmit} className="card">
                <div className="form-row">
                    <FormField label={t('sales.quotations.form.customer')} required style={{ flex: 2 }}>
                        <select
                            className="form-input"
                            required
                            value={formData.customer_id}
                            onChange={e => setFormData({ ...formData, customer_id: e.target.value })}
                        >
                            <option value="">{t('sales.quotations.form.customer_placeholder')}</option>
                            {customers.map(c => (
                                <option key={c.id} value={c.id}>{c.name || c.customer_name}</option>
                            ))}
                        </select>
                    </FormField>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('sales.quotations.form.date')}
                            selected={formData.quotation_date}
                            onChange={(dateStr) => setFormData({ ...formData, quotation_date: dateStr })}
                            required
                        />
                    </div>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('sales.quotations.form.expiry')}
                            selected={formData.expiry_date}
                            onChange={(dateStr) => setFormData({ ...formData, expiry_date: dateStr })}
                        />
                    </div>
                </div>

                <div className="invoice-items-container" style={{
                    margin: '24px 0',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    overflow: 'hidden'
                }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '35%' }}>{t('sales.quotations.form.items.product')} / {t('sales.quotations.form.items.description')}</th>
                                <th style={{ width: '10%' }}>{t('sales.quotations.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('sales.quotations.form.items.price')}</th>
                                <th style={{ width: '10%' }}>{t('sales.quotations.form.items.discount')} (%)</th>
                                <th style={{ width: '10%' }}>{t('sales.invoices.form.items.tax')}</th>
                                <th style={{ width: '15%' }}>{t('sales.quotations.form.items.total')}</th>
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
                                            value={item.product_id}
                                            onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                            required
                                            disabled={products.length === 0}
                                        >
                                            <option value="">{t('sales.quotations.form.product_placeholder')}</option>
                                            {products.map(p => (
                                                <option key={p.id} value={p.id}>
                                                    {p.item_code || p.product_code ? `${p.item_code || p.product_code} - ` : ''}{p.product_name || p.item_name} ({formatNumber(p.selling_price || 0)} {currency})
                                                </option>
                                            ))}
                                        </select>
                                        <input
                                            type="text"
                                            className="form-input text-small"
                                            placeholder={t('sales.quotations.form.desc_placeholder')}
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
                                        {formatNumber(item.total)}
                                    </td>
                                    <td>
                                        <button
                                            type="button"
                                            onClick={() => items.length > 1 && setItems(items.filter((_, i) => i !== index))}
                                            className="btn-icon danger"
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
                            + {t('sales.quotations.form.add_item')}
                        </button>
                    </div>
                </div>

                <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                        <FormField label={t('sales.quotations.form.notes_label')} className="font-bold">
                            <textarea
                                className="form-input" rows="3"
                                placeholder={t('sales.quotations.form.notes_placeholder')}
                                value={formData.notes}
                                onChange={e => setFormData({ ...formData, notes: e.target.value })}
                                style={{ marginBottom: '16px' }}
                            ></textarea>
                        </FormField>
                        <FormField label={t('sales.quotations.form.terms_label')}>
                            <textarea
                                className="form-input" rows="3"
                                value={formData.terms_conditions}
                                onChange={e => setFormData({ ...formData, terms_conditions: e.target.value })}
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
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.quotations.details.subtotal')}</span>
                            <span>{formatNumber(totals.subtotal)} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.quotations.details.discount')}</span>
                            <span className="text-error">-{formatNumber(totals.discount)} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.quotations.details.tax')}</span>
                            <span>{formatNumber(totals.tax)} <small>{currency}</small></span>
                        </div>

                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '16px 0' }}></div>

                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontWeight: 'bold',
                            fontSize: '20px',
                            color: 'var(--primary)',
                            marginBottom: '24px'
                        }}>
                            <span>{t('sales.quotations.details.grand_total')}</span>
                            <span>{formatNumber(totals.total)} <small>{currency}</small></span>
                        </div>

                        <div className="form-actions" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            <button
                                type="submit"
                                className="btn btn-primary"
                                style={{ width: '100%', padding: '12px' }}
                                disabled={loading || products.length === 0}
                            >
                                {loading ? t('sales.quotations.form.saving') : t('sales.quotations.form.save_btn')}
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                style={{ width: '100%' }}
                                onClick={() => navigate('/sales/quotations')}
                            >
                                {t('sales.quotations.form.cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default SalesQuotationForm
