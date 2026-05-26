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
    const [products, setProducts] = useState([])
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)

    const [formData, setFormData] = useState({
        supplier_id: '',
        party_site_id: '',
        order_date: new Date().toISOString().split('T')[0],
        expected_date: '',
        notes: ''
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: '1', unit_price: '', discount: '' }
    ])

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [suppRes, prodRes] = await Promise.all([
                    inventoryAPI.listSuppliers(),
                    inventoryAPI.listProducts()
                ])
                setSuppliers(suppRes.data)
                setProducts(prodRes.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
            } finally {
                setInitialLoad(false)
            }
        }
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [])

    const handleAddItem = () => {
        setItems([
            ...items,
            { product_id: '', description: '', quantity: '1', unit_price: '', discount: '' }
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
                        updatedItem.unit_price = String(product.last_buying_price || product.buying_price || '')
                    }
                }

                updatedItem[field] = value

                return updatedItem
            }
            return item
        })
        setItems(newItems)
    }

    // Backend-powered calculations
    const { totals: backendTotals, lines: backendLines, previewDebounced } = useInvoiceCalc()

    const calculateTotals = () => {
        if (backendTotals) {
            return {
                subtotal: backendTotals.subtotal,
                discount: backendTotals.totalDiscount,
                tax: backendTotals.totalTax,
                total: backendTotals.grandTotal,
                globalEffectType: 'discount',
                globalEffectPercent: '0',
                globalMarkupAmount: '0',
            }
        }
        return {
            subtotal: null,
            discount: null,
            tax: null,
            total: null,
            globalEffectType: 'discount',
            globalEffectPercent: '0',
            globalMarkupAmount: '0',
        };
    }

    // Call backend for accurate calculations
    useEffect(() => {
        if (items.length > 0 && items.some(i => String(i.quantity || '').trim() && String(i.unit_price || '').trim())) {
            previewDebounced({
                lines: items.map(i => ({
                    product_id: i.product_id ? parseInt(i.product_id, 10) : null,
                    quantity: String(i.quantity || '0'),
                    unit_price: String(i.unit_price || '0'),
                    discount: String(i.discount || '0'),
                })),
                branch_id: currentBranch?.id || null,
                supplier_id: formData.supplier_id ? parseInt(formData.supplier_id, 10) : null,
                currency,
            })
        }
    }, [items, formData.supplier_id, currentBranch, currency, previewDebounced])

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
                    markup: '0'
                })),
                submitted_grand_total: backendTotals?.grandTotal ? String(backendTotals.grandTotal) : null,
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
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
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
                                <th style={{ width: '10%' }}>{t('buying.orders.form.items.discount')}</th>
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
                                            type="text" inputMode="decimal" className="form-input"
                                            value={item.quantity}
                                            onChange={e => handleItemChange(index, 'quantity', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="text" inputMode="decimal" className="form-input"
                                            value={item.unit_price}
                                            onChange={e => handleItemChange(index, 'unit_price', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="text" inputMode="decimal" className="form-input"
                                            value={item.discount}
                                            onChange={e => handleItemChange(index, 'discount', e.target.value)}
                                        />
                                    </td>
                                    <td>
                                        <span>{backendLines?.[index]?.tax_rate ?? '—'}</span>
                                    </td>
                                    <td className="font-bold">
                                        {backendLines?.[index]?.line_total != null || backendLines?.[index]?.total != null
                                            ? formatNumber(backendLines[index].line_total ?? backendLines[index].total)
                                            : '—'}
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
                            <span className="font-medium">{totals.subtotal != null ? formatNumber(totals.subtotal) : '—'} <small>{currency}</small></span>
                        </div>
                        {totals.globalEffectPercent > 0 && totals.globalEffectType === 'markup' && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px', color: 'var(--text-success)' }}>
                                <span>زيادة (مجموعة) ({totals.globalEffectPercent}%)</span>
                                <span>{formatNumber(totals.globalMarkupAmount)} <small>{currency}</small></span>
                            </div>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('buying.orders.form.summary.discount')}</span>
                            <span className="font-medium text-error">-{totals.discount != null ? formatNumber(totals.discount) : '—'} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('buying.orders.form.summary.tax')}</span>
                            <span className="font-medium">{totals.tax != null ? formatNumber(totals.tax) : '—'} <small>{currency}</small></span>
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
                            <span>{totals.total != null ? formatNumber(totals.total) : '—'} <small>{currency}</small></span>
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
