import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { taxesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import './TaxHome.css'
import { formatShortDate } from '../../utils/dateUtils';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
import SimpleModal from '../../components/common/SimpleModal'
import DataTable from '../../components/common/DataTable'


function TaxHome() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const fallbackCurrency = getCurrency()
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [summary, setSummary] = useState(null)
    const [rates, setRates] = useState([])
    const [returns, setReturns] = useState([])
    const [activeTab, setActiveTab] = useState('overview')
    const [showRateModal, setShowRateModal] = useState(false)
    const [rateForm, setRateForm] = useState({ tax_code: '', tax_name: '', tax_name_en: '', rate_value: '', description: '', country_code: '' })
    const [editingRate, setEditingRate] = useState(null)
    const [branchAnalysis, setBranchAnalysis] = useState(null)
    const [employeeTaxes, setEmployeeTaxes] = useState(null)
    const [filterYear, setFilterYear] = useState(new Date().getFullYear())
    const currency = summary?.display_currency || branchAnalysis?.display_currency || fallbackCurrency

    const fetchAll = async () => {
        try {
            setLoading(true)
            const params = {};
            if (currentBranch) params.branch_id = currentBranch.id;
            
            const [summaryRes, ratesRes, returnsRes] = await Promise.all([
                taxesAPI.getSummary(params),
                taxesAPI.listRates(currentBranch ? { country_code: currentBranch.country_code } : { all_branches: true }),
                taxesAPI.listReturns(params)
            ])
            setSummary(summaryRes.data)
            setRates(ratesRes.data)
            setReturns(returnsRes.data)
        } catch (err) {
            console.error('Error fetching tax data:', err)
            showToast(err.response?.data?.detail || t('common.error', 'حدث خطأ في تحميل بيانات الضرائب'), 'error')
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    const fetchBranchAnalysis = async () => {
        try {
            const params = { start_date: `${filterYear}-01-01`, end_date: `${filterYear}-12-31` }
            if (currentBranch) params.branch_id = currentBranch.id
            const res = await taxesAPI.getBranchAnalysis(params)
            setBranchAnalysis(res.data)
        } catch (err) { console.error(err) }
    }

    const fetchEmployeeTaxes = async () => {
        try {
            const params = { year: filterYear }
            if (currentBranch) params.branch_id = currentBranch.id
            const res = await taxesAPI.getEmployeeTaxes(params)
            setEmployeeTaxes(res.data)
        } catch (err) { console.error(err) }
    }

    useEffect(() => { fetchAll() }, [currentBranch])
    useEffect(() => {
        if (activeTab === 'branch_analysis') fetchBranchAnalysis()
        if (activeTab === 'employee_taxes') fetchEmployeeTaxes()
    }, [activeTab, filterYear, currentBranch])

    const handleCreateRate = async () => {
        try {
            if (editingRate) {
                await taxesAPI.updateRate(editingRate.id, {
                    tax_name: rateForm.tax_name,
                    tax_name_en: rateForm.tax_name_en,
                    rate_value: String(rateForm.rate_value),
                    country_code: rateForm.country_code || null,
                    description: rateForm.description
                })
            } else {
                await taxesAPI.createRate({ ...rateForm, rate_value: String(rateForm.rate_value) })
            }
            setShowRateModal(false)
            setEditingRate(null)
            setRateForm({ tax_code: '', tax_name: '', tax_name_en: '', rate_value: '', description: '', country_code: '' })
            fetchAll()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'error'))
        }
    }

    const handleDeleteRate = async (id) => {
        if (!confirm(t('taxes.confirm_delete_rate'))) return
        try {
            await taxesAPI.deleteRate(id)
            fetchAll()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'error'))
        }
    }

    const handleEditRate = (rate) => {
        setEditingRate(rate)
        setRateForm({
            tax_code: rate.tax_code,
            tax_name: rate.tax_name,
            tax_name_en: rate.tax_name_en || '',
            rate_value: rate.rate_value,
            description: rate.description || '',
            country_code: rate.country_code || ''
        })
        setShowRateModal(true)
    }

    const getStatusBadge = (status) => {
        const map = {
            draft: { label: t('taxes.status_draft'), bg: 'rgb(254, 243, 199)', color: 'rgb(217, 119, 6)', emoji: '⏳' },
            filed: { label: t('taxes.status_filed'), bg: 'rgba(59, 130, 246, 0.1)', color: 'rgb(59, 130, 246)', emoji: '📤' },
            paid: { label: t('taxes.status_paid'), bg: 'rgb(220, 252, 231)', color: 'rgb(22, 163, 74)', emoji: '✅' },
            cancelled: { label: t('taxes.status_cancelled'), bg: 'rgb(254, 226, 226)', color: 'rgb(220, 38, 38)', emoji: '❌' },
            overdue: { label: t('taxes.status_overdue'), bg: 'rgb(254, 226, 226)', color: 'rgb(220, 38, 38)', emoji: '⚠️' }
        }
        const s = map[status] || { label: status, bg: 'rgba(107, 114, 128, 0.082)', color: 'rgb(107, 114, 128)', emoji: '' }
        return <span style={{ background: s.bg, color: s.color, padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: '600', whiteSpace: 'nowrap' }}>
            {s.emoji} {s.label}
        </span>
    }

    const recentReturnColumns = [
        { key: 'return_number', label: t('taxes.return_number'), render: (v) => <span className="fw-bold" style={{ color: 'var(--primary)', fontFamily: 'monospace' }}>{v}</span> },
        { key: 'tax_period', label: t('taxes.period') },
        { key: 'total_amount', label: t('taxes.amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', fontWeight: 700, whiteSpace: 'nowrap' }, render: (v) => <>{formatNumber(v)} <span className="text-muted fw-normal small">{currency}</span></> },
        { key: 'status', label: t('common.status_title'), render: (v) => getStatusBadge(v) },
    ]

    const rateColumns = [
        { key: 'tax_code', label: t('taxes.tax_code'), render: (v) => <span className="fw-bold" style={{ color: 'var(--primary)', fontFamily: 'monospace' }}>{v}</span> },
        { key: 'tax_name', label: t('taxes.tax_name') },
        { key: 'tax_name_en', label: t('taxes.tax_name_en'), render: (v) => v || <span className="text-muted">-</span> },
        { key: 'rate_value', label: t('taxes.rate_value'), render: (v) => <span style={{ fontWeight: 'bold', color: 'var(--primary)' }}>{v}%</span> },
        { key: 'country_code', label: t('taxes.country_code'), render: (v) => v ? <span style={{ background: 'rgba(59, 130, 246, 0.08)', padding: '3px 8px', borderRadius: '6px', fontSize: '11px', fontWeight: 600 }}>{v}</span> : <span className="text-muted" style={{ fontSize: '11px' }}>{t('taxes.global')}</span> },
        { key: 'effective_from', label: t('taxes.effective_from'), render: (v) => v ? formatShortDate(v) : <span className="text-muted">-</span> },
        { key: 'effective_to', label: t('taxes.effective_to'), render: (v) => v ? formatShortDate(v) : <span className="text-muted">-</span> },
        { key: 'is_active', label: t('common.status_title'), render: (v) => <span style={{ background: v ? 'rgb(220, 252, 231)' : 'rgb(254, 226, 226)', color: v ? 'rgb(22, 163, 74)' : 'rgb(220, 38, 38)', padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 600, whiteSpace: 'nowrap' }}>{v ? t('common.active') : t('common.inactive')}</span> },
        { key: 'actions', label: t('common.actions'), width: '132px', sticky: 'end', sortable: false, searchable: false, exportable: false, render: (_, rate) => (
            <div style={{ display: 'flex', gap: 4 }}>
                <button className="btn btn-sm btn-outline-primary" style={{ borderRadius: 8, fontSize: 12 }} onClick={() => handleEditRate(rate)}>{t('common.edit')}</button>
                {rate.is_active && <button className="btn btn-sm btn-outline-danger" style={{ borderRadius: 8, fontSize: 12 }} onClick={() => handleDeleteRate(rate.id)}>{t('common.delete')}</button>}
            </div>
        ) },
    ]

    const returnColumns = [
        { key: 'return_number', label: t('taxes.return_number'), render: (v) => <span className="fw-bold" style={{ color: 'var(--primary)', fontFamily: 'monospace' }}>{v}</span> },
        { key: 'tax_period', label: t('taxes.period') },
        { key: 'tax_type', label: t('taxes.tax_type'), render: (v) => <span style={{ background: 'rgba(59, 130, 246, 0.1)', color: 'rgb(59, 130, 246)', padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>{v === 'vat' ? 'ض.ق.م' : v}</span> },
        { key: 'branch_name', label: t('common.branch'), render: (v) => v || <span className="text-muted">-</span> },
        { key: 'taxable_amount', label: t('taxes.taxable_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap' }, render: (v) => formatNumber(v) },
        { key: 'tax_amount', label: t('taxes.tax_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap' }, render: (v) => formatNumber(v) },
        { key: 'total_amount', label: t('taxes.total_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', fontWeight: 700, whiteSpace: 'nowrap' }, render: (v) => <>{formatNumber(v)} <span className="text-muted fw-normal small">{currency}</span></> },
        { key: 'paid_amount', label: t('taxes.paid_amount'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap' }, render: (v) => formatNumber(v || 0) },
        { key: 'due_date', label: t('taxes.due_date'), render: (v) => v ? formatShortDate(v) : <span className="text-muted">-</span> },
        { key: 'status', label: t('common.status_title'), render: (v) => getStatusBadge(v) },
        { key: 'actions', label: t('common.actions'), sortable: false, searchable: false, exportable: false, render: (_, r) => (
            <button className="btn btn-sm btn-outline-primary" style={{ borderRadius: 8, fontSize: 12 }} onClick={(e) => { e.stopPropagation(); navigate(`/taxes/returns/${r.id}`); }}>
                {t('common.view')}
            </button>
        ) },
    ]

    const branchAnalysisColumns = [
        { key: 'branch_name', label: t('common.branch'), render: (v) => <span style={{ fontWeight: 600 }}>{v}</span> },
        { key: 'jurisdiction', label: t('taxes.jurisdiction'), render: (v) => <span style={{ background: 'rgba(59, 130, 246, 0.1)', color: 'rgb(59, 130, 246)', padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600 }}>{v}</span> },
        { key: 'taxable_sales', label: t('taxes.taxable_sales'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap' }, render: (v, b) => <>{formatNumber(v)} <small>{b.currency || currency}</small></> },
        { key: 'output_vat', label: t('taxes.output_vat'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap', color: 'var(--secondary)' }, render: (v, b) => <>{formatNumber(v)} <small>{b.currency || currency}</small></> },
        { key: 'input_vat', label: t('taxes.input_vat'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap', color: 'var(--primary)' }, render: (v, b) => <>{formatNumber(v)} <small>{b.currency || currency}</small></> },
        { key: 'net_vat', label: t('taxes.net_vat'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap', fontWeight: 700 }, render: (v, b) => <span style={{ color: Number(v || 0) >= 0 ? 'var(--error)' : 'var(--success)' }}>{formatNumber(Math.abs(Number(v || 0)))} <small>{b.currency || currency}</small></span> },
        { key: 'invoice_count', label: t('taxes.invoices'), style: { textAlign: 'center' } },
        { key: 'returns_count', label: t('taxes.returns_filed'), style: { textAlign: 'center' }, render: (_, b) => b.returns_count || <span className="text-muted">-</span> },
    ]

    const employeeTaxColumns = [
        { key: 'employee_code', label: t('hr.employee_code'), render: (v) => <span style={{ fontFamily: 'monospace', color: 'var(--primary)', fontWeight: 600 }}>{v}</span> },
        { key: 'employee_name', label: t('hr.employee_name'), render: (v) => <span style={{ fontWeight: 600 }}>{v}</span> },
        { key: 'branch_name', label: t('common.branch'), render: (v) => v || '-' },
        { key: 'jurisdiction', label: t('taxes.jurisdiction'), render: (v) => <span style={{ background: 'rgba(59, 130, 246, 0.1)', color: 'rgb(59, 130, 246)', padding: '3px 8px', borderRadius: 6, fontSize: 11 }}>{v}</span> },
        { key: 'total_gross', label: t('taxes.total_gross'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap' }, render: (v) => formatNumber(v) },
        { key: 'gosi_employee', label: t('taxes.gosi_employee'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap', color: 'var(--warning)' }, render: (v) => formatNumber(v) },
        { key: 'gosi_employer', label: t('taxes.gosi_employer'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap', color: 'var(--secondary)' }, render: (v) => formatNumber(v) },
        { key: 'income_tax_due', label: t('taxes.income_tax'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap' }, render: (v, emp) => Number(v || 0) > 0 ? <span style={{ color: 'var(--error)', fontWeight: 600 }}>{formatNumber(v)} ({emp.income_tax_rate}%)</span> : <span className="text-muted">-</span> },
        { key: 'total_net', label: t('taxes.total_net'), headerStyle: { textAlign: 'left' }, style: { textAlign: 'left', whiteSpace: 'nowrap', fontWeight: 700 }, render: (v) => formatNumber(v) },
        { key: 'payslip_count', label: t('taxes.payslips'), style: { textAlign: 'center' } },
    ]

    if (initialLoad && !summary) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <div>
                        <h1 className="workspace-title">🧾 {t('taxes.title')}</h1>
                        <p className="workspace-subtitle">{t('taxes.subtitle')}</p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <button className="btn btn-primary" onClick={() => navigate('/taxes/returns/new')}>
                            + {t('taxes.new_return')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Summary Cards */}
            {summary && (
                <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                    <div className="metric-card">
                        <div className="metric-label">{t('taxes.active_rates')}</div>
                        <div className="metric-value">{summary.active_rates}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('taxes.output_vat_current')}</div>
                        <div className="metric-value text-secondary">{formatNumber(summary.current_period.output_vat)} <small>{currency}</small></div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('taxes.input_vat_current')}</div>
                        <div className="metric-value text-primary">{formatNumber(summary.current_period.input_vat)} <small>{currency}</small></div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('taxes.net_vat_current')}</div>
                        <div className={`metric-value ${summary.current_period.net_vat >= 0 ? 'text-error' : 'text-success'}`}>
                            {formatNumber(Math.abs(summary.current_period.net_vat))} <small>{currency}</small>
                        </div>
                        <div className="metric-change">{summary.current_period.net_vat >= 0 ? (t('taxes.payable')) : (t('taxes.refundable'))}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('taxes.pending_returns')}</div>
                        <div className="metric-value text-warning">{summary.returns.filed}</div>
                        <div className="metric-change">{formatNumber(summary.returns.pending_amount)} {currency}</div>
                    </div>
                    {summary.overdue_returns > 0 && (
                        <div className="metric-card" style={{ borderColor: 'var(--error)' }}>
                            <div className="metric-label" style={{ color: 'var(--error)' }}>⚠️ {t('taxes.overdue_returns')}</div>
                            <div className="metric-value text-error">{summary.overdue_returns}</div>
                        </div>
                    )}
                </div>
            )}

            {/* Tabs */}
            <div className="tabs mt-4">
                {['overview', 'rates', 'returns', 'branch_analysis', 'employee_taxes'].map(tab => (
                    <button key={tab} className={`tab ${activeTab === tab ? 'active' : ''}`} onClick={() => setActiveTab(tab)}>
                        {tab === 'overview' && (t('taxes.tab_overview'))}
                        {tab === 'rates' && (t('taxes.tab_rates'))}
                        {tab === 'returns' && (t('taxes.tab_returns'))}
                        {tab === 'branch_analysis' && (t('taxes.tab_branch_analysis'))}
                        {tab === 'employee_taxes' && (t('taxes.tab_employee_taxes'))}
                    </button>
                ))}
            </div>

            {/* Overview Tab */}
            {activeTab === 'overview' && (
                <div className="mt-4">
                    {/* Grouped Navigation Cards */}
                    <div className="modules-grid" style={{ gap: '16px', marginBottom: '20px' }}>

                        {/* Tax Returns */}
                        <div className="card">
                            <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                📝 {t('taxes.returns_management', 'إدارة الإقرارات')}
                            </h3>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px', marginTop: '12px' }}>
                                <Link to="/taxes/returns/new" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    📝 {t('taxes.create_return')}
                                </Link>
                                <button className="btn btn-outline" onClick={() => setActiveTab('returns')} style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    📋 {t('taxes.tab_returns')}
                                </button>
                            </div>
                        </div>

                        {/* Reports & Analysis */}
                        <div className="card">
                            <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                📊 {t('taxes.reports_analysis', 'التقارير والتحليل')}
                            </h3>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px', marginTop: '12px' }}>
                                <Link to="/accounting/vat-report" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    📊 {t('taxes.vat_report')}
                                </Link>
                                <Link to="/accounting/tax-audit" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    🔍 {t('taxes.audit_report')}
                                </Link>
                                <Link to="/taxes/compliance" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    🛡️ {t('taxes.tax_compliance')}
                                </Link>
                            </div>
                        </div>

                        {/* Settings & Tools */}
                        <div className="card">
                            <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                ⚙️ {t('taxes.settings_tools', 'الإعدادات والأدوات')}
                            </h3>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px', marginTop: '12px' }}>
                                <button className="btn btn-outline" onClick={() => setActiveTab('rates')} style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    ⚙️ {t('taxes.manage_rates')}
                                </button>
                                <Link to="/taxes/classifications" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    🏷️ {t('taxes.tax_classifications', 'التصنيفات الضريبية')}
                                </Link>
                                <Link to="/taxes/wht" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    ✂️ {t('wht.title')}
                                </Link>
                                <Link to="/taxes/calendar" className="btn btn-outline" style={{ textAlign: 'center', fontSize: '13px', padding: '10px 8px' }}>
                                    📅 {t('taxes.tax_calendar', 'التقويم الضريبي')}
                                </Link>
                            </div>
                        </div>
                    </div>

                    {/* Recent Returns Table */}
                    <div className="card">
                        <h3 className="section-title">{t('taxes.recent_returns')}</h3>
                        <DataTable
                            columns={recentReturnColumns}
                            data={returns.slice(0, 5)}
                            rowKey="id"
                            paginate={false}
                            searchable
                            exportable
                            exportName="tax-recent-returns"
                            emptyTitle={t('taxes.no_returns')}
                            onRowClick={(r) => navigate(`/taxes/returns/${r.id}`)}
                        />
                    </div>
                </div>
            )}

            {/* Rates Tab */}
            {activeTab === 'rates' && (
                <div className="card mt-4">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h3 className="section-title" style={{ margin: 0 }}>{t('taxes.tax_rates')}</h3>
                        <button className="btn btn-primary btn-sm" onClick={() => { setEditingRate(null); setRateForm({ tax_code: '', tax_name: '', tax_name_en: '', rate_value: '', description: '', country_code: '' }); setShowRateModal(true) }}>
                            + {t('taxes.add_rate')}
                        </button>
                    </div>
                    <DataTable
                        columns={rateColumns}
                        data={rates}
                        rowKey="id"
                        searchable
                        exportable
                        exportName="tax-rates"
                        emptyTitle={t('taxes.no_rates')}
                    />
                </div>
            )}

            {/* Returns Tab */}
            {activeTab === 'returns' && (
                <div className="card mt-4">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h3 className="section-title" style={{ margin: 0 }}>{t('taxes.tax_returns')}</h3>
                        <button className="btn btn-primary btn-sm" onClick={() => navigate('/taxes/returns/new')}>
                            + {t('taxes.new_return')}
                        </button>
                    </div>
                    <DataTable
                        columns={returnColumns}
                        data={returns}
                        rowKey="id"
                        searchable
                        exportable
                        exportName="tax-returns"
                        emptyTitle={t('taxes.no_returns')}
                        onRowClick={(r) => navigate(`/taxes/returns/${r.id}`)}
                    />
                </div>
            )}

            {/* Tax Rate Modal */}
            <SimpleModal
                isOpen={showRateModal}
                onClose={() => { setShowRateModal(false); setEditingRate(null); }}
                title={editingRate ? t('taxes.edit_rate') : t('taxes.add_rate')}
                size="md"
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => { setShowRateModal(false); setEditingRate(null); }}>
                            {t('common.cancel')}
                        </button>
                        <button className="btn btn-primary" onClick={handleCreateRate}
                            disabled={!rateForm.tax_name || (!editingRate && !rateForm.tax_code)}>
                            {editingRate ? t('common.save') : t('common.create')}
                        </button>
                    </>
                }
            >
                {!editingRate && (
                    <div className="form-group mb-3">
                        <label className="form-label">{t('taxes.tax_code')} *</label>
                        <input className="form-input" value={rateForm.tax_code}
                            onChange={e => setRateForm({...rateForm, tax_code: e.target.value})}
                            placeholder="مثال: VAT15, WHT5" />
                    </div>
                )}
                <div className="form-group mb-3">
                    <label className="form-label">{t('taxes.tax_name')} *</label>
                    <input className="form-input" value={rateForm.tax_name}
                        onChange={e => setRateForm({...rateForm, tax_name: e.target.value})}
                        placeholder="مثال: ضريبة القيمة المضافة" />
                </div>
                <div className="form-group mb-3">
                    <label className="form-label">{t('taxes.tax_name_en')}</label>
                    <input className="form-input" value={rateForm.tax_name_en}
                        onChange={e => setRateForm({...rateForm, tax_name_en: e.target.value})}
                        placeholder={t('taxes.tax_name_placeholder')} />
                </div>
                <div className="form-group mb-3">
                    <label className="form-label">{t('taxes.rate_value')} *</label>
                    <input className="form-input" type="number" min="0" max="100" step="0.01"
                        value={rateForm.rate_value}
                        onChange={e => setRateForm({...rateForm, rate_value: e.target.value})} />
                </div>
                <div className="form-group mb-3">
                    <label className="form-label">{t('taxes.country_code')}</label>
                    <select className="form-input" value={rateForm.country_code || ''}
                        onChange={e => setRateForm({...rateForm, country_code: e.target.value || null})}>
                        <option value="">{t('taxes.all_countries')}</option>
                        <option value="SA">🇸🇦 السعودية</option>
                        <option value="SY">🇸🇾 سوريا</option>
                        <option value="AE">🇦🇪 الإمارات</option>
                        <option value="EG">🇪🇬 مصر</option>
                        <option value="JO">🇯🇴 الأردن</option>
                        <option value="KW">🇰🇼 الكويت</option>
                        <option value="BH">🇧🇭 البحرين</option>
                        <option value="OM">🇴🇲 عمان</option>
                        <option value="QA">🇶🇦 قطر</option>
                        <option value="IQ">🇮🇶 العراق</option>
                        <option value="LB">🇱🇧 لبنان</option>
                        <option value="TR">🇹🇷 تركيا</option>
                    </select>
                </div>
                <div className="form-group mb-3">
                    <label className="form-label">{t('taxes.description')}</label>
                    <textarea className="form-input" rows="2" value={rateForm.description}
                        onChange={e => setRateForm({...rateForm, description: e.target.value})} />
                </div>
            </SimpleModal>

            {/* ═══ Branch Tax Analysis Tab ═══ */}
            {activeTab === 'branch_analysis' && (
                <div className="card mt-4">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h3 className="section-title" style={{ margin: 0 }}>📊 {t('taxes.branch_analysis_title')}</h3>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <label style={{ fontSize: '13px' }}>{t('common.year')}:</label>
                            <select className="form-input" style={{ width: '100px' }} value={filterYear}
                                onChange={e => setFilterYear(parseInt(e.target.value))}>
                                {[...Array(5)].map((_, i) => {
                                    const y = new Date().getFullYear() - i
                                    return <option key={y} value={y}>{y}</option>
                                })}
                            </select>
                        </div>
                    </div>

                    {branchAnalysis && branchAnalysis.totals && (
                        <div className="metrics-grid mb-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.total_output_vat')}</div>
                                <div className="metric-value text-secondary">{formatNumber(branchAnalysis.totals.output_vat)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.total_input_vat')}</div>
                                <div className="metric-value text-primary">{formatNumber(branchAnalysis.totals.input_vat)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.net_vat')}</div>
                                <div className={`metric-value ${branchAnalysis.totals.net_vat >= 0 ? 'text-error' : 'text-success'}`}>
                                    {formatNumber(Math.abs(branchAnalysis.totals.net_vat))} <small>{currency}</small>
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.branches_count')}</div>
                                <div className="metric-value">{branchAnalysis.totals.branch_count}</div>
                            </div>
                        </div>
                    )}

                    <DataTable
                        columns={branchAnalysisColumns}
                        data={branchAnalysis?.branches || []}
                        rowKey="branch_id"
                        searchable
                        exportable
                        exportName="tax-branch-analysis"
                        emptyTitle={t('taxes.no_branch_data')}
                    />
                </div>
            )}

            {/* ═══ Employee Taxes Tab ═══ */}
            {activeTab === 'employee_taxes' && (
                <div className="card mt-4">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h3 className="section-title" style={{ margin: 0 }}>👥 {t('taxes.employee_taxes_title')}</h3>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <label style={{ fontSize: '13px' }}>{t('common.year')}:</label>
                            <select className="form-input" style={{ width: '100px' }} value={filterYear}
                                onChange={e => setFilterYear(parseInt(e.target.value))}>
                                {[...Array(5)].map((_, i) => {
                                    const y = new Date().getFullYear() - i
                                    return <option key={y} value={y}>{y}</option>
                                })}
                            </select>
                        </div>
                    </div>

                    {employeeTaxes && employeeTaxes.summary && (
                        <div className="metrics-grid mb-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.total_employees')}</div>
                                <div className="metric-value">{employeeTaxes.summary.total_employees}</div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.total_gross_salaries')}</div>
                                <div className="metric-value text-primary">{formatNumber(employeeTaxes.summary.total_gross)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.gosi_employee_total')}</div>
                                <div className="metric-value text-warning">{formatNumber(employeeTaxes.summary.total_gosi_employee)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('taxes.gosi_employer_total')}</div>
                                <div className="metric-value text-secondary">{formatNumber(employeeTaxes.summary.total_gosi_employer)} <small>{currency}</small></div>
                            </div>
                        </div>
                    )}

                    {employeeTaxes?.gosi_settings && (
                        <div className="alert alert-info mb-3" style={{ display: 'flex', gap: '20px', fontSize: '13px', padding: '10px 16px', background: 'rgba(59, 130, 246, 0.06)', borderRadius: '8px' }}>
                            <span>🏛️ <strong>{t('taxes.gosi_settings')}:</strong></span>
                            <span>{t('taxes.employee_share')}: <b>{employeeTaxes.gosi_settings.employee_pct}%</b></span>
                            <span>{t('taxes.employer_share')}: <b>{employeeTaxes.gosi_settings.employer_pct}%</b></span>
                            <span>{t('taxes.max_salary')}: <b>{formatNumber(employeeTaxes.gosi_settings.max_salary)} {currency}</b></span>
                        </div>
                    )}

                    <DataTable
                        columns={employeeTaxColumns}
                        data={employeeTaxes?.employees || []}
                        rowKey="employee_id"
                        searchable
                        exportable
                        exportName="tax-employee-obligations"
                        emptyTitle={t('taxes.no_employee_data')}
                    />
                </div>
            )}
        </div>
    )
}

export default TaxHome
