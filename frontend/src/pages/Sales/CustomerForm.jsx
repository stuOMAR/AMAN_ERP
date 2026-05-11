import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { getUser } from '../../utils/auth'
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import CurrencySelector from '../../components/common/CurrencySelector';
import FormField from '../../components/common/FormField';
import { PageLoading } from '../../components/common/LoadingStates'

function CustomerForm() {
    const { t } = useTranslation()
    const { id } = useParams()
    const isEdit = Boolean(id)
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [initialLoading, setInitialLoading] = useState(isEdit)
    const [error, setError] = useState(null)
    const [groups, setGroups] = useState([])
    const [formData, setFormData] = useState({
        name: '',
        name_en: '',
        email: '',
        phone: '',
        tax_number: '',
        address: '',
        credit_limit: 0,
        group_id: '',
        currency: '',
        status: 'active'
    })

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchInitialData = async () => {
                try {
                    if (isEdit) setInitialLoading(true)
                    const [groupsRes] = await Promise.all([
                        salesAPI.listCustomerGroups()
                    ])
                    setGroups(groupsRes.data)

                    if (isEdit) {
                        const customerRes = await salesAPI.getCustomer(id)
                        const c = customerRes.data;
                        setFormData({
                            name: c.name || '',
                            name_en: c.name_en || '',
                            email: c.email || '',
                            phone: c.phone || '',
                            tax_number: c.tax_number || '',
                            address: c.address || '',
                            credit_limit: c.credit_limit ? formatNumber(c.credit_limit) : formatNumber(0),
                            group_id: c.group_id || '',
                            currency: c.currency || '',
                            status: c.status || 'active'
                        })
                    }
                } catch (err) {
                    setError(t('common.error_loading'))
                } finally {
                    setInitialLoading(false)
                    setInitialLoad(false)
                }
            }
            fetchInitialData()
        }, 300)
        return () => clearTimeout(timer)
    }, [id, isEdit, t])

    const handleSubmit = async (e) => {
        e.preventDefault()
        setLoading(true)
        setError(null)

        try {
            // Sanitize payload
            const payload = {
                ...formData,
                name_en: formData.name_en || null,
                email: formData.email || null,
                phone: formData.phone || null,
                tax_number: formData.tax_number || null,
                address: formData.address || null,
                group_id: formData.group_id ? parseInt(formData.group_id) : null,
                branch_id: currentBranch?.id,
                status: formData.status
            }
            if (isEdit) {
                await salesAPI.updateCustomer(id, payload)
                navigate(`/sales/customers/${id}`)
            } else {
                await salesAPI.createCustomer(payload)
                navigate('/sales/customers')
            }
        } catch (err) {
            const errMsg = err.response?.data?.detail
            setError(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg) || t('sales.customers.form.error_add'))
        } finally {
            setLoading(false)
        }
    }

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value })
    }

    if (initialLoading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{isEdit ? t('sales.customers.form.edit_title') : t('sales.customers.form.create_title')}</h1>
                    <p className="workspace-subtitle">{isEdit ? t('sales.customers.form.edit_subtitle') : t('sales.customers.form.create_subtitle')}</p>
                </div>
            </div>

            <div className="card" style={{ maxWidth: '900px', margin: '0 auto', padding: '32px', boxShadow: 'var(--shadow-lg)' }}>
                {error && <div className="alert alert-error mb-4">{error}</div>}

                <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div className="form-section-container" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                        <div className="form-section card">
                            <h3 className="section-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--primary)' }}>
                                <span style={{ fontSize: '24px' }}>🏢</span> {t('sales.customers.form.basic_info')}
                            </h3>
                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                                <FormField label={t('sales.customers.form.name_ar')} required style={{ marginBottom: 0 }}>
                                    <input
                                        type="text" name="name" className="form-input" required
                                        value={formData.name} onChange={handleChange}
                                        placeholder={t('sales.customers.form.name_ar')}
                                    />
                                </FormField>
                                <FormField label={t('sales.customers.form.name_en')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="text" name="name_en" className="form-input"
                                        value={formData.name_en} onChange={handleChange}
                                        placeholder={t('sales.customers.name_placeholder')}
                                    />
                                </FormField>
                            </div>

                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
                                <FormField label={t('sales.customers.form.tax_number')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="text" name="tax_number" className="form-input"
                                        value={formData.tax_number} onChange={handleChange}
                                    />
                                </FormField>
                                <div className="form-group" style={{ marginBottom: 0 }}>
                                    <label className="form-label">{t('sales.customers.form.group')}</label>
                                    <div className="input-group">
                                        <select
                                            name="group_id"
                                            className="form-input"
                                            value={formData.group_id}
                                            onChange={handleChange}
                                        >
                                            <option value="">{t('sales.customers.form.select_group')}</option>
                                            {groups.map(group => (
                                                <option key={group.id} value={group.id}>
                                                    {group.group_name}
                                                </option>
                                            ))}
                                        </select>
                                        <button
                                            type="button"
                                            className="btn btn-secondary"
                                            onClick={() => window.open('/sales/customer-groups', '_blank')}
                                            title={t('sales.customers.form.quick_add_group')}
                                            style={{ padding: '0 12px' }}
                                        >
                                            +
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
                                <FormField label={t('sales.customers.form.credit_limit')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="number"
                                        name="credit_limit"
                                        className="form-input"
                                        step={1 / Math.pow(10, getUser()?.decimal_places ?? 2)}
                                        value={formData.credit_limit}
                                        onChange={handleChange}
                                    />
                                </FormField>
                                <FormField label={t('common.currency')} style={{ marginBottom: 0 }}>
                                    <CurrencySelector
                                        value={formData.currency}
                                        onChange={(code) => setFormData({ ...formData, currency: code })}
                                        className="form-input"
                                    />
                                </FormField>
                            </div>

                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
                                <FormField label={t('sales.customers.table.status')} style={{ marginBottom: 0 }}>
                                    <select
                                        name="status"
                                        className="form-input"
                                        value={formData.status}
                                        onChange={handleChange}
                                    >
                                        <option value="active">{t('sales.customers.status.active')}</option>
                                        <option value="inactive">{t('sales.customers.status.inactive')}</option>
                                    </select>
                                </FormField>
                                <div className="form-group" style={{ marginBottom: 0 }}>
                                    {/* Spacer */}
                                </div>
                            </div>
                        </div>

                        <div className="form-section card">
                            <h3 className="section-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--primary)' }}>
                                <span style={{ fontSize: '24px' }}>📞</span> {t('sales.customers.form.contact_info')}
                            </h3>
                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                                <FormField label={t('sales.customers.form.phone')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="tel" name="phone" className="form-input"
                                        value={formData.phone} onChange={handleChange}
                                    />
                                </FormField>
                                <FormField label={t('sales.customers.form.email')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="email" name="email" className="form-input"
                                        value={formData.email} onChange={handleChange}
                                    />
                                </FormField>
                            </div>
                            <FormField label={t('sales.customers.form.address')} style={{ marginTop: '24px', marginBottom: 0 }}>
                                <textarea
                                    name="address" className="form-input" rows="3"
                                    value={formData.address} onChange={handleChange}
                                ></textarea>
                            </FormField>
                        </div>
                    </div>

                    <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? t('sales.customers.form.saving') : t('sales.customers.form.save_btn')}
                        </button>
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/sales/customers')}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}

export default CustomerForm
