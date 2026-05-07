import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { taxesAPI } from '../../services/taxes'

/**
 * ProductTaxSelector — Professional tax mode selector for products.
 *
 * Modes:
 *   - inherit: Product inherits branch default tax
 *   - custom:  Product has a specific tax rate assigned
 *   - group:   Product uses a tax group (multiple taxes)
 *   - exempt:  Product is exempt from all taxes
 *
 * @param {Object} props
 * @param {number} props.branchId - Current branch ID
 * @param {Object} props.value - { mode, tax_rate_id, tax_rate, tax_name, tax_group_id, is_exempt }
 * @param {Function} props.onChange - Called with updated value object
 */
export default function ProductTaxSelector({ branchId, value, onChange }) {
    const { t } = useTranslation()
    const [branchTax, setBranchTax] = useState(null)
    const [availableTaxes, setAvailableTaxes] = useState([])
    const [availableGroups, setAvailableGroups] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    // Fetch branch tax, available taxes, and tax groups
    useEffect(() => {
        const fetchData = async () => {
            setLoading(true)
            setError(null)
            try {
                const [branchRes, ratesRes, groupsRes] = await Promise.all([
                    branchId ? taxesAPI.getBranchTax(branchId) : Promise.resolve(null),
                    taxesAPI.listRates({ is_active: true }),
                    taxesAPI.listGroups ? taxesAPI.listGroups().catch(() => ({ data: [] })) : Promise.resolve({ data: [] })
                ])
                setBranchTax(branchRes?.data || null)
                setAvailableTaxes(ratesRes?.data || [])
                setAvailableGroups(groupsRes?.data || [])
            } catch (err) {
                console.error('Failed to load tax data:', err)
                setError(t('taxes.load_error', 'تعذر تحميل الضريبة — سيتم استخدام ضريبة الفرع'))
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [branchId, t])

    const handleModeChange = (mode) => {
        if (mode === 'inherit') {
            onChange({
                mode: 'inherit',
                tax_rate_id: null,
                tax_rate: null,
                tax_name: null,
                tax_group_id: null,
                is_exempt: false,
            })
        } else if (mode === 'exempt') {
            onChange({
                mode: 'exempt',
                tax_rate_id: null,
                tax_rate: 0,
                tax_name: null,
                tax_group_id: null,
                is_exempt: true,
            })
        } else if (mode === 'custom') {
            const firstTax = availableTaxes[0]
            onChange({
                mode: 'custom',
                tax_rate_id: firstTax?.id || null,
                tax_rate: firstTax?.rate_value || 0,
                tax_name: firstTax?.tax_name || null,
                tax_group_id: null,
                is_exempt: false,
            })
        } else if (mode === 'group') {
            const firstGroup = availableGroups[0]
            onChange({
                mode: 'group',
                tax_rate_id: null,
                tax_rate: null,
                tax_name: firstGroup?.group_name || null,
                tax_group_id: firstGroup?.id || null,
                is_exempt: false,
            })
        }
    }

    const handleTaxSelect = (taxId) => {
        const selected = availableTaxes.find(t => t.id === parseInt(taxId))
        if (selected) {
            onChange({
                mode: 'custom',
                tax_rate_id: selected.id,
                tax_rate: selected.rate_value,
                tax_name: selected.tax_name,
                tax_group_id: null,
                is_exempt: false,
            })
        }
    }

    const handleGroupSelect = (groupId) => {
        const selected = availableGroups.find(g => g.id === parseInt(groupId))
        if (selected) {
            onChange({
                mode: 'group',
                tax_rate_id: null,
                tax_rate: null,
                tax_name: selected.group_name,
                tax_group_id: selected.id,
                is_exempt: false,
            })
        }
    }

    if (loading) {
        return (
            <div style={styles.container}>
                <div style={styles.loading}>
                    {t('taxes.loading', 'جاري تحميل بيانات الضريبة...')}
                </div>
            </div>
        )
    }

    return (
        <div style={styles.container}>
            {error && <div style={styles.error}>{error}</div>}

            {/* Option 1: Inherit from Branch */}
            <label style={{
                ...styles.option,
                ...(value.mode === 'inherit' ? styles.optionSelected : {})
            }}>
                <input
                    type="radio"
                    name="tax_mode"
                    checked={value.mode === 'inherit'}
                    onChange={() => handleModeChange('inherit')}
                    style={styles.radio}
                />
                <div style={styles.optionContent}>
                    <div style={styles.optionLabel}>
                        {t('taxes.inherit_branch', 'يرث ضريبة الفرع تلقائياً')}
                    </div>
                    {branchTax && (
                        <div style={styles.optionSublabel}>
                            ({branchTax.tax_name} {branchTax.tax_rate}% — {branchTax.country_code})
                        </div>
                    )}
                    {!branchTax && !error && (
                        <div style={styles.optionSublabel}>
                            {t('taxes.no_branch_tax', 'لا توجد ضريبة محددة لهذا الفرع')}
                        </div>
                    )}
                </div>
            </label>

            {/* Option 2: Custom Tax */}
            <label style={{
                ...styles.option,
                ...(value.mode === 'custom' ? styles.optionSelected : {})
            }}>
                <input
                    type="radio"
                    name="tax_mode"
                    checked={value.mode === 'custom'}
                    onChange={() => handleModeChange('custom')}
                    style={styles.radio}
                />
                <div style={styles.optionContent}>
                    <div style={styles.optionLabel}>
                        {t('taxes.custom_tax', 'ضريبة مخصصة')}
                    </div>
                    {value.mode === 'custom' && (
                        <div style={{ marginTop: '8px' }}>
                            <select
                                style={styles.select}
                                value={value.tax_rate_id || ''}
                                onChange={(e) => handleTaxSelect(e.target.value)}
                            >
                                {availableTaxes.map(tax => (
                                    <option key={tax.id} value={tax.id}>
                                        {tax.tax_name} — {tax.rate_value}%
                                        {tax.country_code ? ` (${tax.country_code})` : ''}
                                    </option>
                                ))}
                            </select>
                            {value.tax_rate_id && (
                                <div style={styles.selectedInfo}>
                                    {t('taxes.selected', 'المحدد')}: {value.tax_name} {value.tax_rate}%
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </label>

            {/* Option 3: Tax Group (multi-tax) */}
            <label style={{
                ...styles.option,
                ...(value.mode === 'group' ? styles.optionSelected : {})
            }}>
                <input
                    type="radio"
                    name="tax_mode"
                    checked={value.mode === 'group'}
                    onChange={() => handleModeChange('group')}
                    style={styles.radio}
                />
                <div style={styles.optionContent}>
                    <div style={styles.optionLabel}>
                        {t('taxes.tax_group', 'مجموعة ضرائب')}
                    </div>
                    <div style={styles.optionSublabel}>
                        {t('taxes.tax_group_desc', 'تطبيق عدة ضرائب على هذا المنتج (ضريبة + ضريبة استهلاك مثلاً)')}
                    </div>
                    {value.mode === 'group' && (
                        <div style={{ marginTop: '8px' }}>
                            <select
                                style={styles.select}
                                value={value.tax_group_id || ''}
                                onChange={(e) => handleGroupSelect(e.target.value)}
                            >
                                {availableGroups.map(group => (
                                    <option key={group.id} value={group.id}>
                                        {group.group_name}
                                        {group.group_code ? ` (${group.group_code})` : ''}
                                    </option>
                                ))}
                            </select>
                            {value.tax_group_id && (
                                <div style={styles.selectedInfo}>
                                    {t('taxes.selected', 'المحدد')}: {value.tax_name}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </label>

            {/* Option 4: Exempt */}
            <label style={{
                ...styles.option,
                ...(value.mode === 'exempt' ? styles.optionSelectedExempt : {})
            }}>
                <input
                    type="radio"
                    name="tax_mode"
                    checked={value.mode === 'exempt'}
                    onChange={() => handleModeChange('exempt')}
                    style={styles.radio}
                />
                <div style={styles.optionContent}>
                    <div style={styles.optionLabel}>
                        {t('taxes.exempt', 'معفى من الضريبة')}
                    </div>
                    <div style={styles.optionSublabel}>
                        {t('taxes.exempt_desc', 'لن يتم احتساب أي ضريبة على هذا المنتج')}
                    </div>
                </div>
            </label>
        </div>
    )
}

const styles = {
    container: {
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
    },
    loading: {
        padding: '12px',
        textAlign: 'center',
        color: 'var(--text-secondary, #6b7280)',
        fontSize: '13px',
    },
    error: {
        padding: '8px 12px',
        background: 'rgba(239, 68, 68, 0.1)',
        color: '#ef4444',
        borderRadius: '6px',
        fontSize: '12px',
        marginBottom: '4px',
    },
    option: {
        display: 'flex',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '10px 12px',
        borderRadius: '8px',
        border: '2px solid transparent',
        background: 'var(--bg-secondary, #f9fafb)',
        cursor: 'pointer',
        transition: 'all 0.2s',
    },
    optionSelected: {
        borderColor: 'var(--primary, #3b82f6)',
        background: 'var(--primary-light, #eff6ff)',
    },
    optionSelectedExempt: {
        borderColor: 'var(--warning, #f59e0b)',
        background: 'rgba(245, 158, 11, 0.08)',
    },
    radio: {
        marginTop: '2px',
        cursor: 'pointer',
    },
    optionContent: {
        flex: 1,
    },
    optionLabel: {
        fontWeight: '600',
        fontSize: '13px',
        color: 'var(--text-main, #1f2937)',
    },
    optionSublabel: {
        fontSize: '11px',
        color: 'var(--text-secondary, #6b7280)',
        marginTop: '2px',
    },
    select: {
        width: '100%',
        padding: '6px 10px',
        borderRadius: '6px',
        border: '1px solid var(--border-color, #e5e7eb)',
        background: 'var(--bg-card, white)',
        fontSize: '12px',
        color: 'var(--text-main, #1f2937)',
    },
    selectedInfo: {
        fontSize: '11px',
        color: 'var(--primary, #3b82f6)',
        fontWeight: '600',
        marginTop: '4px',
    },
}
