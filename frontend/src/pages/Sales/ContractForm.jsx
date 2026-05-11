import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { salesAPI, inventoryAPI, contractsAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { useTranslation } from 'react-i18next'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import { PageLoading } from '../../components/common/LoadingStates'
import useInvoiceCalc from '../../hooks/useInvoiceCalc'

function ContractForm() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const { id } = useParams()
    const currency = getCurrency()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [customers, setCustomers] = useState([])
    const [products, setProducts] = useState([])
    const { currentBranch } = useBranch()
    const [error, setError] = useState(null)

    const [formData, setFormData] = useState({
        contract_number: `CON-${Date.now().toString().slice(-6)}`,
        party_id: '',
        contract_type: 'subscription',
        start_date: new Date().toISOString().split('T')[0],
        end_date: '',
        billing_interval: 'monthly',
        total_amount: 0,
        currency: currency || '',
        notes: ''
    })

    const [items, setItems] = useState([
        { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0 }
    ])

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchData = async () => {
                try {
                    const [custRes, prodRes] = await Promise.all([
                        salesAPI.listCustomers({ branch_id: currentBranch?.id }),
                        inventoryAPI.listProducts({ branch_id: currentBranch?.id })
                    ])
                    setCustomers(custRes.data)
                    setProducts(prodRes.data)

                    if (id) {
                        setLoading(true)
                        const res = await contractsAPI.getContract(id)
                        const c = res.data
                        setFormData({
                            ...c,
                            party_id: c.party_id.toString()
                        })
                        setItems(c.items.map(item => ({
                            ...item,
                            product_id: item.product_id.toString()
                        })))
                        setLoading(false)
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
    }, [id, currentBranch])

    const handleItemChange = (index, field, value) => {
        const newItems = items.map((item, i) => {
            if (i === index) {
                const updatedItem = { ...item, [field]: value }
                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value))
                    if (product) {
                        updatedItem.description = product.item_name
                        updatedItem.unit_price = product.selling_price
                        updatedItem.tax_rate = null // Resolved by backend engine
                    }
                }
                return updatedItem
            }
            return item
        })
        setItems(newItems)
    }

    const addItem = () => setItems([...items, { product_id: '', description: '', quantity: 1, unit_price: 0, tax_rate: 0 }])
    const removeItem = (index) => {
        if (items.length <= 1) return
        setItems(items.filter((_, i) => i !== index))
    }

    // Backend-powered calculations
    const { totals: backendTotals, previewContract, previewDebounced } = useInvoiceCalc()

    const getTotals = () => {
        // Use backend totals if available
        if (backendTotals) {
            return { subtotal: backendTotals.subtotal, tax: backendTotals.totalTax, total: backendTotals.grandTotal }
        }
        // Fallback to local calculation
        let subtotal = 0
        let tax = 0
        items.forEach(item => {
            const lineSub = item.quantity * item.unit_price
            subtotal += lineSub
            tax += lineSub * (item.tax_rate / 100)
        })
        return { subtotal, tax, total: subtotal + tax }
    }

    // Call backend for accurate calculations
    useEffect(() => {
        if (items.length > 0 && items.some(i => i.quantity > 0 && i.unit_price > 0)) {
            previewDebounced({
                lines: items.map(i => ({
                    quantity: Number(i.quantity) || 0,
                    unit_price: Number(i.unit_price) || 0,
                    tax_rate: Number(i.tax_rate) || 0,
                    discount: 0,
                })),
                currency,
            })
        }
    }, [items])

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!formData.party_id) return setError(t("sales.contracts.form.select_customer_error"))
        setLoading(true)
        try {
            const totals = getTotals()
            const payload = {
                ...formData,
                party_id: parseInt(formData.party_id),
                total_amount: totals.total,
                items: items.map(item => ({
                    ...item,
                    product_id: parseInt(item.product_id),
                    quantity: Number(item.quantity),
                    unit_price: Number(item.unit_price),
                    tax_rate: Number(item.tax_rate)
                }))
            }
            if (id) {
                await contractsAPI.updateContract(id, payload)
            } else {
                await contractsAPI.createContract(payload)
            }
            navigate('/sales/contracts')
        } catch (err) {
            setError(err.response?.data?.detail || t("sales.contracts.form.save_error"))
        } finally {
            setLoading(false)
        }
    }

    if (initialLoad && id) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{id ? t("sales.contracts.form.edit") : t("sales.contracts.form.create")}</h1>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}

            <form onSubmit={handleSubmit}>
                <div className="card mb-4">
                    <div className="form-row">
                        <FormField label={t("sales.contracts.form.contract_number")}>
                            <input type="text" className="form-input" value={formData.contract_number} readOnly />
                        </FormField>
                        <FormField label={t("sales.contracts.form.customer")} required style={{ flex: 2 }}>
                            <select
                                className="form-input"
                                value={formData.party_id}
                                onChange={e => setFormData({ ...formData, party_id: e.target.value })}
                                required
                            >
                                <option value="">{t("sales.contracts.form.select_customer")}</option>
                                {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                            </select>
                        </FormField>
                        <FormField label={t("sales.contracts.form.contract_type")}>
                            <select
                                className="form-input"
                                value={formData.contract_type}
                                onChange={e => setFormData({ ...formData, contract_type: e.target.value })}
                            >
                                <option value="subscription">{t("sales.contracts.type_subscription")}</option>
                                <option value="fixed">{t("sales.contracts.type_fixed")}</option>
                                <option value="recurring">{t("sales.contracts.type_recurring")}</option>
                            </select>
                        </FormField>
                    </div>
                    <div className="form-row mt-3">
                        <div className="form-group">
                            <CustomDatePicker
                                label={t("sales.contracts.form.start_date")}
                                selected={formData.start_date}
                                onChange={d => setFormData({ ...formData, start_date: d })}
                            />
                        </div>
                        <div className="form-group">
                            <CustomDatePicker
                                label={t("sales.contracts.form.end_date")}
                                selected={formData.end_date}
                                onChange={d => setFormData({ ...formData, end_date: d })}
                            />
                        </div>
                        <FormField label={t("sales.contracts.form.billing_interval")}>
                            <select
                                className="form-input"
                                value={formData.billing_interval}
                                onChange={e => setFormData({ ...formData, billing_interval: e.target.value })}
                            >
                                <option value="monthly">{t("sales.contracts.form.monthly")}</option>
                                <option value="quarterly">{t("sales.contracts.form.quarterly")}</option>
                                <option value="yearly">{t("sales.contracts.form.yearly")}</option>
                            </select>
                        </FormField>
                    </div>
                </div>

                <div className="card mb-4">
                    <h3 className="section-title">{t("sales.contracts.form.items")}</h3>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th style={{ width: '40%' }}>{t("sales.contracts.form.product_service")}</th>
                                <th>{t("sales.contracts.form.quantity")}</th>
                                <th>{t("sales.contracts.form.price")}</th>
                                <th>{t("sales.contracts.form.tax_percent")}</th>
                                <th>{t("sales.contracts.form.total")}</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((item, index) => {
                                const lineTotal = item.quantity * item.unit_price * (1 + item.tax_rate / 100)
                                return (
                                    <tr key={index}>
                                        <td>
                                            <select
                                                className="form-input"
                                                value={item.product_id}
                                                onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                            >
                                                <option value="">{t("sales.contracts.form.select_product")}</option>
                                                {products.map(p => <option key={p.id} value={p.id}>{p.item_name}</option>)}
                                            </select>
                                        </td>
                                        <td>
                                            <input type="number" className="form-input" value={item.quantity} onChange={e => handleItemChange(index, 'quantity', Number(e.target.value) || 0)} />
                                        </td>
                                        <td>
                                            <input type="number" className="form-input" value={item.unit_price} onChange={e => handleItemChange(index, 'unit_price', Number(e.target.value) || 0)} />
                                        </td>
                                        <td>
                                            <input type="number" className="form-input" value={item.tax_rate} onChange={e => handleItemChange(index, 'tax_rate', Number(e.target.value) || 0)} />
                                        </td>
                                        <td style={{ fontWeight: 'bold' }}>{formatNumber(lineTotal)}</td>
                                        <td>
                                            <button type="button" className="btn-icon text-danger" onClick={() => removeItem(index)}>🗑️</button>
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                    <button type="button" className="btn btn-secondary mt-3" onClick={addItem}>{t("sales.contracts.form.add_item")}</button>
                </div>

                <div className="card mb-4">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ flex: 1 }}>
                            <FormField label={t("sales.contracts.form.notes")}>
                                <textarea className="form-input" rows="3" value={formData.notes} onChange={e => setFormData({ ...formData, notes: e.target.value })}></textarea>
                            </FormField>
                        </div>
                        <div style={{ width: '300px', marginLeft: '32px', textAlign: 'left' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{t("sales.contracts.form.subtotal")}:</span>
                                <span>{formatNumber(getTotals().subtotal)} {formData.currency}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{t("sales.contracts.form.tax")}:</span>
                                <span>{formatNumber(getTotals().tax)} {formData.currency}</span>
                            </div>
                            <div style={{ borderTop: '1px solid #ddd', margin: '8px 0' }}></div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.2rem' }}>
                                <span>{t("sales.contracts.form.grand_total")}:</span>
                                <span>{formatNumber(getTotals().total)} {formData.currency}</span>
                            </div>
                            <button type="submit" className="btn btn-primary mt-4 w-full" disabled={loading}>
                                {loading ? t("common.saving") : t("sales.contracts.form.save")}
                            </button>
                        </div>
                    </div>
                </div>
            </form>
        </div>
    )
}

export default ContractForm
