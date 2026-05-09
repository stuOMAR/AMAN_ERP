import { useState } from 'react'
import { zakatAPI } from '../../utils/api'
import { getCurrency, getCountry } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import BackButton from '../../components/common/BackButton'
import { formatNumber } from '../../utils/format'
import { Clock } from 'lucide-react'

// Countries with full Zakat calculation support
const ZAKAT_SUPPORTED_COUNTRIES = ['SA']

const COUNTRY_FLAGS = {
    SA: '🇸🇦', SY: '🇸🇾', AE: '🇦🇪', EG: '🇪🇬', JO: '🇯🇴',
    KW: '🇰🇼', BH: '🇧🇭', OM: '🇴🇲', QA: '🇶🇦', IQ: '🇮🇶',
    LB: '🇱🇧', TR: '🇹🇷'
}

function makeIdempotencyKey(prefix) {
    if (window.crypto?.randomUUID) return `${prefix}:${window.crypto.randomUUID()}`
    return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`
}

function ZakatCalculator() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const country = getCountry()
    const isSupported = ZAKAT_SUPPORTED_COUNTRIES.includes(country)
    const [fiscalYear, setFiscalYear] = useState(new Date().getFullYear())
    const [method, setMethod] = useState('net_assets')
    const [useGregorian, setUseGregorian] = useState(false)
    const [result, setResult] = useState(null)
    const [postResult, setPostResult] = useState(null)
    const [loading, setLoading] = useState(false)
    const [posting, setPosting] = useState(false)

    const handleCalculate = async () => {
        setLoading(true)
        setPostResult(null)
        try {
            const res = await zakatAPI.calculate({
                fiscal_year: fiscalYear, method, use_gregorian_rate: useGregorian,
                branch_id: currentBranch?.id || null
            })
            setResult(res.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setLoading(false) }
    }

    const handlePost = async () => {
        if (posting) return
        setPosting(true)
        try {
            const params = currentBranch?.id ? { branch_id: currentBranch.id } : {}
            const res = await zakatAPI.post(fiscalYear, params, makeIdempotencyKey(`zakat-post:${fiscalYear}`))
            setPostResult(res.data)
            showToast(t('zakat.posted_success'), 'success')
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setPosting(false) }
    }

    // Show Coming Soon for unsupported countries
    if (!isSupported) {
        const flag = COUNTRY_FLAGS[country] || '🌍'
        return (
            <div className="workspace fade-in">
                <div className="workspace-header">
                    <BackButton />
                    <div className="header-title">
                        <h1 className="workspace-title">🕌 {t('zakat.title')}</h1>
                        <p className="workspace-subtitle">{t('zakat.subtitle')}</p>
                    </div>
                </div>

                <div className="card" style={{ padding: '60px 20px', textAlign: 'center' }}>
                    <div style={{ fontSize: '64px', marginBottom: '16px' }}>{flag}</div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', marginBottom: '12px' }}>
                        <Clock size={28} style={{ color: 'var(--text-muted)' }} />
                        <h2 style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text-muted)' }}>
                            {t('coming_soon.title', 'قريباً')}
                        </h2>
                    </div>
                    <p style={{ color: 'var(--text-muted)', maxWidth: '480px', margin: '0 auto', lineHeight: 1.7 }}>
                        {t('zakat.coming_soon_country', 'حاسبة الزكاة غير متوفرة حالياً لدولتك. يعمل الفريق على دعم المزيد من الدول في التحديثات القادمة.')}
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🕌 {t('zakat.title')}</h1>
                    <p className="workspace-subtitle">{t('zakat.subtitle')}</p>
                </div>
            </div>

            <div className="alert alert-info mb-4">
                ℹ️ {t('zakat.islamic_note')}
            </div>

            <div className="card p-4">
                <div className="form-grid-4">
                    <div className="form-group">
                        <label>{t('zakat.fiscal_year')}</label>
                        <input type="number" className="form-input" value={fiscalYear} onChange={e => setFiscalYear(Number(e.target.value))} />
                    </div>
                    <div className="form-group">
                        <label>{t('zakat.method')}</label>
                        <select className="form-select" value={method} onChange={e => setMethod(e.target.value)}>
                            <option value="net_assets">{t('zakat.net_assets_method', 'صافي الملكية — ZATCA')}</option>
                            <option value="net_current_assets">{t('zakat.net_current_assets_method', 'صافي الأصول المتداولة (AAOIFI)')}</option>
                            <option value="adjusted_profit">{t('zakat.adjusted_profit_method')}</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label>{t('zakat.year_type')}</label>
                        <div className="flex items-center gap-2 mt-2">
                            <input type="checkbox" id="gregorian" checked={useGregorian} onChange={e => setUseGregorian(e.target.checked)} />
                            <label htmlFor="gregorian">{t('zakat.use_gregorian')}</label>
                        </div>
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <button className="btn btn-primary" onClick={handleCalculate} disabled={loading}>
                            {loading ? t('common.calculating') : t('zakat.calculate')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Method description */}
            {method === 'net_assets' && (
                <div className="alert alert-info mt-3" style={{ fontSize: '13px', lineHeight: 1.8 }}>
                    🏛️ <strong>{t('zakat.zatca_note_title', 'الطريقة النظامية — ZATCA:')}</strong>{' '}
                    {t('zakat.zatca_note_desc', 'الطريقة المعتمدة نظامياً من هيئة الزكاة والضريبة والجمارك. الوعاء = حقوق الملكية + الالتزامات طويلة الأجل + المخصصات + الربح - الأصول الثابتة - الاستثمارات طويلة الأجل.')}
                </div>
            )}
            {method === 'net_current_assets' && (
                <div className="alert alert-success mt-3" style={{ fontSize: '13px', lineHeight: 1.8 }}>
                    📖 <strong>{t('zakat.aaoifi_note_title', 'طريقة صافي الأصول المتداولة — AAOIFI:')}</strong>{' '}
                    {t('zakat.aaoifi_note_desc', 'وفقاً لمعايير AAOIFI وجمهور الفقهاء: الوعاء = النقد + عروض التجارة + المدينون المرجوون + استثمارات المضاربة - الالتزامات المتداولة (الديون الحالة). يستبعد: الأصول الثابتة والمعنوية والمشاريع تحت الإنشاء.')}
                </div>
            )}

            {result && (
                <>
                    {(() => {
                        const displayCurrency = result.display_currency || currency
                        return (
                            <>
                    {/* Zakat Base Details */}
                    <div className="grid grid-2 mt-4" style={{ gap: 16 }}>
                        <div className="card p-4">
                            <h3 className="card-title text-success mb-3">
                                ➕ {t('zakat.additions')}
                            </h3>
                            {result.additions && result.additions.filter(a => Number(a.amount || 0) !== 0 || a.is_subtotal).map((a, i) => (
                                <div key={i} className="flex justify-between py-1 border-bottom" style={a.is_subtotal ? { fontWeight: 'bold', borderTop: '2px solid var(--border)', paddingTop: '8px' } : {}}>
                                    <span>{a.label_ar || a.label}</span>
                                    <span className="font-medium" style={Number(a.amount || 0) < 0 ? { color: 'var(--danger)' } : {}}>{formatNumber(a.amount)} {displayCurrency}</span>
                                </div>
                            ))}
                            <div className="flex justify-between py-2 font-bold mt-2" style={{ borderTop: '3px double var(--border)', paddingTop: '10px' }}>
                                <span>{t('zakat.total_additions')}</span>
                                <span className="text-success">{formatNumber(result.total_additions || 0)} {displayCurrency}</span>
                            </div>
                        </div>
                        <div className="card p-4">
                            <h3 className="card-title text-danger mb-3">
                                ➖ {t('zakat.deductions')}
                            </h3>
                            {result.deductions && result.deductions.filter(d => Number(d.amount || 0) !== 0).length > 0 ? result.deductions.filter(d => Number(d.amount || 0) !== 0).map((d, i) => (
                                <div key={i} className="flex justify-between py-1 border-bottom">
                                    <span style={{ color: 'var(--text-muted)' }}>{d.label_ar || d.label}</span>
                                    <span className="font-medium" style={{ color: 'var(--text-muted)' }}>{formatNumber(d.amount)} {displayCurrency}</span>
                                </div>
                            )) : (
                                <div className="text-muted py-2">{t('zakat.no_deductions', 'لا توجد حسميات')}</div>
                            )}
                            {result.deductions && result.deductions.length > 0 && (
                                <div className="flex justify-between py-2 font-bold mt-2" style={{ borderTop: '3px double var(--border)', paddingTop: '10px' }}>
                                    <span>{t('zakat.total_deductions')}</span>
                                    <span className="text-danger">{formatNumber(result.total_deductions || 0)} {displayCurrency}</span>
                                </div>
                            )}
                            {result.details?.excluded_assets && result.details.excluded_assets.length > 0 && (
                                <div className="mt-3 p-2" style={{ background: 'var(--bg-secondary)', borderRadius: 8, fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.7 }}>
                                    📌 <strong>{t('zakat.excluded_info_title', 'للعلم — أصول غير زكوية:')}</strong>
                                    {result.details.excluded_assets.map((ea, i) => (
                                        <div key={i} className="flex justify-between mt-1">
                                            <span>{ea.label_ar || ea.label}</span>
                                            <span>{formatNumber(ea.amount)} {displayCurrency}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Final Result */}
                    <div className="card mt-4 p-4">
                        <div className="grid grid-3" style={{ gap: 16, textAlign: 'center' }}>
                            <div>
                                <div className="text-muted">{t('zakat.zakat_base')}</div>
                                <div className="text-xl font-bold">{formatNumber(result.zakat_base)} {displayCurrency}</div>
                            </div>
                            <div>
                                <div className="text-muted">{t('zakat.rate')}</div>
                                <div className="text-xl font-bold">{result.rate_display || '-'}</div>
                            </div>
                            <div>
                                <div className="text-muted">{t('zakat.zakat_amount')}</div>
                                <div className="text-2xl font-bold text-primary">{formatNumber(result.zakat_amount)} {displayCurrency}</div>
                            </div>
                        </div>

                        <div className="mt-4 flex justify-center">
                            {postResult ? (
                                <div className="alert alert-success" style={{ textAlign: 'center' }}>
                                    ✅ {t('zakat.posted_success')} — {t('zakat.gl_reference', 'مرجع القيد')}: <strong style={{ fontFamily: 'monospace' }}>{postResult.entry_number}</strong>
                                </div>
                            ) : (
                                <button className="btn btn-success" onClick={handlePost} disabled={posting}>
                                    {posting ? t('common.posting') : `✅ ${t('zakat.post_journal_entry')}`}
                                </button>
                            )}
                        </div>
                    </div>
                            </>
                        )
                    })()}
                </>
            )}
        </div>
    )
}

export default ZakatCalculator
