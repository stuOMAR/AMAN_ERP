import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { landedCostsAPI, purchasesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton'
import { PageLoading } from '../../components/common/LoadingStates'

function LandedCosts() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [costs, setCosts] = useState([])
    const [suppliers, setSuppliers] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState({ purchase_order_id: '', reference: '', notes: '', currency: currency || '', exchange_rate: 1, allocation_method: 'by_value', cost_items: [] })
    const [newItem, setNewItem] = useState({ cost_type: 'freight', description: '', amount: '', vendor_id: '', invoice_ref: '' })

    useEffect(() => {
        Promise.all([
            landedCostsAPI.list(),
            purchasesAPI.listSuppliers({ limit: 1000 }).catch(() => ({ data: [] })),
        ])
            .then(([costRes, supplierRes]) => {
                setCosts(costRes.data)
                setSuppliers(supplierRes.data || [])
            })
            .catch(() => showToast(t('common.error'), 'error'))
            .finally(() => setLoading(false))
    }, [])

    const addItem = () => {
        if (!newItem.amount) return
        setForm(f => ({
            ...f,
            cost_items: [
                ...f.cost_items,
                {
                    ...newItem,
                    amount: Number(newItem.amount),
                    vendor_id: newItem.vendor_id ? Number(newItem.vendor_id) : null,
                    invoice_ref: newItem.invoice_ref || null,
                },
            ],
        }))
        setNewItem({ cost_type: 'freight', description: '', amount: '', vendor_id: '', invoice_ref: '' })
    }

    const handleCreate = async () => {
        try {
            const payload = {
                ...form,
                purchase_order_id: form.purchase_order_id ? Number(form.purchase_order_id) : null,
                exchange_rate: form.exchange_rate != null && form.exchange_rate !== '' ? Number(form.exchange_rate) : 1,
            }
            const res = await landedCostsAPI.create(payload)
            showToast(t('landed_costs.created'), 'success')
            navigate(`/buying/landed-costs/${res.data.id}`)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    if (loading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📦 {t('landed_costs.title')}</h1>
                    <p className="workspace-subtitle">{t('landed_costs.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
                        + {t('landed_costs.create_new')}
                    </button>
                </div>
            </div>

            {showForm && (
                <div className="card p-4 mb-4">
                    <h3 className="card-title mb-3">{t('landed_costs.create_new')}</h3>
                    <div className="form-grid-3">
                        <div className="form-group">
                            <label>{t('landed_costs.purchase_order')}</label>
                            <input type="number" className="form-input" value={form.purchase_order_id} onChange={e => setForm(f => ({ ...f, purchase_order_id: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label>{t('landed_costs.reference_id')}</label>
                            <input type="text" className="form-input" value={form.reference} onChange={e => setForm(f => ({ ...f, reference: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label>{t('common.description')}</label>
                            <input type="text" className="form-input" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label>{t('common.currency')}</label>
                            <select className="form-select" value={form.currency} onChange={e => setForm(f => ({ ...f, currency: e.target.value }))}>
                                <option value="">{currency || t('common.base_currency')}</option>
                            </select>
                        </div>
                        <div className="form-group">
                            <label>{t('common.exchange_rate')}</label>
                            <input type="number" className="form-input" step="0.000001" min="0.000001" value={form.exchange_rate} onChange={e => setForm(f => ({ ...f, exchange_rate: e.target.value }))} />
                        </div>
                    </div>

                    <h4 className="mt-3 mb-2">{t('landed_costs.cost_items')}</h4>
	                    <div className="form-grid-4">
	                        <select className="form-select" value={newItem.cost_type} onChange={e => setNewItem(n => ({ ...n, cost_type: e.target.value }))}>
	                            <option value="freight">{t('landed_costs.freight')}</option>
	                            <option value="customs">{t('landed_costs.customs')}</option>
	                            <option value="insurance">{t('landed_costs.insurance')}</option>
	                            <option value="other">{t('common.other')}</option>
	                        </select>
	                        <input type="text" className="form-input" placeholder={t('common.description')} value={newItem.description} onChange={e => setNewItem(n => ({ ...n, description: e.target.value }))} />
	                        <input type="number" className="form-input" step="0.01" placeholder={t('common.amount')} value={newItem.amount} onChange={e => setNewItem(n => ({ ...n, amount: e.target.value }))} />
	                        <button type="button" className="btn btn-secondary" onClick={addItem}>+</button>
	                    </div>
	                    <div className="form-grid-2 mt-2">
	                        <select className="form-select" value={newItem.vendor_id} onChange={e => setNewItem(n => ({ ...n, vendor_id: e.target.value }))}>
	                            <option value="">{t('landed_costs.vendor_optional', 'Vendor optional')}</option>
	                            {suppliers.map(s => <option key={s.id} value={s.id}>{s.name || s.supplier_name}</option>)}
	                        </select>
	                        <input type="text" className="form-input" placeholder={t('landed_costs.invoice_ref', 'Invoice reference')} value={newItem.invoice_ref} onChange={e => setNewItem(n => ({ ...n, invoice_ref: e.target.value }))} />
	                    </div>

                    {form.cost_items.length > 0 && (
                        <table className="data-table mt-2">
                            <thead><tr><th>{t('common.type')}</th><th>{t('common.description')}</th><th>{t('common.amount')}</th><th></th></tr></thead>
                            <tbody>
                                {form.cost_items.map((item, i) => (
                                    <tr key={i}>
                                        <td>{t(`landed_costs.${item.cost_type}`, item.cost_type)}</td>
                                        <td>{item.description}</td>
                                        <td>{Number(item.amount).toLocaleString()} {currency}</td>
                                        <td><button className="btn-icon text-danger" onClick={() => setForm(f => ({ ...f, cost_items: f.cost_items.filter((_, j) => j !== i) }))}>🗑️</button></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}

                    <div className="mt-3 flex gap-2">
                        <button className="btn btn-primary" onClick={handleCreate} disabled={form.cost_items.length === 0 || !form.purchase_order_id}>
                            {t('common.save')}
                        </button>
                        <button className="btn btn-secondary" onClick={() => setShowForm(false)}>{t('common.cancel')}</button>
                    </div>
                </div>
            )}

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('landed_costs.lc_number')}</th>
                            <th>{t('common.date')}</th>
                            <th>{t('landed_costs.total_cost')}</th>
                            <th>{t('common.status_title')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {costs.length === 0 ? (
                            <tr><td colSpan="5" className="text-center py-5 text-muted">{t('landed_costs.empty')}</td></tr>
                        ) : costs.map(c => (
                            <tr key={c.id}>
                                <td className="font-medium text-primary">{c.lc_number}</td>
                                <td>{formatShortDate(c.created_at)}</td>
                                <td className="font-bold">{Number(c.total_amount || 0).toLocaleString()} <small>{currency}</small></td>
                                <td><span className={`status-badge ${c.status}`}>{c.status}</span></td>
                                <td><button onClick={() => navigate(`/buying/landed-costs/${c.id}`)} className="btn-icon">👁️</button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default LandedCosts
