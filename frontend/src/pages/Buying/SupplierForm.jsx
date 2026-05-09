import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { inventoryAPI, currenciesAPI, purchasesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import { useToast } from '../../context/ToastContext'

function SupplierForm() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const navigate = useNavigate()
    const { id } = useParams()
    const isEdit = Boolean(id)
    const { currentBranch } = useBranch()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [currencies, setCurrencies] = useState([])
    const [supplierGroups, setSupplierGroups] = useState([])
    const [error, setError] = useState(null)
    const [formData, setFormData] = useState({
        name: '',
        name_en: '',
        email: '',
        phone: '',
        tax_number: '',
        address: '',
        currency: getCurrency(),
        group_id: ''
    })

    useEffect(() => {
        const fetchSupplierData = async () => {
            if (!isEdit) return
            try {
                setLoading(true)
                const response = await inventoryAPI.getSupplier(id)
                const s = response.data
                setFormData({
                    name: s.name || '',
                    name_en: s.name_en || '',
                    email: s.email || '',
                    phone: s.phone || '',
                    tax_number: s.tax_number || '',
                    address: s.address || '',
                    currency: s.currency || getCurrency(),
                    group_id: s.group_id || ''
                })
            } catch (err) {
                setError(t('common.error_loading'))
            } finally {
                setLoading(false)
                setInitialLoad(false)
            }
        }

        const fetchCurrenciesAndGroups = async () => {
            try {
                const [curRes, groupRes] = await Promise.all([
                    currenciesAPI.list(),
                    purchasesAPI.listSupplierGroups({ branch_id: currentBranch?.id })
                ]);
                if (curRes.data) setCurrencies(curRes.data.filter(c => c.is_active));
                if (groupRes.data) setSupplierGroups(groupRes.data.filter(g => g.status === 'active'));
            } catch (err) {
                showToast(t('common.error'), 'error');
            }
        }
        const timer = setTimeout(() => {
            fetchSupplierData()
            fetchCurrenciesAndGroups()
        }, 300)
        return () => clearTimeout(timer)
    }, [id, isEdit, currentBranch?.id, t])

    const handleSubmit = async (e) => {
        e.preventDefault()
        setLoading(true)
        setError(null)

        try {
            const payload = {
                ...formData,
                branch_id: currentBranch?.id,
                group_id: formData.group_id ? parseInt(formData.group_id) : null
            };

            if (isEdit) {
                await inventoryAPI.updateSupplier(id, payload)
            } else {
                await inventoryAPI.createSupplier(payload)
            }
            navigate(isEdit ? `/buying/suppliers/${id}` : '/buying/suppliers')
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_saving'))
        } finally {
            setLoading(false)
        }
    }

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value })
    }

    const handleDelete = async () => {
        if (!window.confirm(t('buying.suppliers.delete_confirm'))) return
        try {
            await inventoryAPI.deleteSupplier(id)
            navigate('/buying/suppliers')
        } catch (err) {
            const errorMsg = err.response?.data?.detail || t('common.error_deleting')
            showToast(errorMsg, 'error')
        }
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{isEdit ? t('buying.suppliers.form.title_edit') : t('buying.suppliers.form.title_new')}</h1>
                    <p className="workspace-subtitle">{isEdit ? t('buying.suppliers.form.subtitle_edit', 'Update supplier information') : t('buying.suppliers.form.subtitle_new', 'Add a new supplier to your system')}</p>
                </div>
            </div>

            <div className="card" style={{ maxWidth: '900px', margin: '0 auto', padding: '32px', boxShadow: 'var(--shadow-lg)' }}>
                {error && <div className="alert alert-error mb-4">{error}</div>}

                <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div className="form-section-container" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                        <div className="form-section card">
                            <h3 className="section-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--primary)' }}>
                                <span style={{ fontSize: '24px' }}>🏢</span> {t('buying.suppliers.form.basic_info')}
                            </h3>
                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                                <FormField label={t('buying.suppliers.form.name_ar')} required style={{ marginBottom: 0 }}>
                                    <input
                                        type="text" name="name" className="form-input" required
                                        value={formData.name} onChange={handleChange}
                                        placeholder={t('buying.suppliers.form.name_ar')}
                                    />
                                </FormField>
                                <FormField label={t('buying.suppliers.form.name_en')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="text" name="name_en" className="form-input"
                                        value={formData.name_en} onChange={handleChange}
                                        placeholder={t('buying.suppliers.name_placeholder')}
                                    />
                                </FormField>
                            </div>

                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
                                <FormField label={t('buying.suppliers.form.tax_number')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="text" name="tax_number" className="form-input"
                                        value={formData.tax_number} onChange={handleChange}
                                    />
                                </FormField>
                                <FormField label={t('common.currency')} style={{ marginBottom: 0 }}>
                                    <select
                                        name="currency"
                                        className="form-input"
                                        value={formData.currency}
                                        onChange={handleChange}
                                    >
                                        {currencies.map(c => (
                                            <option key={c.id} value={c.code}>
                                                {c.name} ({c.code})
                                            </option>
                                        ))}
                                    </select>
                                </FormField>
                            </div>

                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
                                <FormField label={t('buying.supplier_groups.title')} style={{ marginBottom: 0 }}>
                                    <div className="input-group">
                                        <select
                                            name="group_id"
                                            className="form-input"
                                            value={formData.group_id || ''}
                                            onChange={handleChange}
                                        >
                                            <option value="">{t('common.select')}</option>
                                            {supplierGroups.map(g => (
                                                <option key={g.id} value={g.id}>
                                                    {g.group_name}
                                                </option>
                                            ))}
                                        </select>
                                        <button
                                            type="button"
                                            className="btn btn-secondary"
                                            onClick={() => window.open('/buying/supplier-groups', '_blank')}
                                            title={t('buying.suppliers.form.quick_add_group')}
                                            style={{ padding: '0 12px' }}
                                        >
                                            +
                                        </button>
                                    </div>
                                </FormField>
                                <FormField style={{ marginBottom: 0 }}>
                                    {/* Spacer */}
                                </FormField>
                            </div>
                        </div>

                        <div className="form-section card">
                            <h3 className="section-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--primary)' }}>
                                <span style={{ fontSize: '24px' }}>📞</span> {t('buying.suppliers.form.contact_info')}
                            </h3>
                            <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                                <FormField label={t('buying.suppliers.form.phone')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="tel" name="phone" className="form-input"
                                        value={formData.phone} onChange={handleChange}
                                    />
                                </FormField>
                                <FormField label={t('buying.suppliers.form.email')} style={{ marginBottom: 0 }}>
                                    <input
                                        type="email" name="email" className="form-input"
                                        value={formData.email} onChange={handleChange}
                                    />
                                </FormField>
                            </div>
                            <FormField label={t('buying.suppliers.form.address')} style={{ marginTop: '24px', marginBottom: 0 }}>
                                <textarea
                                    name="address" className="form-input" rows="3"
                                    value={formData.address} onChange={handleChange}
                                ></textarea>
                            </FormField>
                        </div>
                    </div>

                    <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? t('buying.suppliers.form.saving') : t('buying.suppliers.form.submit')}
                        </button>
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/buying/suppliers')}>
                            {t('buying.suppliers.form.cancel')}
                        </button>
                        {isEdit && (
                            <button type="button" className="btn btn-danger" onClick={handleDelete} style={{ marginRight: 'auto' }}>
                                {t('common.delete')}
                            </button>
                        )}
                    </div>
                </form>
            </div>
        </div>
    )
}

export default SupplierForm
