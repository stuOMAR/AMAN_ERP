import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { purchasesAPI, inventoryAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import useInvoiceCalc from '../../hooks/useInvoiceCalc'

function BuyingReturnForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [receiveRefund, setReceiveRefund] = useState(false)
    const [paymentMethod, setPaymentMethod] = useState('cash')
    const currency = getCurrency()
    const { currentBranch } = useBranch()

    // Data Sources
    const [suppliers, setSuppliers] = useState([])
    const [products, setProducts] = useState([])
    const [warehouses, setWarehouses] = useState([])
    const [invoices, setInvoices] = useState([]) // For invoice linking

    // Form State
    const [formData, setFormData] = useState({
        supplier_id: '',
        party_site_id: '',
        warehouse_id: '',
        invoice_id: '', // Linked invoice
        invoice_date: new Date().toISOString().split('T')[0],
        due_date: new Date().toISOString().split('T')[0],
        currency: currency || '',
        exchange_rate: '1',
        notes: ''
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: '1', unit_price: '', discount: '' }
    ])

    useEffect(() => {
        const fetchResources = async () => {
            try {
                const params = { branch_id: currentBranch?.id }
                const [suppRes, prodRes, whRes] = await Promise.all([
                    inventoryAPI.listSuppliers(params),
                    inventoryAPI.listProducts(params),
                    inventoryAPI.listWarehouses(params)
                ])
                setSuppliers(suppRes.data)
                setProducts(prodRes.data)
                setWarehouses(whRes.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
            } finally {
                setInitialLoad(false)
            }
        }
        const timer = setTimeout(() => {
            fetchResources()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    // Fetch Invoices when Supplier Selected
    useEffect(() => {
        if (formData.supplier_id) {
            purchasesAPI.listInvoices({ supplier_id: formData.supplier_id })
                .then(res => setInvoices(res.data))
                .catch(err => showToast(t('common.error'), 'error'))
        } else {
            setInvoices([])
        }
    }, [formData.supplier_id])

    // Load Items from Invoice
    const handleInvoiceSelect = async (invoiceId) => {
        setFormData(prev => ({ ...prev, invoice_id: invoiceId }))
        if (!invoiceId) return

        try {
            const res = await purchasesAPI.getInvoice(invoiceId)
            const invoice = res.data
            setFormData(prev => ({
                ...prev,
                currency: invoice.currency || prev.currency,
                exchange_rate: String(invoice.exchange_rate || prev.exchange_rate || '1'),
            }))

            // Map items with max_quantity
            const returnItems = invoice.items.map(item => {
                const remaining = item.remaining_quantity !== undefined
                    ? String(item.remaining_quantity || '0')
                    : String(item.quantity || '0')

                return {
                    product_id: item.product_id,
                    description: item.description || item.product_name,
                    quantity: remaining,
                    max_quantity: remaining,
                    unit_price: String(item.unit_price || '0'),
                    discount: String(item.discount || '0')
                }
            })

            setItems(returnItems)
        } catch (err) {
            showToast(t('common.error'), 'error')
            setError(t('common.error_loading'))
        }
    }

    // Calculations
    const { totals: backendTotals, lines: backendLines, previewDebounced } = useInvoiceCalc()

    const calculateTotals = () => {
        if (backendTotals) {
            return {
                subtotal: backendTotals.subtotal,
                totalTax: backendTotals.totalTax,
                totalDiscount: backendTotals.totalDiscount,
                total: backendTotals.grandTotal,
            }
        }
        return { subtotal: null, totalTax: null, totalDiscount: null, total: null }
    }

    const totals = calculateTotals()

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
                currency: formData.currency || currency,
            })
        }
    }, [items, formData.supplier_id, formData.currency, currentBranch, currency, previewDebounced])

    // Handlers
    const handleItemChange = (index, field, value) => {
        const newItems = items.map((item, i) => {
            if (i === index) {
                const updatedItem = { ...item }

                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value))
                    if (product) {
                        updatedItem.description = product.item_name || ''
                        // Use buying price or last purchase price
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

    const addItem = () => {
        setItems([...items, { product_id: '', description: '', quantity: '1', unit_price: '', discount: '' }])
    }

    const removeItem = (index) => {
        if (items.length > 1) {
            setItems(items.filter((_, i) => i !== index))
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()

        if (!formData.supplier_id) {
            setError(t('buying.returns.form.error_supplier_required') || t('common.required'))
            return
        }
        if (!formData.warehouse_id) {
            setError(t('buying.returns.form.error_warehouse'))
            return
        }

        setLoading(true)
        setError(null)

        try {
            const payload = {
                supplier_id: parseInt(formData.supplier_id),
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                branch_id: currentBranch?.id,
                warehouse_id: formData.warehouse_id ? parseInt(formData.warehouse_id) : null,
                invoice_date: formData.invoice_date,
                due_date: formData.due_date,
                payment_method: receiveRefund ? paymentMethod : null,
	                paid_amount: receiveRefund ? String(totals.total || '0') : '0',
	                currency: formData.currency || currency,
	                exchange_rate: String(formData.exchange_rate || 1),
	                original_invoice_id: formData.invoice_id ? parseInt(formData.invoice_id) : null,
                notes: formData.notes + (formData.invoice_id ? ` (Return for Invoice #${formData.invoice_id})` : ''),
                items: items.map(item => ({
                    product_id: parseInt(item.product_id) || null,
                    description: item.description || '',
                    quantity: String(item.quantity || 0),
                    unit_price: String(item.unit_price || 0),
                    discount: String(item.discount || 0)
                })),
                submitted_grand_total: backendTotals?.grandTotal ? String(backendTotals.grandTotal) : null,
            }

            await purchasesAPI.createReturn(payload)
            navigate('/buying/returns')
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
            const errMsg = err.response?.data?.detail
            setError(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg) || t('buying.returns.form.error_saving'))
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title" style={{ color: 'var(--error)' }}>{t('buying.returns.form.title_new')}</h1>
                <p className="workspace-subtitle">{t('buying.returns.form.subtitle_new')}</p>
            </div>

            <style>{`
                @keyframes shake {
                    0% { transform: translateX(0); }
                    25% { transform: translateX(-10px); }
                    50% { transform: translateX(10px); }
                    75% { transform: translateX(-10px); }
                    100% { transform: translateX(0); }
                }
                .shake-alert {
                    animation: shake 0.4s ease-in-out;
                    border: 2px solid #ef4444;
                    background: #fef2f2;
                    color: #991b1b;
                    padding: 16px;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 1.1em;
                    box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }
            `}</style>

            {error && (
                <div className="shake-alert mb-6">
                    <span style={{ fontSize: '1.5em' }}>🚫</span>
                    <div>
                        {error}
                    </div>
                </div>
            )}

            <form onSubmit={handleSubmit} className="card">
                {/* Header Info */}
                <div className="form-row">
                    <FormField label={t('buying.returns.form.supplier')} required style={{ flex: 1 }}>
                        <select
                            className="form-input"
                            value={formData.supplier_id}
                            onChange={e => setFormData({ ...formData, supplier_id: e.target.value })}
                            required
                        >
                            <option value="">{t('buying.returns.form.supplier_placeholder')}</option>
                            {suppliers.map(s => <option key={s.id} value={s.id}>{s.name || 'No Name'}</option>)}
                        </select>
                    </FormField>

                    <FormField label={t('stock.warehouses.title')} style={{ flex: 1 }}>
                        <select
                            className="form-input"
                            value={formData.warehouse_id}
                            onChange={e => setFormData({ ...formData, warehouse_id: e.target.value })}
                        >
                            <option value="">{t('common.select')}</option>
                            {warehouses.filter(wh => !currentBranch || wh.branch_id === currentBranch.id).map(wh => (
                                <option key={wh.id} value={wh.id}>{wh.name}</option>
                            ))}
                        </select>
                    </FormField>

                    <FormField label={t('buying.returns.form.original_invoice')} style={{ flex: 1 }}>
                        <select
                            className="form-input"
                            value={formData.invoice_id}
                            onChange={e => handleInvoiceSelect(e.target.value)}
                            disabled={!formData.supplier_id}
                        >
                            <option value="">{t('buying.returns.form.invoice_placeholder')}</option>
                            {invoices.map(inv => (
                                <option key={inv.id} value={inv.id}>
                                    {inv.invoice_number} ({formatShortDate(inv.invoice_date)}) - {formatNumber(inv.total)}
                                </option>
                            ))}
                        </select>
                        {formData.invoice_id && <small style={{ color: 'green' }}>{t('buying.returns.form.invoice_loaded')}</small>}
                    </FormField>

                    <FormField>
                        <CustomDatePicker
                            label={t('buying.returns.form.return_date')}
                            selected={formData.invoice_date}
                            onChange={(dateStr) => setFormData({ ...formData, invoice_date: dateStr })}
                        />
                    </FormField>
                </div>

                {/* Items Table */}
                <div className="invoice-items-container" style={{ margin: '24px 0', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: '#fef2f2' }}>
                            <tr>
                                <th style={{ width: '30%' }}>{t('buying.returns.form.items.product')}</th>
                                <th style={{ width: '10%' }}>{t('buying.returns.form.items.return_qty')}</th>
                                <th style={{ width: '15%' }}>{t('buying.returns.form.items.return_price')}</th>
                                <th style={{ width: '10%' }}>{t('buying.returns.form.items.discount')}</th>
                                <th style={{ width: '10%' }}>{t('buying.returns.form.items.tax_rate')}</th>
                                <th style={{ width: '15%' }}>{t('buying.returns.form.items.total')}</th>
                                <th style={{ width: '5%' }}></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((item, index) => (
                                    <tr key={index}>
                                        <td>
                                            <select
                                                className="form-input"
                                                style={{ marginBottom: '4px' }}
                                                value={item.product_id || ''}
                                                onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                                disabled={!!formData.invoice_id && !!item.max_quantity} // Lock product if loaded from invoice
                                            >
                                                <option value="">{t('buying.returns.form.items.product_placeholder')}</option>
                                                {products.map(p => <option key={p.id} value={p.id}>{p.item_name}</option>)}
                                            </select>
                                            <input
                                                type="text"
                                                className="form-input"
                                                placeholder={t('buying.returns.form.items.desc_placeholder')}
                                                value={item.description || ''}
                                                onChange={e => handleItemChange(index, 'description', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                <input
                                                    type="text" inputMode="decimal" className="form-input"
                                                    value={item.quantity || ''}
                                                    onChange={e => handleItemChange(index, 'quantity', e.target.value)}
                                                    max={item.max_quantity}
                                                />
                                                {item.max_quantity && <small style={{ color: 'grey', whiteSpace: 'nowrap' }}>/{formatNumber(item.max_quantity || 0)}</small>}
                                            </div>
                                        </td>
                                        <td>
                                            <input
                                                type="text" inputMode="decimal" className="form-input"
                                                value={item.unit_price || ''}
                                                onChange={e => handleItemChange(index, 'unit_price', e.target.value)}
                                                disabled={!!formData.invoice_id} // Lock price if linked
                                            />
                                        </td>
                                        <td>
                                            <input
                                                type="text" inputMode="decimal" className="form-input"
                                                value={item.discount}
                                                onChange={e => handleItemChange(index, 'discount', e.target.value)}
                                                disabled={!!formData.invoice_id}
                                            />
                                        </td>
                                        <td>
                                            <span>{backendLines?.[index]?.tax_rate ?? '—'}</span>
                                        </td>
                                        <td>
                                            <div style={{ fontWeight: 'bold' }}>
                                                {backendLines?.[index]?.line_total != null || backendLines?.[index]?.total != null
                                                    ? formatNumber(backendLines[index].line_total ?? backendLines[index].total)
                                                    : '—'}
                                            </div>
                                        </td>
                                        <td>
                                            <button
                                                type="button"
                                                className="btn-icon danger"
                                                onClick={() => removeItem(index)}
                                                style={{ color: 'var(--error)' }}
                                            >
                                                🗑️
                                            </button>
                                        </td>
                                    </tr>
                            ))}
                        </tbody>
                    </table>
                    <div style={{ padding: '8px', background: '#fff' }}>
                        {!formData.invoice_id && <button type="button" className="btn btn-secondary btn-sm" onClick={addItem}>{t('buying.returns.form.items.add_line')}</button>}
                        {formData.invoice_id && <small style={{ color: 'grey' }}>{t('buying.returns.form.items.cant_add')}</small>}
                    </div>
                </div>

                {/* Footer Totals */}
                <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                        <FormField label={t('buying.returns.form.notes.label')}>
                            <textarea
                                className="form-input" rows="3"
                                value={formData.notes}
                                onChange={e => setFormData({ ...formData, notes: e.target.value })}
                                placeholder={t('buying.returns.form.notes.placeholder')}
                            ></textarea>
                        </FormField>
                    </div>

                    <div style={{ width: '300px', padding: '24px', background: '#fef2f2', borderRadius: '8px', border: '1px solid #fee2e2' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.returns.form.summary.subtotal')}</span>
                            <span>{totals.subtotal != null ? formatNumber(totals.subtotal) : '—'} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.returns.form.summary.tax')}</span>
                            <span>{totals.totalTax != null ? formatNumber(totals.totalTax) : '—'} <small>{currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid #fecaca', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '18px', color: 'var(--error)' }}>
                            <span>{t('buying.returns.form.summary.total_return')}</span>
                            <span>{totals.total != null ? formatNumber(totals.total) : '—'} <small>{currency}</small></span>
                        </div>

                        {/* Instant Refund Option */}
                        <div style={{ marginTop: '16px', padding: '12px', background: '#fff', borderRadius: '4px', border: '1px solid #fecaca' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginBottom: receiveRefund ? '8px' : '0' }}>
                                <input
                                    type="checkbox"
                                    checked={receiveRefund}
                                    onChange={e => setReceiveRefund(e.target.checked)}
                                />
                                <span style={{ fontSize: '0.95em' }}>{t('buying.returns.form.refund.label')}</span>
                            </label>

                            {receiveRefund && (
                                <div className="fade-in">
                                    <FormField label={t('buying.returns.form.refund.method_label')} style={{ marginBottom: '8px' }}>
                                        <select
                                            className="form-input"
                                            value={paymentMethod}
                                            onChange={e => setPaymentMethod(e.target.value)}
                                            style={{ padding: '4px' }}
                                        >
                                            <option value="cash">{t('buying.returns.form.refund.methods.cash')}</option>
                                            <option value="bank">{t('buying.returns.form.refund.methods.bank')}</option>
                                        </select>
                                    </FormField>
                                    <div style={{ fontSize: '0.85em', color: 'green' }}>
                                        {t('buying.returns.form.refund.auto_receipt')}
                                    </div>
                                </div>
                            )}
                        </div>

                        <button
                            type="submit"
                            className="btn btn-danger"
                            style={{ width: '100%', marginTop: '24px', padding: '12px' }}
                            disabled={loading}
                        >
                            {loading ? t('buying.returns.form.saving') : t('buying.returns.form.submit')}
                        </button>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default BuyingReturnForm
