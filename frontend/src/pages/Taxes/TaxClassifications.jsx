import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { taxesAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { PageLoading } from '../../components/common/LoadingStates'
import SimpleModal from '../../components/common/SimpleModal'
import { ChevronLeft, Plus, Edit2, Trash2, Globe, Search, X, Tag } from 'lucide-react'
import DataTable from '../../components/common/DataTable'

export default function TaxClassifications() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()

    const [loading, setLoading] = useState(true)
    const [classifications, setClassifications] = useState([])
    const [searchQuery, setSearchQuery] = useState('')
    const [showInactive, setShowInactive] = useState(false)
    const [countryFilter, setCountryFilter] = useState('ALL')

    // Modal state
    const [showModal, setShowModal] = useState(false)
    const [editingItem, setEditingItem] = useState(null)
    const [form, setForm] = useState({ code: '', name_ar: '', name_en: '', description: '' })
    const [saving, setSaving] = useState(false)

    // Rates modal state
    const [showRatesModal, setShowRatesModal] = useState(false)
    const [selectedClassification, setSelectedClassification] = useState(null)
    const [classificationRates, setClassificationRates] = useState([])
    const [loadingRates, setLoadingRates] = useState(false)

    // Add rate form
    const [showAddRate, setShowAddRate] = useState(false)
    const [rateForm, setRateForm] = useState({ country_code: '', tax_rate_id: '', tax_group_id: '' })
    const [availableRates, setAvailableRates] = useState([])

    const currentCountry = currentBranch?.country_code?.toUpperCase() || 'SA'

    const fetchClassifications = async () => {
        try {
            setLoading(true)
            const res = await taxesAPI.listClassifications()
            const all = res.data || []

            // Fetch rates for current country to show which classifications have rates
            const ratesRes = await taxesAPI.listClassificationsForCountry(currentCountry)
            const countryRates = ratesRes.data || []

            // Merge: attach country-specific rate info to each classification
            const merged = all.map(c => {
                const rateInfo = countryRates.find(r => r.classification_id === c.id)
                return {
                    ...c,
                    country_tax_rate: rateInfo?.tax_rate ?? null,
                    country_tax_name: rateInfo?.tax_name ?? null,
                    country_tax_code: rateInfo?.tax_code ?? null,
                    has_country_rate: !!rateInfo?.tax_rate_id
                }
            })

            setClassifications(merged)
        } catch (err) {
            showToast(t('common.error', 'حدث خطأ'), 'error')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchClassifications()
    }, [currentCountry])

    const openCreateModal = () => {
        setEditingItem(null)
        setForm({ code: '', name_ar: '', name_en: '', description: '' })
        setShowModal(true)
    }

    const openEditModal = (item) => {
        setEditingItem(item)
        setForm({
            code: item.code,
            name_ar: item.name_ar,
            name_en: item.name_en || '',
            description: item.description || ''
        })
        setShowModal(true)
    }

    const handleSave = async () => {
        if (!form.code.trim() || !form.name_ar.trim()) {
            showToast(t('taxes.fill_required', 'يرجى ملء الحقول المطلوبة'), 'warning')
            return
        }
        setSaving(true)
        try {
            if (editingItem) {
                await taxesAPI.updateClassification(editingItem.id, form)
                showToast(t('common.saved', 'تم الحفظ'), 'success')
            } else {
                await taxesAPI.createClassification(form)
                showToast(t('common.created', 'تم الإنشاء'), 'success')
            }
            setShowModal(false)
            fetchClassifications()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setSaving(false)
        }
    }

    const handleDelete = async (item) => {
        if (!confirm(t('taxes.confirm_delete_classification', `هل تريد حذف التصنيف "${item.name_ar}"؟`))) return
        try {
            await taxesAPI.deleteClassification(item.id)
            showToast(t('common.deleted', 'تم الحذف'), 'success')
            fetchClassifications()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const openRatesModal = async (item) => {
        setSelectedClassification(item)
        setShowRatesModal(true)
        setLoadingRates(true)
        try {
            const [ratesRes, taxRatesRes] = await Promise.all([
                taxesAPI.getClassificationRates(item.id),
                taxesAPI.listRates({ is_active: true, country_code: currentCountry })
            ])
            setClassificationRates(ratesRes.data || [])
            setAvailableRates(taxRatesRes.data || [])
        } catch (err) {
            showToast(t('common.error'), 'error')
        } finally {
            setLoadingRates(false)
        }
    }

    const handleAddRate = async () => {
        const cc = rateForm.country_code || currentCountry
        if (!cc.trim()) {
            showToast(t('taxes.enter_country_code', 'يرجى إدخال رمز الدولة'), 'warning')
            return
        }
        try {
            await taxesAPI.addClassificationRate(selectedClassification.id, {
                country_code: cc.toUpperCase(),
                tax_rate_id: rateForm.tax_rate_id ? parseInt(rateForm.tax_rate_id) : null,
                tax_group_id: rateForm.tax_group_id ? parseInt(rateForm.tax_group_id) : null
            })
            showToast(t('common.created', 'تم الإنشاء'), 'success')
            setRateForm({ country_code: '', tax_rate_id: '', tax_group_id: '' })
            setShowAddRate(false)
            const res = await taxesAPI.getClassificationRates(selectedClassification.id)
            setClassificationRates(res.data || [])
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleDeleteRate = async (rateLinkId) => {
        if (!confirm(t('taxes.confirm_delete_rate', 'هل تريد حذف هذا الربط؟'))) return
        try {
            await taxesAPI.deleteClassificationRate(selectedClassification.id, rateLinkId)
            showToast(t('common.deleted', 'تم الحذف'), 'success')
            const res = await taxesAPI.getClassificationRates(selectedClassification.id)
            setClassificationRates(res.data || [])
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const filtered = classifications.filter(c => {
        if (!showInactive && !c.is_active) return false
        if (searchQuery) {
            const q = searchQuery.toLowerCase()
            return c.code.toLowerCase().includes(q) ||
                   c.name_ar.includes(q) ||
                   (c.name_en && c.name_en.toLowerCase().includes(q))
        }
        return true
    })

    const classificationColumns = [
        {
            key: 'code',
            label: t('taxes.code', 'الرمز'),
            width: '120px',
            render: (value) => (
                <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--primary)', background: 'var(--primary-light)', padding: '2px 8px', borderRadius: 4, fontSize: 12 }}>
                    {value}
                </span>
            ),
        },
        { key: 'name_ar', label: t('taxes.name_ar', 'الاسم بالعربي'), render: (v) => <span style={{ fontWeight: 600 }}>{v}</span> },
        { key: 'name_en', label: t('taxes.name_en', 'الاسم بالإنجليزي'), render: (v) => <span style={{ color: 'var(--text-secondary)' }}>{v || '—'}</span> },
        {
            key: 'country_tax_rate',
            label: `${t('taxes.tax_rate_for', 'المعدل')} (${currentCountry})`,
            render: (v, item) => item.has_country_rate ? (
                <span style={{ fontWeight: 700, color: 'var(--success, #16a34a)' }}>
                    {v}% {item.country_tax_name || ''}
                </span>
            ) : (
                <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                    {t('taxes.no_rate_for_country', 'لا يوجد معدل')}
                </span>
            ),
        },
        {
            key: 'is_active',
            label: t('common.status_title', 'الحالة'),
            width: '90px',
            render: (v) => <span className={`badge ${v ? 'badge-success' : 'badge-danger'}`}>{v ? t('common.active', 'نشط') : t('common.inactive', 'غير نشط')}</span>,
        },
        {
            key: 'actions',
            label: t('common.actions', 'الإجراءات'),
            width: '170px',
            sortable: false,
            searchable: false,
            exportable: false,
            render: (_, item) => (
                <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => openRatesModal(item)} title={t('taxes.manage_rates', 'المعدلات')}>
                        <Globe size={14} />
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => openEditModal(item)} title={t('common.edit', 'تعديل')}>
                        <Edit2 size={14} />
                    </button>
                    {item.is_active && (
                        <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(item)} title={t('common.delete', 'حذف')} style={{ color: 'var(--danger)' }}>
                            <Trash2 size={14} />
                        </button>
                    )}
                </div>
            ),
        },
    ]

    const classificationRateColumns = [
        { key: 'country_code', label: t('taxes.country', 'الدولة'), render: (v) => <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Globe size={14} style={{ color: 'var(--primary)' }} /><strong>{v}</strong></span> },
        { key: 'tax_name', label: t('taxes.tax_name', 'اسم الضريبة'), render: (v) => v || t('taxes.exempt', 'معفى') },
        { key: 'tax_code', label: t('taxes.tax_code', 'رمز الضريبة'), render: (v) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v || '—'}</span> },
        { key: 'tax_rate', label: t('taxes.rate', 'المعدل'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', fontWeight: 700 }, render: (v) => v != null ? `${v}%` : t('taxes.exempt', 'معفى') },
        { key: 'effective_from', label: t('taxes.effective_from', 'تاريخ البداية'), render: (v) => v || '—' },
        { key: 'actions', label: '', sortable: false, searchable: false, exportable: false, render: (_, r) => (
            <button className="btn btn-ghost btn-sm" onClick={() => handleDeleteRate(r.rate_link_id)} style={{ color: 'var(--danger)' }}>
                <Trash2 size={14} />
            </button>
        ) },
    ]

    if (loading) return <PageLoading />

    return (
        <div className="page-container">
            {/* Header */}
            <div className="page-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <button className="btn btn-ghost btn-icon" onClick={() => navigate('/taxes')} title={t('common.back')}>
                        <ChevronLeft size={20} />
                    </button>
                    <div>
                        <h1 style={{ fontSize: '20px', margin: 0 }}>🏷️ {t('taxes.tax_classifications', 'التصنيفات الضريبية')}</h1>
                        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '4px 0 0' }}>
                            {t('taxes.classifications_subtitle', 'إدارة تصنيفات المنتجات الضرريبية')}
                        </p>
                    </div>
                </div>
                <button className="btn btn-primary" onClick={openCreateModal}>
                    <Plus size={16} /> {t('taxes.add_classification', 'إضافة تصنيف')}
                </button>
            </div>

            {/* Filters */}
            <div className="card" style={{ marginTop: '16px', padding: '12px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative', flex: '1', minWidth: '200px' }}>
                        <Search size={16} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                        <input
                            type="text"
                            className="form-input"
                            placeholder={t('common.search', 'بحث...')}
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                            style={{ paddingLeft: '32px' }}
                        />
                        {searchQuery && (
                            <button
                                onClick={() => setSearchQuery('')}
                                style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                            >
                                <X size={14} />
                            </button>
                        )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Globe size={14} style={{ color: 'var(--primary)' }} />
                        <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>
                            {currentBranch?.branch_name || t('taxes.all_branches', 'كل الفروع')} ({currentCountry})
                        </span>
                    </div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                        <input
                            type="checkbox"
                            checked={showInactive}
                            onChange={e => setShowInactive(e.target.checked)}
                        />
                        {t('taxes.show_inactive', 'عرض غير النشطة')}
                    </label>
                    <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        {filtered.length} {t('common.items', 'عنصر')}
                    </span>
                </div>
            </div>

            {/* Table */}
            <div className="card" style={{ marginTop: '12px', padding: 0, overflow: 'hidden' }}>
                <DataTable
                    columns={classificationColumns}
                    data={filtered}
                    rowKey="id"
                    searchable
                    exportable
                    exportName="tax-classifications"
                    emptyTitle={t('taxes.no_classifications', 'لا توجد تصنيفات ضريبية')}
                />
            </div>

            {/* Create/Edit Modal */}
            <SimpleModal
                isOpen={showModal}
                onClose={() => setShowModal(false)}
                title={editingItem ? t('taxes.edit_classification', 'تعديل تصنيف ضريبي') : t('taxes.add_classification', 'إضافة تصنيف ضريبي')}
                size="md"
                footer={
                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                        <button className="btn btn-ghost" onClick={() => setShowModal(false)}>{t('common.cancel', 'إلغاء')}</button>
                        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                            {saving ? t('common.saving', 'جاري الحفظ...') : t('common.save', 'حفظ')}
                        </button>
                    </div>
                }
            >
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    <div>
                        <label className="form-label" style={{ fontWeight: '600' }}>{t('taxes.code', 'الرمز')} *</label>
                        <input
                            type="text"
                            className="form-input"
                            value={form.code}
                            onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })}
                            placeholder="TOBACCO"
                            maxLength={50}
                            disabled={!!editingItem}
                            style={{ fontFamily: 'monospace' }}
                        />
                        <small style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>{t('taxes.code_hint', 'رمز فريد بالإنجليزي (STANDARD, TOBACCO, etc.)')}</small>
                    </div>
                    <div>
                        <label className="form-label" style={{ fontWeight: '600' }}>{t('taxes.name_ar', 'الاسم بالعربي')} *</label>
                        <input
                            type="text"
                            className="form-input"
                            value={form.name_ar}
                            onChange={e => setForm({ ...form, name_ar: e.target.value })}
                            placeholder="منتجات التبغ"
                        />
                    </div>
                    <div>
                        <label className="form-label" style={{ fontWeight: '600' }}>{t('taxes.name_en', 'الاسم بالإنجليزي')}</label>
                        <input
                            type="text"
                            className="form-input"
                            value={form.name_en}
                            onChange={e => setForm({ ...form, name_en: e.target.value })}
                            placeholder="Tobacco Products"
                        />
                    </div>
                    <div>
                        <label className="form-label" style={{ fontWeight: '600' }}>{t('taxes.description', 'الوصف')}</label>
                        <textarea
                            className="form-input"
                            value={form.description}
                            onChange={e => setForm({ ...form, description: e.target.value })}
                            placeholder={t('taxes.description_hint', 'وصف مختصر للتصنيف...')}
                            rows={3}
                        />
                    </div>
                </div>
            </SimpleModal>

            {/* Rates Modal */}
            <SimpleModal
                isOpen={showRatesModal}
                onClose={() => { setShowRatesModal(false); setSelectedClassification(null) }}
                title={`${t('taxes.classification_rates', 'معدلات التصنيف')} — ${selectedClassification?.name_ar || ''}`}
                size="lg"
            >
                {loadingRates ? (
                    <div style={{ textAlign: 'center', padding: '30px' }}>{t('common.loading', 'جاري التحميل...')}</div>
                ) : (
                    <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0 }}>
                                {t('taxes.classification_rates_desc', 'ربط التصنيف بمعدلات ضريبية حسب الدولة')}
                            </p>
                            <button className="btn btn-primary btn-sm" onClick={() => setShowAddRate(!showAddRate)}>
                                <Plus size={14} /> {t('taxes.add_rate', 'إضافة معدل')}
                            </button>
                        </div>

                        {/* Add Rate Form */}
                        {showAddRate && (
                            <div className="card" style={{ padding: '14px', marginBottom: '12px', background: 'var(--bg-secondary)' }}>
                                <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 1fr auto', gap: '10px', alignItems: 'end' }}>
                                    <div>
                                        <label className="form-label" style={{ fontSize: '12px' }}>{t('taxes.country_code', 'الدولة')}</label>
                                        <input
                                            type="text"
                                            className="form-input"
                                            value={currentCountry}
                                            readOnly
                                            style={{ fontFamily: 'monospace', fontSize: '13px', textAlign: 'center', fontWeight: '700', background: 'var(--bg-secondary)' }}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" style={{ fontSize: '12px' }}>{t('taxes.tax_rate', 'المعدل الضريبي')}</label>
                                        <select
                                            className="form-input"
                                            value={rateForm.tax_rate_id}
                                            onChange={e => setRateForm({ ...rateForm, tax_rate_id: e.target.value, tax_group_id: '' })}
                                            style={{ fontSize: '13px' }}
                                        >
                                            <option value="">{t('taxes.select_rate', 'اختر...')}</option>
                                            {availableRates.map(r => (
                                                <option key={r.id} value={r.id}>{r.tax_name} ({r.rate_value}%)</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="form-label" style={{ fontSize: '12px' }}>{t('taxes.tax_group', 'مجموعة ضريبية')}</label>
                                        <input
                                            type="text"
                                            className="form-input"
                                            value={rateForm.tax_group_id}
                                            onChange={e => setRateForm({ ...rateForm, tax_group_id: e.target.value })}
                                            placeholder={t('taxes.optional', 'اختياري')}
                                            style={{ fontSize: '13px' }}
                                        />
                                    </div>
                                    <button className="btn btn-primary btn-sm" onClick={handleAddRate} style={{ height: '34px' }}>
                                        {t('common.add', 'إضافة')}
                                    </button>
                                </div>
                            </div>
                        )}

                        <DataTable
                            columns={classificationRateColumns}
                            data={classificationRates}
                            rowKey="rate_link_id"
                            searchable
                            exportable
                            exportName={`tax-classification-${selectedClassification?.code || 'rates'}`}
                            emptyTitle={t('taxes.no_rates', 'لا توجد معدلات مرتبطة')}
                        />
                    </div>
                )}
            </SimpleModal>
        </div>
    )
}
