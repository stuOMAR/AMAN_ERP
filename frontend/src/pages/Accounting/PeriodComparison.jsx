import React, { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { reportsAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import BackButton from '../../components/common/BackButton'

import DateInput from '../../components/common/DateInput';
import { formatShortDate } from '../../utils/dateUtils';
import { PageLoading } from '../../components/common/LoadingStates'

// Report types use t() keys

// Preset periods use t() keys

function getPresetPeriods(preset) {
    const now = new Date()
    const y = now.getFullYear()
    const m = now.getMonth()
    const q = Math.floor(m / 3)

    switch (preset) {
        case 'yoy':
            return [
                { start: `${y}-01-01`, end: `${y}-12-31`, label: `${y}` },
                { start: `${y - 1}-01-01`, end: `${y - 1}-12-31`, label: `${y - 1}` },
            ]
        case 'qoq': {
            const qStart = (qi) => {
                const yr = qi < 0 ? y - 1 : y
                const qq = qi < 0 ? qi + 4 : qi
                const sm = qq * 3 + 1
                return `${yr}-${String(sm).padStart(2, '0')}-01`
            }
            const qEnd = (qi) => {
                const yr = qi < 0 ? y - 1 : y
                const qq = qi < 0 ? qi + 4 : qi
                const em = (qq + 1) * 3
                const lastDay = new Date(yr, em, 0).getDate()
                return `${yr}-${String(em).padStart(2, '0')}-${lastDay}`
            }
            return [
                { start: qStart(q), end: qEnd(q), label: `Q${q + 1} ${y}` },
                { start: qStart(q - 1), end: qEnd(q - 1), label: `Q${q > 0 ? q : 4} ${q > 0 ? y : y - 1}` },
            ]
        }
        case 'mom': {
            const mStart = (offset) => {
                const d = new Date(y, m + offset, 1)
                return d.toISOString().slice(0, 10)
            }
            const mEnd = (offset) => {
                const d = new Date(y, m + offset + 1, 0)
                return d.toISOString().slice(0, 10)
            }
            const mLabel = (offset) => {
                const d = new Date(y, m + offset, 1)
                return formatShortDate(d)
            }
            return [
                { start: mStart(0), end: mEnd(0), label: mLabel(0) },
                { start: mStart(-1), end: mEnd(-1), label: mLabel(-1) },
            ]
        }
        default:
            return [
                { start: `${y}-01-01`, end: `${y}-12-31`, label: `${y}` },
                { start: `${y - 1}-01-01`, end: `${y - 1}-12-31`, label: `${y - 1}` },
            ]
    }
}

export default function PeriodComparison() {
    const { t, i18n } = useTranslation()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()

    const [reportType, setReportType] = useState('profit-loss')
    const [preset, setPreset] = useState('yoy')
    const [customPeriods, setCustomPeriods] = useState(getPresetPeriods('yoy'))
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [result, setResult] = useState(null)

    const handlePresetChange = (p) => {
        setPreset(p)
        if (p !== 'custom') {
            setCustomPeriods(getPresetPeriods(p))
        }
    }

    const updatePeriod = (idx, field, val) => {
        setCustomPeriods(ps => {
            const copy = [...ps]
            copy[idx] = { ...copy[idx], [field]: val }
            return copy
        })
    }

    const addPeriod = () => {
        setPreset('custom')
        setCustomPeriods(ps => [...ps, { start: '', end: '', label: '' }])
    }

    const removePeriod = (idx) => {
        if (customPeriods.length <= 2) return
        setCustomPeriods(ps => ps.filter((_, i) => i !== idx))
    }

    const fetchComparison = useCallback(async () => {
        setLoading(true)
        try {
            let periodsStr
            if (reportType === 'balance-sheet') {
                periodsStr = customPeriods.map(p => p.end).join(',')
            } else {
                periodsStr = customPeriods.map(p => `${p.start}:${p.end}`).join(',')
            }

            const params = { periods: periodsStr }
            if (currentBranch?.id) params.branch_id = currentBranch.id

            let res
            if (reportType === 'profit-loss') {
                res = await reportsAPI.compareProfitLoss(params)
            } else if (reportType === 'balance-sheet') {
                res = await reportsAPI.compareBalanceSheet(params)
            } else {
                res = await reportsAPI.compareTrialBalance(params)
            }
            setResult(res.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }, [reportType, customPeriods, currentBranch])

    const formatNum = (n) => {
        if (n === 0 || n === undefined) return '-'
        return parseFloat(n).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }

    const changeColor = (val) => {
        if (val > 0) return 'text-success'
        if (val < 0) return 'text-danger'
        return ''
    }

    const periodLabels = result?.periods?.map((p, i) => {
        if (p.label) return p.label
        if (p.date) return p.date
        return `${p.start} → ${p.end}`
    }) || []

    const TYPE_LABELS = {
        asset: t('comparison.type_asset'),
        liability: t('comparison.type_liability'),
        equity: t('comparison.type_equity'),
        revenue: t('comparison.type_revenue'),
        expense: t('comparison.type_expense'),
    }

    return (
        <div className="module-container" dir={i18n.dir()}>
            <div className="module-header" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <BackButton />
                <h2>📊 {t('comparison.title')}</h2>
            </div>

            {/* Controls */}
            <div className="card mb-3">
                <div className="card-body">
                    <div className="row g-3 align-items-end">
                        <div className="col-md-3">
                            <label className="form-label">{t('comparison.report_type')}</label>
                            <select className="form-input" value={reportType} onChange={e => setReportType(e.target.value)}>
                                {[['profit-loss','comparison.report_profit_loss'],['balance-sheet','comparison.report_balance_sheet'],['trial-balance','comparison.report_trial_balance']].map(([k, tk]) => (
                                    <option key={k} value={k}>{t(tk)}</option>
                                ))}
                            </select>
                        </div>
                        <div className="col-md-3">
                            <label className="form-label">{t('comparison.period_preset')}</label>
                            <select className="form-input" value={preset} onChange={e => handlePresetChange(e.target.value)}>
                                {[['yoy','comparison.preset_yoy'],['qoq','comparison.preset_qoq'],['mom','comparison.preset_mom'],['custom','comparison.preset_custom']].map(([k, tk]) => (
                                    <option key={k} value={k}>{t(tk)}</option>
                                ))}
                            </select>
                        </div>
                        <div className="col-md-3">
                            <button className="btn btn-primary" onClick={fetchComparison} disabled={loading}>
                                {loading ? '⏳' : '🔍'} {t('comparison.compare')}
                            </button>
                        </div>
                        <div className="col-md-3 text-end">
                            <button className="btn btn-outline-secondary btn-sm" onClick={addPeriod}>
                                + {t('comparison.add_period')}
                            </button>
                        </div>
                    </div>

                    {/* Period inputs */}
                    <div className="mt-3">
                        {customPeriods.map((p, idx) => (
                            <div key={idx} className="row g-2 mb-2 align-items-center">
                                <div className="col-auto">
                                    <span className="badge bg-primary">{`${t('comparison.period_n')} ${idx + 1}`}</span>
                                </div>
                                <div className="col">
                                    <DateInput className="form-input form-input-sm" value={p.start}
                                        onChange={e => { updatePeriod(idx, 'start', e.target.value); setPreset('custom') }} />
                                </div>
                                <div className="col-auto">{t('comparison.to')}</div>
                                <div className="col">
                                    <DateInput className="form-input form-input-sm" value={p.end}
                                        onChange={e => { updatePeriod(idx, 'end', e.target.value); setPreset('custom') }} />
                                </div>
                                <div className="col">
                                    <input className="form-input form-input-sm" placeholder={t('comparison.label')}
                                        value={p.label || ''} onChange={e => updatePeriod(idx, 'label', e.target.value)} />
                                </div>
                                <div className="col-auto">
                                    {customPeriods.length > 2 && (
                                        <button className="btn btn-sm btn-outline-danger" onClick={() => removePeriod(idx)}>✕</button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Results */}
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {loading && <PageLoading />}

            {!loading && result && (
                <>
                    {/* Summary Cards */}
                    <div className="row g-3 mb-3">
                        {result.summary.map((s, idx) => (
                            <div key={idx} className="col-md">
                                <div className="card">
                                    <div className="card-header bg-light">
                                        <strong>{periodLabels[idx]}</strong>
                                    </div>
                                    <div className="card-body p-2">
                                        {reportType === 'profit-loss' && (
                                            <div className="row text-center">
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.revenue')}</div>
                                                    <div className="fw-bold text-success">{formatNum(s.total_revenue)} <small>{currency}</small></div>
                                                </div>
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.expenses')}</div>
                                                    <div className="fw-bold text-danger">{formatNum(s.total_expense)} <small>{currency}</small></div>
                                                </div>
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.net_income')}</div>
                                                    <div className={`fw-bold ${s.net_income >= 0 ? 'text-success' : 'text-danger'}`}>
                                                        {formatNum(s.net_income)} <small>{currency}</small>
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        {reportType === 'balance-sheet' && (
                                            <div className="row text-center">
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.assets')}</div>
                                                    <div className="fw-bold">{formatNum(s.total_assets)} <small>{currency}</small></div>
                                                </div>
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.liabilities')}</div>
                                                    <div className="fw-bold">{formatNum(s.total_liabilities)} <small>{currency}</small></div>
                                                </div>
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.equity')}</div>
                                                    <div className="fw-bold">{formatNum(s.total_equity)} <small>{currency}</small></div>
                                                </div>
                                            </div>
                                        )}
                                        {reportType === 'trial-balance' && (
                                            <div className="row text-center">
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.debit')}</div>
                                                    <div className="fw-bold">{formatNum(s.total_debit)} <small>{currency}</small></div>
                                                </div>
                                                <div className="col">
                                                    <div className="small text-muted">{t('comparison.credit')}</div>
                                                    <div className="fw-bold">{formatNum(s.total_credit)} <small>{currency}</small></div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Comparison Table */}
                    <div className="card">
                        <div className="card-body p-0">
                            <div className="data-table-container">
                                <table className="data-table table-hover mb-0">
                                    <thead className="table-light">
                                        <tr>
                                            <th>{t('comparison.code')}</th>
                                            <th>{t('comparison.account')}</th>
                                            <th>{t('comparison.type')}</th>
                                            {reportType === 'trial-balance' ? (
                                                periodLabels.map((label, idx) => (
                                                    <React.Fragment key={idx}>
                                                        <th className="text-end">{label} ({t('comparison.dr')})</th>
                                                        <th className="text-end">{label} ({t('comparison.cr')})</th>
                                                    </React.Fragment>
                                                ))
                                            ) : (
                                                <>
                                                    {periodLabels.map((label, idx) => (
                                                        <th key={idx} className="text-end">{label}</th>
                                                    ))}
                                                    <th className="text-end">{t('comparison.change')}</th>
                                                    <th className="text-end">%</th>
                                                </>
                                            )}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {result.comparison.map((row, idx) => (
                                            <tr key={idx}>
                                                <td className="text-muted small">{row.account_number}</td>
                                                <td>{i18n.language === 'ar' ? row.name : (row.name_en || row.name)}</td>
                                                <td><span className="badge bg-secondary">{TYPE_LABELS[row.account_type] || row.account_type}</span></td>
                                                {reportType === 'trial-balance' ? (
                                                    row.periods.map((p, pi) => (
                                                        <React.Fragment key={pi}>
                                                            <td className="text-end">{formatNum(p.debit)}</td>
                                                            <td className="text-end">{formatNum(p.credit)}</td>
                                                        </React.Fragment>
                                                    ))
                                                ) : (
                                                    <>
                                                        {row.periods.map((val, pi) => (
                                                            <td key={pi} className="text-end">{formatNum(val)}</td>
                                                        ))}
                                                        <td className={`text-end fw-bold ${changeColor(row.change)}`}>
                                                            {row.change > 0 ? '+' : ''}{formatNum(row.change)}
                                                        </td>
                                                        <td className={`text-end ${changeColor(row.change_pct)}`}>
                                                            {row.change_pct > 0 ? '+' : ''}{row.change_pct}%
                                                        </td>
                                                    </>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
