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

function SalesOrderForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const location = useLocation()
    const currency = getCurrency()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [customers, setCustomers] = useState([])
    const [products, setProducts] = useState([])
    const [warehouses, setWarehouses] = useState([])
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)

    const [formData, setFormData] = useState({
        customer_id: '',
        party_site_id: '',
        warehouse_id: '',
        quotation_id: '',
        order_date: new Date().toISOString().split('T')[0],
        expected_delivery_date: '',
        notes: ''
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, total: 0 }
    ])

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchData = async () => {
                try {
                    const [custRes, prodRes, whRes, priceRes] = await Promise.all([
                        salesAPI.listCustomers(),
                        inventoryAPI.listProducts(),
                        inventoryAPI.listWarehouses(),
                        inventoryAPI.getBranchPrices(currentBranch?.id)
                    ])
                    setCustomers(custRes.data)
                    setProducts(prodRes.data)
                    setWarehouses(whRes.data)
                    
                    // Store branch prices for auto-fill
                    window.__branchPrices = priceRes.data?.prices || {}
                    window.__branchCurrency = priceRes.data?.currency || currency
                } catch (err) {
                    showToast(t('common.error'), 'error')
                } finally {
                    setInitialLoad(false)
                }
            }
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    useEffect(() => {
        if (location.state?.fromQuotation) {
            const quote = location.state.fromQuotation
            setFormData(prev => ({
                ...prev,
                customer_id: quote.customer_id || '',
        party_site_id: '',
                quotation_id: quote.id,
                notes: `${t('sales.orders.converted_from_quote')}: ${quote.sq_number}\n${quote.notes || ''}`
            }))

            if (quote.items && quote.items.length > 0) {
                setItems(quote.items.map(item => {
                    const quantity = Number(item.quantity) || 0
                    const unitPrice = Number(item.unit_price) || 0
                    const discount = Number(item.discount) || 0
                    const discountPercent = (quantity * unitPrice) > 0 ? (discount / (quantity * unitPrice)) * 100 : 0

                    return {
                        product_id: item.product_id,
                        description: item.description,
                        quantity: quantity,
                        unit_price: unitPrice,
                        tax_rate: item.tax_rate,
                        discount: discount,
                        discount_percent: discountPercent,
                        total: item.total
                    }
                }))
            }
        }
    }, [location.state])

    const handleAddItem = () => {
        setItems([
            ...items,
            { product_id: '', description: '', quantity: '1', unit_price: '0', tax_rate: null, discount: '0', discount_percent: '0' }
        ])
    }

    // Dumb-terminal item handler — stores raw strings, no arithmetic
    const handleItemChange = (index, field, value) => {
        const newItems = items.map((item, i) => {
            if (i !== index) return item
            const updatedItem = { ...item, [field]: value }

            if (field === 'product_id') {
                const product = products.find(p => p.id === parseInt(value, 10))
                if (product) {
                    updatedItem.description = product.product_name || product.item_name || ''
                    const branchPrices = window.__branchPrices || {}
                    const priceInfo = branchPrices[parseInt(value, 10)]
                    updatedItem.unit_price = String(priceInfo ? priceInfo.price : (product.selling_price || '0'))
                    updatedItem.tax_rate = null // Resolved by backend engine
                }
            }

            return updatedItem
        })
        setItems(newItems)
    }

    // Backend-powered calculations — no local arithmetic
    const { totals: backendTotals, lines: backendLines, previewDebounced } = useInvoiceCalc()

    // Call backend for accurate calculations
    useEffect(() => {
        if (items.length > 0 && items.some(i => String(i.quantity || '').trim() && String(i.unit_price || '').trim())) {
            previewDebounced({
                lines: items.map(i => ({
                    product_id: i.product_id ? parseInt(i.product_id, 10) : null,
                    quantity: String(i.quantity || '0'),
                    unit_price: String(i.unit_price || '0'),
                    tax_rate: i.tax_rate != null ? String(i.tax_rate) : null,
                    discount: String(i.discount || '0'),
                })),
                branch_id: currentBranch?.id || null,
                customer_id: formData.customer_id ? parseInt(formData.customer_id, 10) : null,
                currency,
            })
        }
    }, [items, formData.customer_id, currentBranch, currency, previewDebounced])

    const handleSubmit = async (e) => {
        e.preventDefault()

        if (!formData.customer_id) {
            setError(t('sales.orders.form.errors.customer_required'))
            return
        }
        if (!formData.warehouse_id) {
            setError(t('sales.orders.form.errors.warehouse_required'))
            return
        }
        if (items.some(item => !item.product_id)) {
            setError(t('sales.orders.form.errors.product_required'))
            return
        }
        if (!formData.order_date || !formData.expected_delivery_date) {
            setError(t('sales.orders.form.errors.dates_required'))
            return
        }
        if (formData.expected_delivery_date < formData.order_date) {
            setError(t('sales.orders.form.errors.delivery_before_order'))
            return
        }

        setLoading(true)
        setError(null)
        try {
            const payload = {
                customer_id: parseInt(formData.customer_id),
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                branch_id: currentBranch?.id,
                warehouse_id: formData.warehouse_id ? parseInt(formData.warehouse_id) : null,
                quotation_id: formData.quotation_id ? parseInt(formData.quotation_id) : null,
                order_date: formData.order_date,
                expected_delivery_date: formData.expected_delivery_date || null,
                notes: formData.notes,
                items: items.map(item => ({
                    product_id: parseInt(item.product_id),
                    description: item.description || '',
                    quantity: String(item.quantity || 0),
                    unit_price: String(item.unit_price || 0),
                    discount: String(item.discount || 0),
                    tax_rate: String(item.tax_rate || 0)
                }))
            }
            await salesAPI.createOrder(payload)
            navigate('/sales/orders')
        } catch (err) {
            const detail = err.response?.data?.detail
            if (typeof detail === 'string') {
                setError(detail)
            } else if (Array.isArray(detail)) {
                setError(detail.map(e => e.msg).join(', '))
            } else if (typeof detail === 'object') {
                setError(JSON.stringify(detail))
            } else {
                setError(t('sales.orders.form.errors.create_failed'))
            }
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('sales.orders.form.create_title')}</h1>
                    <p className="workspace-subtitle">{t('sales.orders.form.create_subtitle')}</p>
                </div>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}

            <form onSubmit={handleSubmit} className="card">
                <div className="form-row">
                    <FormField label={t('sales.orders.form.customer')} required style={{ flex: 1.5 }}>
                        <select
                            className="form-input"
                            required
                            value={formData.customer_id || ''}
                            onChange={e => setFormData({ ...formData, customer_id: e.target.value })}
                        >
                            <option value="">{t('sales.orders.form.customer_placeholder')}</option>
                            {customers.map(c => (
                                <option key={c.id} value={c.id}>{c.name || c.customer_name}</option>
                            ))}
                        </select>
                    </FormField>

                    <FormField label={t('stock.warehouses.title')} style={{ flex: 1.5 }}>
                        <select
                            className="form-input"
                            value={formData.warehouse_id || ''}
                            onChange={e => setFormData({ ...formData, warehouse_id: e.target.value })}
                        >
                            <option value="">{t('common.select')}</option>
                            {warehouses.filter(wh => !currentBranch || wh.branch_id === currentBranch.id).map(wh => (
                                <option key={wh.id} value={wh.id}>{wh.name}</option>
                            ))}
                        </select>
                    </FormField>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('sales.orders.form.date')}
                            selected={formData.order_date}
                            onChange={(dateStr) => setFormData({ ...formData, order_date: dateStr })}
                            required
                        />
                    </div>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('sales.orders.form.expected_delivery')}
                            selected={formData.expected_delivery_date}
                            onChange={(dateStr) => setFormData({ ...formData, expected_delivery_date: dateStr })}
                            required
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
                                <th style={{ width: '35%' }}>{t('sales.orders.form.items.product')} / {t('sales.orders.form.items.description')}</th>
                                <th style={{ width: '10%' }}>{t('sales.orders.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('sales.orders.form.items.price')}</th>
                                <th style={{ width: '10%' }}>{t('sales.orders.form.items.discount')} (%)</th>
                                <th style={{ width: '10%' }}>{t('sales.invoices.form.items.tax')}</th>
                                <th style={{ width: '15%' }}>{t('sales.orders.form.items.total')}</th>
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
                                        >
                                            <option value="">{t('sales.orders.form.product_placeholder')}</option>
                                            {products.map(p => (
                                                <option key={p.id} value={p.id}>{p.product_name || p.item_name}</option>
                                            ))}
                                        </select>
                                        <input
                                            type="text"
                                            className="form-input text-small"
                                            placeholder={t('sales.orders.form.desc_placeholder')}
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
                                        {backendLines?.[index]?.total != null ? formatNumber(backendLines[index].total) : '—'}
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
                            + {t('sales.orders.form.add_item')}
                        </button>
                    </div>
                </div>

                <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                        <FormField label={t('sales.orders.form.notes_label')} className="font-bold">
                            <textarea
                                className="form-input" rows="5"
                                placeholder={t('sales.orders.form.notes_placeholder')}
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
                        {/* Totals — sourced exclusively from backend preview */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.orders.details.subtotal')}</span>
                            <span>{backendTotals ? formatNumber(backendTotals.subtotal) : '—'} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.orders.details.discount')}</span>
                            <span className="text-error">{backendTotals ? `-${formatNumber(backendTotals.totalDiscount)}` : '—'} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.orders.details.tax')}</span>
                            <span>{backendTotals ? formatNumber(backendTotals.totalTax) : '—'} <small>{currency}</small></span>
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
                            <span>{t('sales.orders.details.grand_total')}</span>
                            <span>{backendTotals ? formatNumber(backendTotals.grandTotal) : '—'} <small>{currency}</small></span>
                        </div>

                        <div className="form-actions" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            <button
                                type="submit"
                                className="btn btn-primary"
                                style={{ width: '100%', padding: '12px' }}
                                disabled={loading}
                            >
                                {loading ? t('sales.orders.form.saving') : t('sales.orders.form.save_btn')}
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                style={{ width: '100%' }}
                                onClick={() => navigate('/sales/orders')}
                            >
                                {t('sales.orders.form.cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default SalesOrderForm
