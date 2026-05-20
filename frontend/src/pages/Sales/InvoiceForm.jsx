import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { salesAPI, inventoryAPI, currenciesAPI, treasuryAPI } from '../../utils/api'
import { fetchCurrentRate } from '../../hooks/useExchangeRate'
import { getCurrency } from '../../utils/auth'
import { formatNumber, getStep } from '../../utils/format'
import { useTranslation } from 'react-i18next'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import useInvoiceCalc from '../../hooks/useInvoiceCalc';
import Decimal from 'decimal.js';

function InvoiceForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const location = useLocation()
    const currency = getCurrency()
    const [loading, setLoading] = useState(false)
    const submittingRef = useRef(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [customers, setCustomers] = useState([])
    const [customerGroups, setCustomerGroups] = useState([])
    const [products, setProducts] = useState([])
    const [productStocks, setProductStocks] = useState({})
    const [warehouses, setWarehouses] = useState([])
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [error, setError] = useState(null)
    const [currencies, setCurrencies] = useState([])
    const [treasuryAccounts, setTreasuryAccounts] = useState([])

    // Backend-powered calculations
    const { totals: calcTotals, lines: backendLines, preview, previewDebounced } = useInvoiceCalc()

    const [formData, setFormData] = useState({
        customer_id: '',
        party_site_id: '',
        warehouse_id: '',
        invoice_date: new Date().toISOString().split('T')[0],
        due_date: '',
        notes: '',
        payment_method: '',
        down_payment_method: 'cash',
        paid_amount: '',
        currency: currency || '',
        exchange_rate: '1',
        treasury_id: ''
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: '1', unit_price: '', discount: '', unit: '' }
    ])

    const moneyOrDash = (value) => value !== null && value !== undefined && value !== '' ? formatNumber(value) : '—'

    const isPositiveDecimal = (value) => {
        try {
            return new Decimal(value || '0').gt(0)
        } catch {
            return false
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchData = async () => {
                try {
                    const params = { branch_id: currentBranch?.id }
                    const [custRes, groupsRes, prodRes, whRes, curRes, treasRes, priceRes] = await Promise.all([
                        salesAPI.listCustomers(params),
                        salesAPI.listCustomerGroups(params),
                        inventoryAPI.listProducts(params),
                        inventoryAPI.listWarehouses(params),
                        currenciesAPI.list(),
                        treasuryAPI.listAccounts(currentBranch?.id),
                        inventoryAPI.getBranchPrices(currentBranch?.id)
                    ])
                    setCustomers(custRes.data)
                    setCustomerGroups(groupsRes.data)
                    setProducts(prodRes.data)
                    setWarehouses(whRes.data)
                    setCurrencies(curRes.data)
                    setTreasuryAccounts(treasRes.data)
                    
                    // Store branch prices for auto-fill. The server remains
                    // authoritative for totals, taxes, and discounts.
                    window.__branchPrices = priceRes.data?.prices || {}
                    window.__branchCurrency = priceRes.data?.currency || formData.currency

                    const base = curRes.data.find(c => c.is_base)
                    if (base && !formData.currency) {
                        setFormData(prev => ({ ...prev, currency: base.code }))
                    }

                    // Check if we have an order to pre-fill from
                    if (location.state?.fromOrder) {
                        const order = location.state.fromOrder
                        setFormData(prev => ({
                            ...prev,
                            customer_id: order.customer_id,
                            notes: order.notes || '',
                            due_date: order.expected_delivery_date ? new Date(order.expected_delivery_date).toISOString().split('T')[0] : ''
                        }))
                        setItems(order.items.map(item => ({
                            product_id: item.product_id,
                            description: item.description || '',
                            quantity: String(item.quantity || ''),
                            unit_price: String(item.unit_price || ''),
                            tax_rate: null,
                            discount: String(item.discount || ''),
                            unit: item.unit || ''
                        })))
                    }
                } catch (err) {
                    showToast(t('common.error'), 'error')
                } finally {
                    setInitialLoad(false)
                }
            }
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [location.state, currentBranch])

    // Filter warehouses based on current branch
    const filteredWarehouses = warehouses.filter(wh => {
        if (!currentBranch) return true // Show all if no branch selected (or maybe enforce default?)
        return wh.branch_id === currentBranch.id
    })

    // Auto-select warehouse if only one available for branch
    useEffect(() => {
        if (filteredWarehouses.length === 1 && !formData.warehouse_id) {
            setFormData(prev => ({ ...prev, warehouse_id: filteredWarehouses[0].id }))
        }
    }, [filteredWarehouses, formData.warehouse_id])


    // Auto-select treasury if only one available for method
    useEffect(() => {
        let type = null;
        if (formData.payment_method && formData.payment_method !== 'credit') {
            type = formData.payment_method === 'bank' ? 'bank' : 'cash';
        } else if (formData.payment_method === 'credit' && formData.paid_amount > 0) {
            type = formData.down_payment_method === 'bank' ? 'bank' : 'cash';
        }

        if (type) {
            const available = treasuryAccounts.filter(acc => acc.account_type === type);
            if (available.length === 1 && !formData.treasury_id) {
                setFormData(prev => ({ ...prev, treasury_id: available[0].id }));
            }
        }
    }, [formData.payment_method, formData.down_payment_method, formData.paid_amount, treasuryAccounts]);

    const handleItemChange = async (index, field, value) => {
        const newItems = items.map((item, i) => {
            if (i === index) {
                const updatedItem = { ...item, [field]: value }

                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value))
                    if (product) {
                        updatedItem.description = product.item_name
                        const branchPrices = window.__branchPrices || {}
                        const priceInfo = branchPrices[parseInt(value)]
                        updatedItem.unit_price = String(priceInfo ? priceInfo.price : (product.selling_price || ''))
                        updatedItem.unit = product.unit || 'قطعة'
                        updatedItem.tax_rate = null // Resolved by backend engine

                        // Fetch stock for this product
                        fetchProductStock(parseInt(value), formData.warehouse_id)
                    }
                }

                // Validate quantity against available stock
                if (field === 'quantity' && item.product_id) {
                    const productId = parseInt(item.product_id)
                    const availableStock = productStocks[productId] || '0'
                    let exceedsStock = false
                    try {
                        exceedsStock = new Decimal(value || '0').gt(availableStock || '0')
                    } catch {
                        exceedsStock = false
                    }

                    if (exceedsStock) {
                        showToast(t('sales.invoices.form.error_stock', { stock: availableStock }), 'error')
                        updatedItem.quantity = ''
                        return updatedItem
                    }
                }

                return updatedItem
            }
            return item
        })
        setItems(newItems)
    }

    const fetchProductStock = async (productId, warehouseId) => {
        try {
            const res = await inventoryAPI.getProductStock(productId, warehouseId)
            setProductStocks(prev => ({ ...prev, [productId]: res.data }))
        } catch (err) {
            showToast(t('common.error'), 'error')
        }
    }

    // Refresh all stocks when warehouse changes
    useEffect(() => {
        const productIds = [...new Set(items.map(item => item.product_id).filter(id => id))];
        productIds.forEach(id => fetchProductStock(parseInt(id), formData.warehouse_id));
    }, [formData.warehouse_id]);

    const DISCRETE_UNITS = ['قطعة', 'علبة', 'كرتون', 'piece', 'box', 'carton', 'unit'];
    const isDiscreteUnit = (unit) => DISCRETE_UNITS.includes((unit || '').trim().toLowerCase()) || DISCRETE_UNITS.includes((unit || '').trim());

    const addItem = () => {
        setItems([...items, { product_id: '', description: '', quantity: '1', unit_price: '', tax_rate: null, discount: '', unit: '' }])
    }

    const removeItem = (index) => {
        if (items.length <= 1) return // Prevent removing the last item
        const newItems = items.filter((_, i) => i !== index)
        setItems(newItems)
    }

    const getTotals = () => {
        if (calcTotals) {
            return {
                subtotal: calcTotals.subtotal,
                discount: calcTotals.totalDiscount,
                markup: null,
                tax: calcTotals.totalTax,
                total: calcTotals.grandTotal,
                remainingBalance: calcTotals.remainingBalance,
                globalEffectType: 'discount',
                globalEffectPercent: '0',
                globalMakeupAmount: '0',
                globalDiscountAmount: calcTotals.totalDiscount,
            }
        }
        return {
            subtotal: null,
            discount: null,
            markup: null,
            tax: null,
            total: null,
            remainingBalance: null,
            globalEffectType: 'discount',
            globalEffectPercent: '0',
            globalMakeupAmount: '0',
            globalDiscountAmount: null,
        }
    }

    const buildCalculationPayload = () => ({
        lines: items.map(i => ({
            product_id: i.product_id ? parseInt(i.product_id, 10) : null,
            quantity: String(i.quantity || '0'),
            unit_price: String(i.unit_price || '0'),
            discount: String(i.discount || '0'),
        })),
        branch_id: currentBranch?.id || null,
        customer_id: formData.customer_id ? parseInt(formData.customer_id, 10) : null,
        document_date: formData.invoice_date,
        currency: formData.currency || currency,
        paid_amount: String(formData.paid_amount || '0'),
    })

    // Call backend for accurate calculations when items change
    useEffect(() => {
        const hasPreviewableLine = items.some(i => isPositiveDecimal(i.quantity) && isPositiveDecimal(i.unit_price))
        if (hasPreviewableLine) {
            previewDebounced(buildCalculationPayload())
        }
    }, [items, formData.currency, formData.customer_id, formData.invoice_date, formData.paid_amount, currentBranch])

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!formData.customer_id) {
            setError(t('sales.invoices.form.error_customer'))
            window.scrollTo(0, 0)
            return
        }
        if (!formData.payment_method) {
            setError(t('sales.invoices.form.error_payment_method'))
            window.scrollTo(0, 0)
            return
        }
        if (!formData.warehouse_id) {
            setError(t('sales.invoices.form.error_warehouse'))
            window.scrollTo(0, 0)
            return
        }
        // Validate items
        if (items.length === 0 || items.every(i => !i.product_id)) {
            setError(t('sales.invoices.form.error_items'))
            window.scrollTo(0, 0)
            return
        }
        if (items.some(i => i.product_id && !isPositiveDecimal(i.quantity))) {
            setError(t('sales.invoices.form.error_quantity'))
            window.scrollTo(0, 0)
            return
        }
        if (submittingRef.current) {
            return
        }
        submittingRef.current = true
        setLoading(true)
        setError(null)

        try {
            const previewResult = await preview(buildCalculationPayload())
            if (!previewResult) {
                setError('تعذر احتساب إجمالي الفاتورة، يرجى المحاولة مرة أخرى')
                window.scrollTo(0, 0)
                return
            }
            const totals = {
                subtotal: previewResult.subtotal ?? null,
                discount: previewResult.total_discount ?? null,
                markup: null,
                tax: previewResult.total_tax ?? null,
                total: previewResult.grand_total ?? null,
                globalEffectType: 'discount',
                globalEffectPercent: '0',
                globalMakeupAmount: '0',
                globalDiscountAmount: previewResult.total_discount ?? null,
            };
            const payload = {
                ...formData,
                status: 'draft',
                branch_id: currentBranch ? currentBranch.id : null,
                warehouse_id: formData.warehouse_id ? parseInt(formData.warehouse_id) : null,
                customer_id: parseInt(formData.customer_id),
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                due_date: formData.due_date || null,
                down_payment_method: formData.down_payment_method || 'cash',
                paid_amount: String(formData.paid_amount || '0'),
                currency: formData.currency,
                exchange_rate: String(formData.exchange_rate || '1'),
                treasury_id: formData.treasury_id ? parseInt(formData.treasury_id) : null,
                effect_type: totals.globalEffectType,
                effect_percentage: totals.globalEffectPercent,
                markup_amount: totals.globalMakeupAmount,
                items: items.map(item => ({
                    product_id: item.product_id ? parseInt(item.product_id) : null,
                    quantity: String(item.quantity || '0'),
                    unit_price: String(item.unit_price || '0'),
                    discount: String(item.discount || '0'),
                    markup: '0'
                }))
            }
            await salesAPI.createInvoice(payload)
            navigate('/sales/invoices')
        } catch (err) {
            setError(err.response?.data?.detail || t('sales.invoices.form.error_save'))
        } finally {
            submittingRef.current = false
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('sales.invoices.form.title')}</h1>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}

            <form onSubmit={handleSubmit}>
                <div className="card mb-4">
                    <div className="form-row">
                        <div className="form-group" style={{ flex: 2 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                <label className="form-label" style={{ margin: 0 }}>{t('sales.invoices.form.customer')} *</label>
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm"
                                    style={{ padding: '2px 8px', fontSize: '0.8rem' }}
                                    onClick={() => {
                                        const cashCust = customers.find(c => c.name === t('sales.invoices.cash_customer') || c.name_en === 'Cash Customer');
                                        if (cashCust) {
                                            setFormData(prev => ({ ...prev, customer_id: cashCust.id, payment_method: 'cash' }));
                                        } else {
                                            // Fallback: search by ID if we knew it, or just show error
                                            console.warn("Cash customer not found in list");
                                        }
                                    }}
                                >
                                    {t('sales.invoices.form.walk_in_customer')}
                                </button>
                            </div>
                            <select
                                className="form-input"
                                value={formData.customer_id || ''}
                                onChange={(e) => {
                                    setFormData({ ...formData, customer_id: e.target.value });
                                    setItems(prevItems => prevItems.map(item => {
                                        let updated = { ...item };
                                        if (item.product_id) {
                                            const product = products.find(p => p.id === parseInt(item.product_id));
                                            if (product) {
                                                updated.unit_price = String(product.selling_price || '');
                                            }
                                        }
                                        return updated;
                                    }));
                                }}
                                required
                            >
                                <option value="">{t('sales.invoices.form.select_customer')}</option>
                                {customers.map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                        </div>
                        <FormField label={t('stock.warehouses.title')} style={{ flex: 1 }}>
                            <select
                                className="form-input"
                                value={formData.warehouse_id || ''}
                                onChange={(e) => setFormData({ ...formData, warehouse_id: e.target.value })}
                            >
                                <option value="">{t('common.select')}</option>
                                {filteredWarehouses.map(wh => (
                                    <option key={wh.id} value={wh.id}>{wh.name}</option>
                                ))}
                            </select>
                        </FormField>
                        <FormField>
                            <CustomDatePicker
                                label={t('sales.invoices.form.date')}
                                selected={formData.invoice_date}
                                onChange={(dateStr) => setFormData({ ...formData, invoice_date: dateStr })}
                                required
                            />
                        </FormField>
                    </div>
                </div>


                <div className="invoice-items-container" style={{ margin: '24px 0', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '30%' }}>{t('sales.invoices.form.items.product')}</th>
                                <th style={{ width: '10%' }}>{t('sales.invoices.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('sales.invoices.form.items.price')}</th>
                                <th style={{ width: '10%' }}>{t('sales.invoices.form.items.discount')}</th>
                                <th style={{ width: '10%' }}>{t('sales.invoices.form.items.tax')}</th>
                                <th style={{ width: '15%' }}>{t('sales.invoices.form.items.total')}</th>
                                <th style={{ width: '5%' }}></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((item, index) => {
                                const backendLine = backendLines?.[index] || null
                                return (
                                    <tr key={index}>
                                        <td>
                                            <select
                                                className="form-input"
                                                style={{ marginBottom: '4px' }}
                                                value={item.product_id || ''}
                                                onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                            >
                                                <option value="">{t('sales.invoices.form.items.select_product')}</option>
                                                {products.map(p => (
                                                    <option key={p.id} value={p.id}>{p.item_name}</option>
                                                ))}
                                            </select>
                                            <input
                                                type="text" className="form-input" placeholder={t('sales.invoices.form.items.desc_placeholder')}
                                                value={item.description || ''}
                                                onChange={(e) => handleItemChange(index, 'description', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <input
                                                type="text" inputMode="decimal" className="form-input"
                                                step={isDiscreteUnit(item.unit) ? "1" : getStep()}
                                                value={item.quantity}
                                                onChange={(e) => handleItemChange(index, 'quantity', e.target.value)}
                                            />
                                            {item.product_id && productStocks[item.product_id] !== undefined && (
                                                <small style={{ display: 'block', color: '#666', marginTop: '2px' }}>
                                                    {t('sales.invoices.form.items.available_stock')} {productStocks[item.product_id]}
                                                </small>
                                            )}
                                        </td>
                                        <td>
                                            <input
                                                type="text" inputMode="decimal" className="form-input"
                                                value={item.unit_price}
                                                onChange={(e) => handleItemChange(index, 'unit_price', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <input
                                                type="text" inputMode="decimal" className="form-input"
                                                value={item.discount}
                                                onChange={(e) => handleItemChange(index, 'discount', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <div style={{ padding: '6px 4px', fontSize: '13px', textAlign: 'center' }}>
                                                <div style={{ fontWeight: '600', color: 'var(--primary)' }}>
                                                    {backendLine?.tax_rate != null ? `${backendLine.tax_rate}%` : '—'}
                                                </div>
                                                {backendLine?.applied_taxes?.length ? (
                                                    <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                                                        {backendLine.applied_taxes.map(tax => tax.tax_name).filter(Boolean).join(', ')}
                                                    </div>
                                                ) : null}
                                            </div>
                                        </td>
                                        <td style={{ fontWeight: 'bold' }}>{moneyOrDash(backendLine?.line_total)}</td>
                                        <td>
                                            {items.length > 1 && (
                                                <button type="button" className="btn-icon text-danger" onClick={() => removeItem(index)}>
                                                    🗑️
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                    <div style={{ padding: '12px', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border-color)' }}>
                        <button type="button" className="btn btn-secondary btn-sm" onClick={addItem}>
                            {t('sales.invoices.form.items.add_row')}
                        </button>
                    </div>
                </div>

                {/* Footer Totals & Payment */}
                <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start', marginTop: '24px' }}>
                    <div style={{ flex: 1 }}>
                        <h4 style={{ marginBottom: '12px' }}>{t('sales.invoices.form.payment.title')}</h4>

                        {/* Currency Selection */}
                        <div className="form-row mb-3">
                            <FormField label={t('common.currency')} style={{ flex: 1 }}>
                                <select
                                    className="form-input form-input-sm"
                                    value={formData.currency}
                                    onChange={async e => {
                                        const code = e.target.value;
                                        const curr = currencies.find(c => c.code === code);
                                        // T8.4: prefer the live rate from /accounting/currencies/current.
                                        // Falls back to the legacy `current_rate` field, then 1.0.
                                        let rate = String(curr?.current_rate || '1');
                                        try {
                                            rate = await fetchCurrentRate(code);
                                        } catch { /* keep fallback */ }
                                        setFormData(prev => ({
                                            ...prev,
                                            currency: code,
                                            exchange_rate: String(rate || '1')
                                        }));
                                    }}
                                >
                                    {currencies.map(c => (
                                        <option key={c.id} value={c.code}>{c.code} - {c.name}</option>
                                    ))}
                                </select>
                            </FormField>
                            {formData.currency !== currency && (
                                <FormField label={t('accounting.currencies.table.rate')} style={{ flex: 1 }}>
                                    <input
                                        type="text"
                                        inputMode="decimal"
                                        step="0.000001"
                                        className="form-input form-input-sm font-mono"
                                        value={formData.exchange_rate}
                                        onChange={e => setFormData({ ...formData, exchange_rate: e.target.value })}
                                    />
                                </FormField>
                            )}
                        </div>

                        <FormField label={t('sales.invoices.form.payment.method')}>
                            <div style={{ display: 'flex', gap: '16px' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input
                                        type="radio" name="payment_method" value="cash"
                                        checked={formData.payment_method === 'cash'}
                                        onChange={e => setFormData({ ...formData, payment_method: e.target.value, paid_amount: getTotals().total || '', treasury_id: '' })}
                                    />
                                    {t('sales.invoices.form.payment.cash')}
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input
                                        type="radio" name="payment_method" value="bank"
                                        checked={formData.payment_method === 'bank'}
                                        onChange={e => setFormData({ ...formData, payment_method: e.target.value, paid_amount: getTotals().total || '', treasury_id: '' })}
                                    />
                                    {t('sales.invoices.form.payment.bank')}
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input
                                        type="radio" name="payment_method" value="credit"
                                        checked={formData.payment_method === 'credit'}
                                        onChange={e => setFormData({ ...formData, payment_method: e.target.value, paid_amount: '', treasury_id: '' })}
                                    />
                                    {t('sales.invoices.form.payment.credit')}
                                </label>
                            </div>
                        </FormField>

                        {formData.payment_method && formData.payment_method !== 'credit' && (
                            <div className="form-group animate-fade-in">
                                <label className="form-label">{t('sales.invoices.form.payment.paid_amount')}</label>
                                <div className="input-with-suffix" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                                    <input
                                        type="text"
                                        inputMode="decimal"
                                        className="form-input"
                                        step={getStep()}
                                        min="0"
                                        value={formData.paid_amount}
                                        onChange={e => setFormData({ ...formData, paid_amount: e.target.value })}
                                    />
                                    <span className="input-suffix">{formData.currency}</span>
                                </div>
                                <label className="form-label">
                                    {formData.payment_method === 'bank' ? (t('treasury.accounts.bank')) : (t('treasury.accounts.cash'))}
                                </label>
                                <select
                                    className="form-input"
                                    value={formData.treasury_id || ''}
                                    onChange={e => setFormData({ ...formData, treasury_id: e.target.value })}
                                    required
                                >
                                    <option value="">{t('common.select')}</option>
                                    {treasuryAccounts
                                        .filter(acc => acc.account_type === (formData.payment_method === 'bank' ? 'bank' : 'cash'))
                                        .map(acc => (
                                            <option key={acc.id} value={acc.id}>
                                                {acc.name}
                                            </option>
                                        ))}
                                </select>
                                {formData.treasury_id && (
                                    <div className="account-balance-hint mt-1" style={{ fontSize: '0.85rem' }}>
                                        <span className="text-muted">{t('treasury.available_balance')}: </span>
                                        <span className="fw-bold" style={{ color: 'var(--primary-color)' }}>
                                            {formatNumber(treasuryAccounts.find(a => a.id.toString() === formData.treasury_id.toString())?.current_balance)} {currency}
                                        </span>
                                    </div>
                                )}
                            </div>
                        )}

                        {formData.payment_method === 'credit' && (
                            <div className="form-group">
                                <label className="form-label">{t('sales.invoices.form.payment.paid_amount')}</label>
                                <div className="input-with-suffix" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                                    <input
                                        type="text" inputMode="decimal" className="form-input" step={getStep()}
                                        min="0"
                                        value={formData.paid_amount}
                                        onChange={e => setFormData({ ...formData, paid_amount: e.target.value })}
                                    />
                                    <span className="input-suffix">{formData.currency}</span>
                                </div>

                                {isPositiveDecimal(formData.paid_amount) && (
                                    <div className="form-group mb-2 animate-fade-in">
                                        <label className="form-label" style={{ fontSize: '0.85rem' }}>{t('sales.invoices.form.payment.down_payment_method')}</label>
                                        <div style={{ display: 'flex', gap: '16px' }}>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>
                                                <input
                                                    type="radio" name="down_payment_method" value="cash"
                                                    checked={(formData.down_payment_method || 'cash') === 'cash'}
                                                    onChange={e => setFormData({ ...formData, down_payment_method: e.target.value, treasury_id: '' })}
                                                />
                                                {t('sales.invoices.form.payment.cash')}
                                            </label>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>
                                                <input
                                                    type="radio" name="down_payment_method" value="bank"
                                                    checked={formData.down_payment_method === 'bank'}
                                                    onChange={e => setFormData({ ...formData, down_payment_method: e.target.value, treasury_id: '' })}
                                                />
                                                {t('sales.invoices.form.payment.bank')}
                                            </label>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>
                                                <input
                                                    type="radio" name="down_payment_method" value="check"
                                                    checked={formData.down_payment_method === 'check'}
                                                    onChange={e => setFormData({ ...formData, down_payment_method: e.target.value })}
                                                />
                                                {t('sales.invoices.form.payment.check')}
                                            </label>
                                        </div>

                                        {(formData.down_payment_method === 'cash' || formData.down_payment_method === 'bank') && (
                                            <div style={{ marginTop: '8px' }}>
                                                <select
                                                    className="form-input form-input-sm"
                                                    value={formData.treasury_id || ''}
                                                    onChange={e => setFormData({ ...formData, treasury_id: e.target.value })}
                                                    required
                                                >
                                                    <option value="">{t('treasury.accounts.select_account')}</option>
                                                    {treasuryAccounts
                                                        .filter(acc => acc.account_type === (formData.down_payment_method === 'bank' ? 'bank' : 'cash'))
                                                        .map(acc => (
                                                            <option key={acc.id} value={acc.id}>
                                                                {acc.name}
                                                            </option>
                                                        ))}
                                                </select>
                                            </div>
                                        )}
                                    </div>
                                )}

                                <small style={{ color: 'var(--text-secondary)' }}>
                                    {t('sales.invoices.form.payment.remaining_msg', { amount: moneyOrDash(getTotals().remainingBalance) + ' ' + formData.currency })}
                                </small>
                            </div>
                        )}


                        <FormField label={t('sales.invoices.form.notes')}>
                            <textarea
                                className="form-input" rows="3"
                                value={formData.notes}
                                onChange={e => setFormData({ ...formData, notes: e.target.value })}
                            ></textarea>
                        </FormField>
                    </div>

                    <div style={{ width: '300px', padding: '24px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.invoices.form.totals.subtotal')}</span>
                            <span>{formData.currency} {moneyOrDash(getTotals().subtotal)}</span>
                        </div>
                        {isPositiveDecimal(getTotals().globalEffectPercent) && getTotals().globalEffectType === 'markup' && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: 'var(--text-success)' }}>
                                <span>زيادة (مجموعة) ({getTotals().globalEffectPercent}%)</span>
                                <span>{formData.currency} {moneyOrDash(getTotals().markup)}</span>
                            </div>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.invoices.form.totals.discount')}</span>
                            <span>{formData.currency} {moneyOrDash(getTotals().discount)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.invoices.form.totals.tax')}</span>
                            <span>{formData.currency} {moneyOrDash(getTotals().tax)}</span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span style={{ fontWeight: 'bold' }}>{t('sales.invoices.form.totals.grand_total')}</span>
                            <span style={{ fontWeight: 'bold', fontSize: '1.2rem' }}>
                                {formData.currency} {moneyOrDash(getTotals().total)}
                            </span>
                        </div>

                        <button
                            type="submit"
                            className="btn btn-primary"
                            style={{ width: '100%', marginTop: '24px', padding: '12px' }}
                            disabled={loading}
                        >
                            {loading ? t('sales.invoices.form.saving') : t('sales.invoices.form.save_btn')}
                        </button>
                        <button
                            type="button"
                            className="btn btn-secondary mt-2"
                            style={{ width: '100%' }}
                            onClick={() => navigate('/sales/invoices')}
                        >
                            {t('common.cancel')}
                        </button>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default InvoiceForm
