import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { purchasesAPI, inventoryAPI, currenciesAPI, treasuryAPI } from '../../utils/api'
import { fetchCurrentRate } from '../../hooks/useExchangeRate'
import { getCurrency } from '../../utils/auth'
import { formatNumber, getStep } from '../../utils/format'
import { useTranslation } from 'react-i18next'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import useInvoiceCalc from '../../hooks/useInvoiceCalc'

function PurchaseInvoiceForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const location = useLocation()
    const { showToast } = useToast()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const currency = getCurrency()

    // Data Sources
    const [suppliers, setSuppliers] = useState([])
    const [supplierGroups, setSupplierGroups] = useState([])
    const [products, setProducts] = useState([])
    const [warehouses, setWarehouses] = useState([])
    const [currencies, setCurrencies] = useState([])
    const [treasuryAccounts, setTreasuryAccounts] = useState([])
    const { currentBranch } = useBranch()

    // Form State
    const [formData, setFormData] = useState({
        supplier_id: '',
        party_site_id: '',
        warehouse_id: '',
        invoice_date: new Date().toISOString().split('T')[0],
        due_date: new Date().toISOString().split('T')[0],
        payment_method: '',
        paid_amount: 0,
        notes: '',
        currency: currency || '',
        exchange_rate: 1.0,
        treasury_id: '',
        is_prepayment: false
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, total: 0 }
    ])

    useEffect(() => {
        const fetchResources = async () => {
            try {
                const params = { branch_id: currentBranch?.id }
                const [suppRes, groupsRes, prodRes, whRes, curRes, treasRes] = await Promise.all([
                    inventoryAPI.listSuppliers(params),
                    purchasesAPI.listSupplierGroups(params),
                    inventoryAPI.listProducts(params),
                    inventoryAPI.listWarehouses(params),
                    currenciesAPI.list(),
                    treasuryAPI.listAccounts(currentBranch?.id)
                ])
                setSuppliers(suppRes.data)
                setSupplierGroups(groupsRes.data)
                setProducts(prodRes.data)
                setWarehouses(whRes.data)
                setCurrencies(curRes.data)
                setTreasuryAccounts(treasRes.data)

                const base = curRes.data.find(c => c.is_base)
                if (base && !formData.currency) {
                    setFormData(prev => ({ ...prev, currency: base.code }))
                }

                // Check if we have an order to pre-fill from
                if (location.state?.fromOrder) {
                    const order = location.state.fromOrder
                    setFormData(prev => ({
                        ...prev,
                        supplier_id: order.supplier_id,
                        notes: order.notes || '',
                        due_date: order.expected_date ? new Date(order.expected_date).toISOString().split('T')[0] : new Date().toISOString().split('T')[0],
                        is_prepayment: false
                    }))
                    setItems(order.items.map(item => {
                        const quantity = Number(item.received_quantity) > 0 ? Number(item.received_quantity) : (Number(item.quantity) || 0)
                        const unitPrice = Number(item.unit_price) || 0
                        const discount = Number(item.discount) || 0
                        const discountPercent = (quantity * unitPrice) > 0 ? (discount / (quantity * unitPrice)) * 100 : 0

                        return {
                            product_id: item.product_id,
                            description: item.description || '',
                            quantity: quantity,
                            unit_price: unitPrice,
                            tax_rate: Number(item.tax_rate) || 0,
                            discount: discount,
                            discount_percent: discountPercent
                        }
                    }))
                }
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
    }, [location.state, currentBranch])

    // Auto-select warehouse and Reset if branch mismatch
    useEffect(() => {
        const availableWh = warehouses.filter(wh => !currentBranch || wh.branch_id === currentBranch.id)
        if (availableWh.length === 1 && !formData.warehouse_id) {
            setFormData(prev => ({ ...prev, warehouse_id: availableWh[0].id }))
        }
        // If current warehouse_id is not in available list, reset it
        if (formData.warehouse_id && !availableWh.find(wh => wh.id === parseInt(formData.warehouse_id))) {
            setFormData(prev => ({ ...prev, warehouse_id: '' }))
        }
    }, [warehouses, currentBranch, formData.warehouse_id])

    // Calculations
    // Backend-powered calculations
    const { totals: backendTotals, previewDebounced, quickCalc } = useInvoiceCalc()

    const calculateTotals = () => {
        // Use backend totals if available
        if (backendTotals) {
            return {
                subtotal: backendTotals.subtotal,
                totalDiscount: backendTotals.totalDiscount,
                totalMarkup: 0,
                totalTax: backendTotals.totalTax,
                total: backendTotals.grandTotal,
                globalEffectType: 'discount',
                globalEffectPercent: 0,
                globalMakeupAmount: 0,
                globalDiscountAmount: backendTotals.totalDiscount,
            }
        }
        // Fallback to local calculation
        let subtotal = 0
        let totalTax = 0
        let totalDiscount = 0

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
            const lineTotal = item.quantity * item.unit_price
            subtotal += lineTotal
            totalDiscount += item.discount
        })

        let totalAfterLineDiscounts = subtotal - totalDiscount;
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
            const weight = (item.quantity * item.unit_price - item.discount) / totalAfterLineDiscounts || 0;
            const itemBase = (item.quantity * item.unit_price - item.discount)
                - (globalDiscountAmount * weight)
                + (globalMarkupAmount * weight);
            totalTax += itemBase * (item.tax_rate / 100);
        });

        const total = baseForTax + totalTax
        return {
            subtotal,
            totalTax,
            totalDiscount: totalDiscount + globalDiscountAmount,
            totalMarkup: globalMarkupAmount,
            total,
            globalEffectType,
            globalEffectPercent,
            globalMarkupAmount,
            globalDiscountAmount
        }
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

    const totals = calculateTotals()

    // Handlers
    const handleItemChange = (index, field, value) => {
        const newItems = items.map((item, i) => {
            if (i === index) {
                const updatedItem = { ...item }

                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value))
                    if (product) {
                        updatedItem.description = product.item_name || ''
                        // Use branch price if available, otherwise use product default
                        const branchPrices = window.__branchPrices || {}
                        const priceInfo = branchPrices[parseInt(value)]
                        updatedItem.unit_price = priceInfo ? priceInfo.price : (product.last_buying_price || product.buying_price || 0)
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
                                    const basePrice = priceInfo ? priceInfo.price : (product.last_buying_price || product.buying_price || 0)
                                    updatedItem.unit_price = basePrice * (1 + (group.discount_percentage / 100));
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

                updatedItem[field] = ['quantity', 'unit_price', 'tax_rate', 'discount', 'discount_percent'].includes(field)
                    ? (value === '' ? '' : Number(value) || 0)
                    : value
                return updatedItem
            }
            return item
        })
        setItems(newItems)
    }

    const addItem = () => {
        setItems([...items, { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, total: 0 }])
    }

    const removeItem = (index) => {
        if (items.length > 1) {
            setItems(items.filter((_, i) => i !== index))
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()

        if (!formData.supplier_id) {
            setError(t('buying.purchase_invoices.form.error_supplier_required'))
            window.scrollTo(0, 0)
            return
        }

        if (!formData.warehouse_id) {
            setError(t('buying.purchase_invoices.form.error_warehouse'))
            window.scrollTo(0, 0)
            return
        }

        const hasEmptyProduct = items.some(item => !item.product_id)
        if (hasEmptyProduct) {
            setError(t('buying.purchase_invoices.form.error_product_required'))
            window.scrollTo(0, 0)
            return
        }

        setLoading(true)
        setError(null)

        try {
            const payload = {
                branch_id: currentBranch ? currentBranch.id : null,
                warehouse_id: formData.warehouse_id ? parseInt(formData.warehouse_id) : null,
                supplier_id: parseInt(formData.supplier_id),
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                invoice_date: formData.invoice_date,
                due_date: formData.due_date,
                payment_method: formData.payment_method,
                paid_amount: String(formData.paid_amount || 0),
                notes: formData.notes,
                currency: formData.currency,
                exchange_rate: String(formData.exchange_rate || 1.0),
                treasury_id: formData.treasury_id ? parseInt(formData.treasury_id) : null,
                is_prepayment: formData.is_prepayment,
                original_invoice_id: location.state?.fromOrder?.id || null,
                effect_type: totals.globalEffectType,
                effect_percentage: totals.globalEffectPercent,
                markup_amount: totals.globalMarkupAmount,
                items: items.map(item => ({
                    product_id: parseInt(item.product_id) || null,
                    description: item.description || '',
                    quantity: String(item.quantity || 0),
                    unit_price: String(item.unit_price || 0),
                    tax_rate: String(item.tax_rate || 0),
                    discount: String(item.discount || 0),
                    markup: 0 // Handled at line level unit_price for purchases
                }))
            }

            await purchasesAPI.createInvoice(payload)
            navigate('/buying/invoices')
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
            const errMsg = err.response?.data?.detail
            setError(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg) || t('buying.purchase_invoices.form.error_saving'))
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('buying.purchase_invoices.form.title_new')}</h1>
                    <p className="workspace-subtitle">{t('buying.purchase_invoices.form.subtitle_new')}</p>
                </div>

                <div className="prepayment-toggle-wrapper" style={{
                    background: formData.is_prepayment ? 'rgba(52, 152, 219, 0.1)' : 'var(--card-bg)',
                    padding: '8px 16px',
                    borderRadius: '50px',
                    border: formData.is_prepayment ? '1px solid var(--primary)' : '1px solid var(--border-color)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    cursor: 'pointer',
                    transition: 'all 0.3s'
                }}
                    onClick={() => setFormData({ ...formData, is_prepayment: !formData.is_prepayment })}
                >
                    <span style={{
                        fontSize: '14px',
                        fontWeight: 'bold',
                        color: formData.is_prepayment ? 'var(--primary)' : 'var(--text-secondary)'
                    }}>
                        {t('buying.purchase_invoices.form.prepayment_label')}
                    </span>
                    <div className="switch" style={{
                        width: '40px',
                        height: '20px',
                        background: formData.is_prepayment ? 'var(--primary)' : '#ccc',
                        borderRadius: '20px',
                        position: 'relative',
                        transition: '0.3s'
                    }}>
                        <div style={{
                            width: '16px',
                            height: '16px',
                            background: '#fff',
                            borderRadius: '50%',
                            position: 'absolute',
                            top: '2px',
                            left: formData.is_prepayment ? '22px' : '2px',
                            transition: '0.3s'
                        }} />
                    </div>
                </div>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}

            <form onSubmit={handleSubmit} className="card">
                {/* Header Info */}
                <div className="form-row">
                    <FormField label={t('buying.purchase_invoices.form.supplier')} required style={{ flex: 2 }}>
                        <select
                            className="form-input"
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
                                    }
                                    return updated;
                                }));
                            }}
                            required
                        >
                            <option value="">{t('buying.purchase_invoices.form.supplier_placeholder')}</option>
                            {suppliers.map(s => <option key={s.id} value={s.id}>{s.name || t('common.no_name')}</option>)}
                        </select>
                    </FormField>
                    <FormField label={t('stock.warehouses.title')} style={{ flex: 1 }}>
                        <select
                            className="form-input"
                            value={formData.warehouse_id || ''}
                            onChange={(e) => setFormData({ ...formData, warehouse_id: e.target.value })}
                        >
                            <option value="">{t('common.select')}</option>
                            {warehouses.filter(wh => !currentBranch || wh.branch_id === currentBranch.id).map(wh => (
                                <option key={wh.id} value={wh.id}>{wh.name}</option>
                            ))}
                        </select>
                    </FormField>
                    <FormField>
                        <CustomDatePicker
                            label={t('buying.purchase_invoices.form.invoice_date')}
                            selected={formData.invoice_date}
                            onChange={(dateStr) => setFormData({ ...formData, invoice_date: dateStr })}
                        />
                    </FormField>
                    <FormField>
                        <CustomDatePicker
                            label={t('buying.purchase_invoices.form.due_date')}
                            selected={formData.due_date}
                            onChange={(dateStr) => setFormData({ ...formData, due_date: dateStr })}
                        />
                    </FormField>



                </div>


                {/* Items Table */}
                <div className="invoice-items-container" style={{ margin: '24px 0', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '30%' }}>{t('buying.purchase_invoices.form.items.product')}</th>
                                <th style={{ width: '10%' }}>{t('buying.purchase_invoices.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('buying.purchase_invoices.form.items.unit_price')}</th>
                                <th style={{ width: '10%' }}>{t('buying.purchase_invoices.form.items.discount')} (%)</th>
                                <th style={{ width: '10%' }}>{t('buying.purchase_invoices.form.items.tax_rate')}</th>
                                <th style={{ width: '15%' }}>{t('buying.purchase_invoices.form.items.total')}</th>
                                <th style={{ width: '5%' }}></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((item, index) => {
                                const lineTotal = (item.quantity || 0) * (item.unit_price || 0) - (item.discount || 0);
                                const withTax = lineTotal * (1 + (item.tax_rate || 0) / 100);
                                return (
                                    <tr key={index}>
                                        <td>
                                            <select
                                                className="form-input"
                                                style={{ marginBottom: '4px' }}
                                                value={item.product_id || ''}
                                                onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                            >
                                                <option value="">{t('buying.purchase_invoices.form.items.product_placeholder')}</option>
                                                {products.map(p => <option key={p.id} value={p.id}>{p.item_name}</option>)}
                                            </select>
                                            <input
                                                type="text"
                                                className="form-input"
                                                placeholder={t('buying.purchase_invoices.form.items.desc_placeholder')}
                                                value={item.description || ''}
                                                onChange={e => handleItemChange(index, 'description', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <input
                                                type="number" className="form-input" min="1" step={getStep()}
                                                value={item.quantity || ''}
                                                onChange={e => handleItemChange(index, 'quantity', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <input
                                                type="number" className="form-input" step={getStep()}
                                                value={item.unit_price || ''}
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
                                                type="number" className="form-input"
                                                value={item.tax_rate || ''}
                                                onChange={e => handleItemChange(index, 'tax_rate', e.target.value)}
                                            />
                                        </td>
                                        <td>
                                            <div style={{ fontWeight: 'bold' }}>
                                                {formatNumber(withTax)}
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
                                )
                            })}
                        </tbody>
                    </table>
                    <div style={{ padding: '8px', background: 'var(--bg-secondary)' }}>
                        <button type="button" className="btn btn-secondary btn-sm" onClick={addItem}>{t('buying.purchase_invoices.form.items.add_line')}</button>
                    </div>
                </div>

                {/* Footer Totals & Payment */}
                <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                        <h4 style={{ marginBottom: '12px' }}>{t('buying.purchase_invoices.form.payment.title')}</h4>
                        {/* Currency Selection */}
                        <div className="form-row mb-3">
                            <FormField label={t('common.currency')} style={{ flex: 1 }}>
                                <select
                                    className="form-input form-input-sm"
                                    value={formData.currency}
                                    onChange={async e => {
                                        const code = e.target.value;
                                        const curr = currencies.find(c => c.code === code);
                                        // T8.4: live rate from /accounting/currencies/current.
                                        let rate = curr?.current_rate || 1.0;
                                        try { rate = await fetchCurrentRate(code); } catch { /* keep fallback */ }
                                        setFormData(prev => ({
                                            ...prev,
                                            currency: code,
                                            exchange_rate: rate || 1.0
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
                                        type="number"
                                        step="0.000001"
                                        className="form-input form-input-sm font-mono"
                                        value={formData.exchange_rate}
                                        onChange={e => setFormData({ ...formData, exchange_rate: e.target.value })}
                                    />
                                </FormField>
                            )}
                        </div>

                        <FormField label={t('buying.purchase_invoices.form.payment.method')} required>
                            <div style={{ display: 'flex', gap: '16px' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input
                                        type="radio" name="payment_method" value="cash"
                                        checked={formData.payment_method === 'cash'}
                                        onChange={e => setFormData({ ...formData, payment_method: e.target.value })}
                                        required
                                        onInvalid={e => e.target.setCustomValidity(t('buying.payments.form.validation.payment_method_required'))}
                                        onInput={e => e.target.setCustomValidity('')}
                                    />
                                    {t('buying.purchase_invoices.form.payment.methods.cash')}
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input
                                        type="radio" name="payment_method" value="bank"
                                        checked={formData.payment_method === 'bank'}
                                        onChange={e => setFormData({ ...formData, payment_method: e.target.value })}
                                    />
                                    {t('buying.purchase_invoices.form.payment.methods.bank')}
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                    <input
                                        type="radio" name="payment_method" value="credit"
                                        checked={formData.payment_method === 'credit'}
                                        onChange={e => setFormData({ ...formData, payment_method: e.target.value })}
                                    />
                                    {t('buying.purchase_invoices.form.payment.methods.credit')}
                                </label>
                            </div>
                        </FormField>

                        {formData.is_prepayment && (
                            <div style={{ background: 'rgba(52, 152, 219, 0.1)', padding: '12px', borderRadius: '8px', borderLeft: '4px solid var(--primary)', marginTop: '16px' }}>
                                <p style={{ fontSize: '13px', margin: 0, color: 'var(--primary)' }}>
                                    {t('buying.invoices.proactive_warning')}
                                </p>
                            </div>
                        )}

                        {formData.payment_method && formData.payment_method !== 'credit' && (
                            <FormField label={formData.payment_method === 'bank' ? t('treasury.accounts.bank') : t('treasury.accounts.cash')} required>
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
                            </FormField>
                        )}

                        {formData.payment_method === 'credit' && (
                            <FormField label={t('buying.purchase_invoices.form.payment.paid_amount')}>
                                <div className="input-with-suffix">
                                    <input
                                        type="number" className="form-input"
                                        value={formData.paid_amount}
                                        onChange={e => setFormData({ ...formData, paid_amount: e.target.value })}
                                        min="0" step={getStep()}
                                    />
                                    <span className="input-suffix">{formData.currency}</span>
                                </div>

                                {Number(formData.paid_amount) > 0 && (
                                    <div style={{ marginTop: '12px' }}>
                                        <label className="form-label" style={{ fontSize: '0.9rem' }}>{t('buying.purchase_invoices.form.payment.down_payment_method')}:</label>
                                        <div style={{ display: 'flex', gap: '16px' }}>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                                <input
                                                    type="radio"
                                                    name="down_payment_method"
                                                    value="cash"
                                                    checked={!formData.down_payment_method || formData.down_payment_method === 'cash'}
                                                    onChange={e => {
                                                        setFormData({ ...formData, down_payment_method: e.target.value, treasury_id: '' })
                                                    }}
                                                />
                                                <span style={{ fontSize: '14px' }}>{t('buying.purchase_invoices.form.payment.down_payment_methods.cash')}</span>
                                            </label>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                                <input
                                                    type="radio"
                                                    name="down_payment_method"
                                                    value="bank"
                                                    checked={formData.down_payment_method === 'bank'}
                                                    onChange={e => {
                                                        setFormData({ ...formData, down_payment_method: e.target.value, treasury_id: '' })
                                                    }}
                                                />
                                                <span style={{ fontSize: '14px' }}>{t('buying.purchase_invoices.form.payment.down_payment_methods.bank')}</span>
                                            </label>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                                <input
                                                    type="radio"
                                                    name="down_payment_method"
                                                    value="check"
                                                    checked={formData.down_payment_method === 'check'}
                                                    onChange={e => setFormData({ ...formData, down_payment_method: e.target.value })}
                                                />
                                                <span style={{ fontSize: '14px' }}>{t('buying.purchase_invoices.form.payment.down_payment_methods.check')}</span>
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

                                <small style={{ color: 'var(--text-secondary)', display: 'block', marginTop: '8px' }}>
                                    {t('buying.purchase_invoices.form.payment.remaining_note')} ({formatNumber(totals.total - formData.paid_amount)} {formData.currency})
                                </small>
                            </FormField>
                        )}

                        <FormField label={t('buying.purchase_invoices.form.notes')}>
                            <textarea
                                className="form-input" rows="3"
                                value={formData.notes}
                                onChange={e => setFormData({ ...formData, notes: e.target.value })}
                            ></textarea>
                        </FormField>
                    </div>

                    <div style={{ width: '300px', padding: '24px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.purchase_invoices.form.summary.subtotal')}</span>
                            <span>{formatNumber(totals.subtotal)} <small>{formData.currency}</small></span>
                        </div>
                        {totals.globalEffectPercent > 0 && totals.globalEffectType === 'markup' && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: 'var(--text-success)' }}>
                                <span>زيادة (مجموعة) ({totals.globalEffectPercent}%)</span>
                                <span>{formatNumber(totals.totalMarkup)} <small>{formData.currency}</small></span>
                            </div>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.purchase_invoices.form.summary.discount')}</span>
                            <span>{formatNumber(totals.totalDiscount)} <small>{formData.currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.purchase_invoices.form.summary.tax')}</span>
                            <span>{formatNumber(totals.totalTax)} <small>{formData.currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '18px' }}>
                            <span>{t('buying.purchase_invoices.form.summary.grand_total')}</span>
                            <span>{formatNumber(totals.total)} <small>{formData.currency}</small></span>
                        </div>

                        {formData.currency !== currency && (
                            <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px dashed var(--border-color)', fontSize: '0.9rem' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                                    <span>{t('accounting.currencies.table.rate') || 'Exchange Rate'}:</span>
                                    <span>1 {formData.currency} = {formData.exchange_rate} {currency}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--primary)', fontWeight: 'bold', marginTop: '4px' }}>
                                    <span>{t('accounting.currencies.total_base') || 'Total in Base'}:</span>
                                    <span>{formatNumber(totals.total * formData.exchange_rate, 2)} <small>{currency}</small></span>
                                </div>
                            </div>
                        )}

                        <button
                            type="submit"
                            className="btn btn-primary"
                            style={{ width: '100%', marginTop: '24px', padding: '12px' }}
                            disabled={loading}
                        >
                            {loading ? t('buying.purchase_invoices.form.saving') : t('buying.purchase_invoices.form.submit')}
                        </button>
                    </div>
                </div>
            </form >
        </div >
    )
}

export default PurchaseInvoiceForm
