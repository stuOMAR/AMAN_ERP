import { useNavigate, useParams } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { inventoryAPI, settingsAPI } from '../../utils/api'
import { getCurrency, hasPermission } from '../../utils/auth'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { getStep } from '../../utils/format'
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import ProductTaxSelector from '../../components/Tax/ProductTaxSelector';

const formatApiError = (detail, fallback) => {
    if (!detail) return fallback
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
        return detail
            .map((entry) => {
                if (typeof entry === 'string') return entry
                if (entry?.msg) {
                    const field = Array.isArray(entry.loc) ? entry.loc.at(-1) : null
                    return field ? `${field}: ${entry.msg}` : entry.msg
                }
                return null
            })
            .filter(Boolean)
            .join('، ') || fallback
    }
    return fallback
}

const normalizeOptionalDecimalString = (value, defaultValue = '0') => {
    if (value === '' || value === null || value === undefined) return defaultValue
    return String(value)
}

const normalizeOptionalInteger = (value, defaultValue = 0) => {
    if (value === '' || value === null || value === undefined) return defaultValue
    const parsed = parseInt(value, 10)
    return Number.isFinite(parsed) ? parsed : defaultValue
}

function ProductForm() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { id } = useParams()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [formData, setFormData] = useState({
        item_code: '',
        item_name: '',
        item_name_en: '',
        item_type: 'product',
        unit: t('stock.products.unit_piece'),
        selling_price: '',
        buying_price: '',
        description: '',
        category_id: '',
        has_batch_tracking: false,
        has_serial_tracking: false,
        has_expiry_tracking: false,
        shelf_life_days: '',
        expiry_alert_days: 30
    })
    const [taxMode, setTaxMode] = useState({
        mode: 'inherit',
        tax_rate_id: null,
        tax_rate: null,
        tax_name: null,
        tax_group_id: null,
        tax_classification_id: null,
        is_exempt: false,
    })
    const [categories, setCategories] = useState([])

    const buildPayload = () => {
        const isTrackedProduct = formData.item_type === 'product'
        const hasExpiryTracking = isTrackedProduct && !!formData.has_expiry_tracking

        return {
            item_code: formData.item_code.trim(),
            item_name: formData.item_name.trim(),
            item_name_en: formData.item_name_en?.trim() || null,
            item_type: formData.item_type,
            unit: formData.unit || t('stock.products.unit_piece'),
            selling_price: normalizeOptionalDecimalString(formData.selling_price, '0'),
            buying_price: normalizeOptionalDecimalString(formData.buying_price, '0'),
            last_buying_price: normalizeOptionalDecimalString(formData.last_buying_price ?? formData.buying_price, '0'),
            tax_rate: null, // Resolved by tax engine
            tax_rate_id: taxMode.tax_rate_id,
            tax_group_id: taxMode.tax_group_id,
            tax_classification_id: taxMode.tax_classification_id,
            is_exempt: taxMode.is_exempt,
            description: formData.description?.trim() || null,
            category_id: formData.category_id === '' ? null : normalizeOptionalInteger(formData.category_id, 0),
            is_active: formData.is_active ?? true,
            has_batch_tracking: isTrackedProduct && !!formData.has_batch_tracking,
            has_serial_tracking: isTrackedProduct && !!formData.has_serial_tracking,
            has_expiry_tracking: hasExpiryTracking,
            shelf_life_days: hasExpiryTracking ? normalizeOptionalInteger(formData.shelf_life_days, 0) : 0,
            expiry_alert_days: hasExpiryTracking ? normalizeOptionalInteger(formData.expiry_alert_days, 30) : 30,
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchInitialData = async () => {
                try {
                    // Fetch Categories
                    const catRes = await inventoryAPI.listCategories({ branch_id: currentBranch?.id })
                    setCategories(catRes.data)

                    // If new product, fetch default tax rate from settings
                    if (!id) {
                        // Default to inherit mode — no need to set anything
                    }
                } catch (err) {
                    showToast(t('stock.products.validation.error_load_data'), 'error')
                }
            }
            fetchInitialData()

            if (id) {
                const fetchProduct = async () => {
                    try {
                        setLoading(true)
                        const res = await inventoryAPI.getProduct(id)
                        const data = res.data
                        setFormData({
                            ...data,
                            category_id: data.category_id || '',
                            product_name: data.product_name || '',
                            product_name_en: data.product_name_en || '',
                            product_code: data.product_code || '',
                            description: data.description || '',
                            barcode: data.barcode || '',
                            brand: data.brand || '',
                            manufacturer: data.manufacturer || '',
                            sku: data.sku || '',
                            cost_price: data.cost_price ?? 0,
                            selling_price: data.selling_price ?? 0,
                            wholesale_price: data.wholesale_price ?? 0,
                            min_price: data.min_price ?? 0,
                            max_price: data.max_price ?? 0,
                            reorder_level: data.reorder_level ?? 0,
                            reorder_quantity: data.reorder_quantity ?? 0,
                        })
                        // Set tax mode based on product data
                        if (data.is_exempt) {
                            setTaxMode({ mode: 'exempt', tax_rate_id: null, tax_rate: 0, tax_name: null, tax_group_id: null, tax_classification_id: null, is_exempt: true })
                        } else if (data.tax_group_id) {
                            setTaxMode({
                                mode: 'group',
                                tax_rate_id: null,
                                tax_rate: null,
                                tax_name: data.tax_group_name || null,
                                tax_group_id: data.tax_group_id,
                                tax_classification_id: null,
                                is_exempt: false,
                            })
                        } else if (data.tax_classification_id) {
                            setTaxMode({
                                mode: 'classification',
                                tax_rate_id: null,
                                tax_rate: null,
                                tax_name: data.tax_classification_name || null,
                                tax_group_id: null,
                                tax_classification_id: data.tax_classification_id,
                                is_exempt: false,
                            })
                        } else if (data.tax_rate_id) {
                            setTaxMode({
                                mode: 'custom',
                                tax_rate_id: data.tax_rate_id,
                                tax_rate: data.tax_rate,
                                tax_name: data.tax_name || null,
                                tax_group_id: null,
                                tax_classification_id: null,
                                is_exempt: false,
                            })
                        } else {
                            setTaxMode({ mode: 'inherit', tax_rate_id: null, tax_rate: null, tax_name: null, tax_group_id: null, tax_classification_id: null, is_exempt: false })
                        }
                    } catch (err) {
                        setError(t('stock.products.validation.error_load_data'))
                        showToast(t('stock.products.validation.error_load_data'), 'error')
                    } finally {
                        setLoading(false)
                        setInitialLoad(false)
                    }
                }
                fetchProduct()
            } else {
                setInitialLoad(false)
            }
        }, 300)
        return () => clearTimeout(timer)
    }, [id, currentBranch, t])

    const handleSubmit = async (e) => {
        e.preventDefault()
        setLoading(true)
        setError(null)

        try {
            const payload = buildPayload()
            if (id) {
                await inventoryAPI.updateProduct(id, payload)
            } else {
                await inventoryAPI.createProduct(payload)
            }
            navigate('/stock/products')
        } catch (err) {
            setError(formatApiError(err.response?.data?.detail, t('stock.products.validation.error_save')))
        } finally {
            setLoading(false)
        }
    }

    const handleChange = (e) => {
        let value = e.target.value

        if (e.target.name === 'category_id' && value !== '') {
            value = parseInt(value)
        } else if ((e.target.name === 'shelf_life_days' || e.target.name === 'expiry_alert_days') && value !== '') {
            value = parseInt(value, 10)
        }

        setFormData({ ...formData, [e.target.name]: value })
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{id ? t('stock.products.form.edit_title') : t('stock.products.form.title')}</h1>
                <p className="workspace-subtitle">{t('stock.products.form.subtitle')}</p>
            </div>

            <div className="card" style={{ maxWidth: '800px' }}>
                {error && <div className="alert alert-error mb-4">{error}</div>}

                <form onSubmit={handleSubmit}>
                    <div className="form-section">
                        <h3 className="section-title">{t('stock.products.form.basic_info')}</h3>
                        <div className="form-row">
                            <FormField label={t('stock.products.form.code')} required>
                                <input
                                    type="text" name="item_code" className="form-input" required
                                    value={formData.item_code} onChange={handleChange}
                                    placeholder={t('stock.products.form.placeholder_code')}
                                />
                            </FormField>
                            <FormField label={t('stock.products.form.type')}>
                                <select name="item_type" className="form-input" value={formData.item_type} onChange={handleChange}>
                                    <option value="product">{t('stock.products.form.types.product')}</option>
                                    <option value="service">{t('stock.products.form.types.service')}</option>
                                    <option value="consumable">{t('stock.products.form.types.consumable')}</option>
                                </select>
                            </FormField>
                        </div>

                        <div className="form-row">
                            <FormField label={t('stock.products.form.name_ar')} required>
                                <input
                                    type="text" name="item_name" className="form-input" required
                                    value={formData.item_name} onChange={handleChange}
                                />
                            </FormField>
                            <FormField label={t('stock.products.form.name_en')}>
                                <input
                                    type="text" name="item_name_en" className="form-input"
                                    value={formData.item_name_en} onChange={handleChange}
                                />
                            </FormField>
                        </div>

                        <div className="form-row">
                            <FormField label={t('stock.products.form.unit')}>
                                <select name="unit" className="form-input" value={formData.unit} onChange={handleChange}>
                                    <option value="قطعة">{t('stock.products.form.units.piece')}</option>
                                    <option value="كيلو">{t('stock.products.form.units.kg')}</option>
                                    <option value="متر">{t('stock.products.form.units.meter')}</option>
                                    <option value="لتر">{t('stock.products.form.units.liter')}</option>
                                    <option value="علبة">{t('stock.products.form.units.box')}</option>
                                    <option value="كرتون">{t('stock.products.form.units.carton')}</option>
                                </select>
                            </FormField>
                            <FormField label={t('stock.products.form.category')} required>
                                <select
                                    name="category_id"
                                    className="form-input"
                                    value={formData.category_id}
                                    onChange={handleChange}
                                    required
                                >
                                    <option value="">-- {t('stock.products.form.select_category')} --</option>
                                    {categories.map(cat => (
                                        <option key={cat.id} value={cat.id}>{cat.name}</option>
                                    ))}
                                </select>
                            </FormField>
                        </div>
                    </div>

                    <div className="form-section">
                        <h3 className="section-title">{t('stock.products.form.pricing')}</h3>
                        <div className="form-row">
                            {hasPermission('stock.view_cost') && (
                                <FormField label={`${t('stock.products.form.buying_price')} (${currency})`} required>
                                    <input
                                        type="number" name="buying_price" className="form-input" min="0" step={getStep()}
                                        value={formData.buying_price} onChange={handleChange} required
                                    />
                                </FormField>
                            )}
                            <FormField label={`${t('stock.products.form.selling_price')} (${currency})`} required>
                                <input
                                    type="number" name="selling_price" className="form-input" min="0" step={getStep()}
                                    value={formData.selling_price} onChange={handleChange} required
                                />
                            </FormField>
                            <FormField label={t('stock.products.form.tax_rate')}>
                                <ProductTaxSelector
                                    branchId={currentBranch?.id}
                                    value={taxMode}
                                    onChange={setTaxMode}
                                />
                            </FormField>
                        </div>
                    </div>

                    {/* Tracking Section - only for products */}
                    {formData.item_type === 'product' && (
                        <div className="form-section">
                            <h3 className="section-title">{t('stock.products.form.tracking')}</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: formData.has_batch_tracking ? 'var(--primary-light, #e8f0fe)' : 'var(--bg-secondary)', borderRadius: '8px', border: formData.has_batch_tracking ? '2px solid var(--primary)' : '2px solid transparent' }}>
                                        <input type="checkbox" name="has_batch_tracking"
                                            checked={formData.has_batch_tracking}
                                            onChange={(e) => setFormData({ ...formData, has_batch_tracking: e.target.checked })} />
                                        <div>
                                            <strong>📦 {t('stock.products.form.batch_tracking')}</strong>
                                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                                {t('stock.products.form.batch_tracking_desc')}
                                            </div>
                                        </div>
                                    </label>
                                </div>
                                <div className="form-group">
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: formData.has_serial_tracking ? 'var(--primary-light, #e8f0fe)' : 'var(--bg-secondary)', borderRadius: '8px', border: formData.has_serial_tracking ? '2px solid var(--primary)' : '2px solid transparent' }}>
                                        <input type="checkbox" name="has_serial_tracking"
                                            checked={formData.has_serial_tracking}
                                            onChange={(e) => setFormData({ ...formData, has_serial_tracking: e.target.checked })} />
                                        <div>
                                            <strong>🏷️ {t('stock.products.form.serial_tracking')}</strong>
                                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                                {t('stock.products.form.serial_tracking_desc')}
                                            </div>
                                        </div>
                                    </label>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: formData.has_expiry_tracking ? 'var(--primary-light, #e8f0fe)' : 'var(--bg-secondary)', borderRadius: '8px', border: formData.has_expiry_tracking ? '2px solid var(--primary)' : '2px solid transparent' }}>
                                        <input type="checkbox" name="has_expiry_tracking"
                                            checked={formData.has_expiry_tracking}
                                            onChange={(e) => setFormData({ ...formData, has_expiry_tracking: e.target.checked })} />
                                        <div>
                                            <strong>📅 {t('stock.products.form.expiry_tracking')}</strong>
                                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                                {t('stock.products.form.expiry_tracking_desc')}
                                            </div>
                                        </div>
                                    </label>
                                </div>
                                {formData.has_expiry_tracking && (
                                    <div className="form-group" style={{ display: 'flex', gap: '12px' }}>
                                        <div style={{ flex: 1 }}>
                                            <label className="form-label">{t('stock.products.form.shelf_life')}</label>
                                            <input type="number" name="shelf_life_days" className="form-input" min="0"
                                                value={formData.shelf_life_days} onChange={handleChange} placeholder="365" />
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <label className="form-label">{t('stock.products.form.expiry_alert')}</label>
                                            <input type="number" name="expiry_alert_days" className="form-input" min="0"
                                                value={formData.expiry_alert_days} onChange={handleChange} placeholder="30" />
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    <FormField label={t('stock.products.form.description')}>
                        <textarea
                            name="description" className="form-input" rows="3"
                            value={formData.description} onChange={handleChange}
                        ></textarea>
                    </FormField>

                    <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? t('stock.products.form.saving') : (id ? t('stock.products.form.save_changes') : t('stock.products.form.save'))}
                        </button>
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/stock/products')}>
                            {t('stock.products.form.cancel')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}

export default ProductForm
