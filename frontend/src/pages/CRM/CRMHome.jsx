import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { crmAPI, salesAPI } from '../../utils/api'
import { getCurrency, hasPermission } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { formatShortDate } from '../../utils/dateUtils'
import '../../components/ModuleStyles.css'
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'
import { getIndustryFeature } from '../../hooks/useIndustryType'
import { PageLoading } from '../../components/common/LoadingStates'

// ─── Stage / Status / Priority maps ───────────────────────────────────────────
const stageBadgeColors = {
    lead: { background: '#3b82f6', color: '#fff' },
    qualified: { background: '#eab308', color: '#fff' },
    proposal: { background: '#f97316', color: '#fff' },
    negotiation: { background: '#8b5cf6', color: '#fff' },
    won: { background: '#22c55e', color: '#fff' },
    lost: { background: '#ef4444', color: '#fff' }
}
const statusBadgeStyles = {
    open: { background: '#3b82f6', color: '#fff' },
    in_progress: { background: '#eab308', color: '#fff' },
    resolved: { background: '#22c55e', color: '#fff' },
    closed: { background: '#6b7280', color: '#fff' }
}
const priorityBadgeStyles = {
    critical: { background: '#ef4444', color: '#fff' },
    high: { background: '#f97316', color: '#fff' },
    medium: { background: '#eab308', color: '#fff' },
    low: { background: '#22c55e', color: '#fff' }
}
const detailPanelStyle = {
    background: 'var(--bg-secondary,#f9fafb)',
    padding: 20,
    borderTop: '2px solid var(--border-color,#e5e7eb)'
}
const commentStyle = (isInternal) => ({
    background: isInternal ? 'rgba(234,179,8,0.08)' : 'var(--bg-primary,#fff)',
    border: `1px solid ${isInternal ? '#eab308' : 'var(--border-color,#e5e7eb)'}`,
    borderRadius: 8,
    padding: 12
})

// ══════════════════════════════════════════════════════════════════════════════
function CRMHome() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [activeTab, setActiveTab] = useState('overview')

    // ── Overview state ──────────────────────────────────────────────────────
    const [overviewLoading, setOverviewLoading] = useState(true)
    const [dashboardData, setDashboardData] = useState(null)

    // ── Opportunities state ─────────────────────────────────────────────────
    const [opportunities, setOpportunities] = useState([])
    const [oppLoading, setOppLoading] = useState(false)
    const [showOppModal, setShowOppModal] = useState(false)
    const [isOppEdit, setIsOppEdit] = useState(false)
    const [selectedOppId, setSelectedOppId] = useState(null)
    const [filterStage, setFilterStage] = useState('')
    const [deleteOppConfirm, setDeleteOppConfirm] = useState(null)
    const emptyOppForm = { title: '', customer_id: '', stage: 'lead', probability: 50, expected_value: '0.00', expected_close_date: '', source: '', notes: '' }
    const [oppForm, setOppForm] = useState({ ...emptyOppForm })

    // ── Support Tickets state ───────────────────────────────────────────────
    const [tickets, setTickets] = useState([])
    const [ticketsLoading, setTicketsLoading] = useState(false)
    const [showTicketModal, setShowTicketModal] = useState(false)
    const [filterStatus, setFilterStatus] = useState('')
    const [filterPriority, setFilterPriority] = useState('')
    const [expandedId, setExpandedId] = useState(null)
    const [ticketDetail, setTicketDetail] = useState(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const [commentText, setCommentText] = useState('')
    const [isInternal, setIsInternal] = useState(false)
    const emptyTicketForm = { subject: '', description: '', customer_id: '', priority: 'medium', category: '', sla_hours: 24 }
    const [ticketForm, setTicketForm] = useState({ ...emptyTicketForm })

    // ── Shared ──────────────────────────────────────────────────────────────
    const [customers, setCustomers] = useState([])

    const stageOptions = [
        { value: 'lead', label: t('crm.stage_lead') },
        { value: 'qualified', label: t('crm.stage_qualified') },
        { value: 'proposal', label: t('crm.stage_proposal') },
        { value: 'negotiation', label: t('crm.stage_negotiation') },
        { value: 'won', label: t('crm.stage_won') },
        { value: 'lost', label: t('crm.stage_lost') }
    ]
    const statusOptions = [
        { value: 'open', label: t('crm.status_open') },
        { value: 'in_progress', label: t('crm.status_in_progress') },
        { value: 'resolved', label: t('crm.status_resolved') },
        { value: 'closed', label: t('crm.status_closed') }
    ]
    const priorityOptions = [
        { value: 'critical', label: t('crm.priority_critical') },
        { value: 'high', label: t('crm.priority_high') },
        { value: 'medium', label: t('crm.priority_medium') },
        { value: 'low', label: t('crm.priority_low') }
    ]


    // ── Effects ─────────────────────────────────────────────────────────────
    useEffect(() => { fetchOverview(); fetchCustomers() }, [])
    useEffect(() => { if (activeTab === 'opportunities') fetchOpportunities() }, [activeTab, filterStage])
    useEffect(() => { if (activeTab === 'tickets') fetchTickets() }, [activeTab, filterStatus, filterPriority])

    // ── Fetch helpers ───────────────────────────────────────────────────────
    const fetchOverview = async () => {
        try {
            setOverviewLoading(true)
            const res = await crmAPI.getDashboard()
            setDashboardData(res.data)
        } catch (err) { console.error('Failed to fetch CRM overview', err) }
        finally { setOverviewLoading(false) }
    }
    const fetchCustomers = async () => {
        try { const res = await salesAPI.listCustomers(); setCustomers(res.data || []) }
        catch (err) { console.error(err) }
    }
    const fetchOpportunities = async () => {
        try {
            setOppLoading(true)
            const params = {}; if (filterStage) params.stage = filterStage
            const res = await crmAPI.listOpportunities(params); setOpportunities(res.data)
        } catch (err) { console.error(err) } finally { setOppLoading(false) }
    }
    const fetchTickets = async () => {
        try {
            setTicketsLoading(true)
            const params = {}
            if (filterStatus) params.status = filterStatus
            if (filterPriority) params.priority = filterPriority
            const res = await crmAPI.listTickets(params); setTickets(res.data)
        } catch (err) { console.error(err) } finally { setTicketsLoading(false) }
    }

    // ── Opportunity handlers ────────────────────────────────────────────────
    const openCreateOpp = () => { setOppForm({ ...emptyOppForm }); setIsOppEdit(false); setSelectedOppId(null); setShowOppModal(true) }
    const openEditOpp = (opp) => {
        setOppForm({ title: opp.title || '', customer_id: opp.customer_id || '', stage: opp.stage || 'lead', probability: opp.probability ?? 50, expected_value: opp.expected_value || '0.00', expected_close_date: opp.expected_close_date || '', source: opp.source || '', notes: opp.notes || '' })
        setIsOppEdit(true); setSelectedOppId(opp.id); setShowOppModal(true)
    }
    const handleOppSubmit = async (e) => {
        e.preventDefault()
        try {
            const payload = { ...oppForm, probability: Number(oppForm.probability), expected_value: oppForm.expected_value || '0.00', customer_id: oppForm.customer_id ? Number(oppForm.customer_id) : null }
            if (isOppEdit) { await crmAPI.updateOpportunity(selectedOppId, payload) } else { await crmAPI.createOpportunity(payload) }
            setShowOppModal(false); fetchOpportunities()
        } catch (err) { showToast(err.response?.data?.detail || t('crm.save_error', 'error')) }
    }
    const handleDeleteOpp = async (id) => {
        try { await crmAPI.deleteOpportunity(id); setDeleteOppConfirm(null); fetchOpportunities() }
        catch (err) { showToast(err.response?.data?.detail || t('crm.delete_error', 'error')) }
    }
    const getStageLabel = (stage) => { const opt = stageOptions.find(s => s.value === stage); return opt ? opt.label : stage }

    // ── Ticket handlers ─────────────────────────────────────────────────────
    const openCreateTicket = () => { setTicketForm({ ...emptyTicketForm }); setShowTicketModal(true) }
    const handleTicketSubmit = async (e) => {
        e.preventDefault()
        try {
            const payload = { ...ticketForm, customer_id: ticketForm.customer_id ? Number(ticketForm.customer_id) : null, sla_hours: Number(ticketForm.sla_hours) }
            await crmAPI.createTicket(payload); setShowTicketModal(false); fetchTickets()
        } catch (err) { showToast(err.response?.data?.detail || t('crm.create_error', 'error')) }
    }
    const toggleExpand = async (ticketId) => {
        if (expandedId === ticketId) { setExpandedId(null); setTicketDetail(null); return }
        try { setExpandedId(ticketId); setDetailLoading(true); const res = await crmAPI.getTicket(ticketId); setTicketDetail(res.data); setCommentText(''); setIsInternal(false) }
        catch (err) { console.error(err) } finally { setDetailLoading(false) }
    }
    const handleStatusChange = async (ticketId, newStatus) => {
        try {
            await crmAPI.updateTicket(ticketId, { status: newStatus }); fetchTickets()
            if (expandedId === ticketId) { const res = await crmAPI.getTicket(ticketId); setTicketDetail(res.data) }
        } catch (err) { console.error(err) }
    }
    const handleAddComment = async (e) => {
        e.preventDefault()
        if (!commentText.trim()) return
        try { await crmAPI.addComment(expandedId, { comment: commentText, is_internal: isInternal }); const res = await crmAPI.getTicket(expandedId); setTicketDetail(res.data); setCommentText(''); setIsInternal(false) }
        catch (err) { showToast(err.response?.data?.detail || t('crm.comment_error', 'error')) }
    }
    const getStatusLabel = (status) => { const opt = statusOptions.find(s => s.value === status); return opt ? opt.label : status }
    const getPriorityLabel = (priority) => { const opt = priorityOptions.find(p => p.value === priority); return opt ? opt.label : priority }
    const formatDate = (dateStr) => { if (!dateStr) return '-'; try { return formatShortDate(dateStr) } catch { return dateStr } }

    // ── Render ──────────────────────────────────────────────────────────────
    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <h1 className="workspace-title">{t('crm.title')}</h1>
                <p className="workspace-subtitle">{t('crm.subtitle')}</p>
            </div>

            {/* Metrics Grid at the very top */}
            <div className="metrics-grid">
                <div className="metric-card" style={{ borderLeft: '4px solid #3b82f6' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>📊</span> {t('crm.total_opportunities', 'إجمالي الفرص')}
                    </div>
                    <div className="metric-value text-primary">{overviewLoading ? '...' : dashboardData?.kpis?.total_opportunities || 0}</div>
                </div>
                <div className="metric-card" style={{ borderLeft: '4px solid #22c55e' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>💰</span> {t('crm.pipeline_value', 'قيمة خط الأنابيب')}
                    </div>
                    <div className="metric-value text-success">{overviewLoading ? '...' : formatNumber(dashboardData?.kpis?.pipeline_value || 0)} <small>{currency}</small></div>
                </div>
                <div className="metric-card" style={{ borderLeft: '4px solid #f97316' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>🎫</span> {t('crm.open_tickets', 'التذاكر المفتوحة')}
                    </div>
                    <div className="metric-value text-warning">{overviewLoading ? '...' : dashboardData?.tickets?.open_tickets || 0}</div>
                </div>
                <div className="metric-card" style={{ borderLeft: '4px solid #ef4444' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>🔥</span> {t('crm.critical_tickets', 'تذاكر حرجة')}
                    </div>
                    <div className="metric-value text-danger">{overviewLoading ? '...' : dashboardData?.tickets?.critical_tickets || 0}</div>
                </div>
                <div className="metric-card" style={{ borderLeft: '4px solid #8b5cf6' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>📣</span> {t('crm.active_campaigns', 'الحملات النشطة')}
                    </div>
                    <div className="metric-value" style={{ color: '#8b5cf6' }}>{overviewLoading ? '...' : dashboardData?.campaigns?.active || 0}</div>
                </div>
                <div className="metric-card" style={{ borderLeft: '4px solid #10b981' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>🏆</span> {t('crm.win_rate', 'معدل الفوز')}
                    </div>
                    <div className="metric-value text-success">{overviewLoading ? '...' : `${dashboardData?.kpis?.win_rate || 0}%`}</div>
                </div>
                <div className="metric-card" style={{ borderLeft: '4px solid #0ea5e9' }}>
                    <div className="metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '16px' }}>🤝</span> {t('crm.avg_deal_size', 'متوسط حجم الصفقة')}
                    </div>
                    <div className="metric-value text-info">{overviewLoading ? '...' : formatNumber(dashboardData?.kpis?.avg_deal_size || 0)} <small>{currency}</small></div>
                </div>
            </div>

            {/* Apps / Modules Row */}
            <style>{`
                .crm-module-card { transition: all 0.2s ease-in-out; border: 1px solid var(--border-color, #e5e7eb); border-radius: 12px; background: var(--bg-primary, #fff); }
                .crm-module-card:hover { transform: translateY(-3px); box-shadow: 0 4px 12px rgba(0,0,0,0.06); border-color: var(--primary, #0d6efd); }
            `}</style>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: '16px', marginTop: '20px', marginBottom: '16px' }}>
                <Link to="/crm/lead-scoring" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                    <div style={{ fontSize: '28px' }}>⭐</div>
                    <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.lead_scoring', 'التقييم')}</div>
                </Link>
                <Link to="/crm/segments" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                    <div style={{ fontSize: '28px' }}>👥</div>
                    <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.customer_segments', 'الشرائح')}</div>
                </Link>
                <Link to="/crm/analytics" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                    <div style={{ fontSize: '28px' }}>📈</div>
                    <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.analytics', 'التحليلات')}</div>
                </Link>
                <Link to="/crm/contacts" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                    <div style={{ fontSize: '28px' }}>📇</div>
                    <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.contacts', 'جهات الاتصال')}</div>
                </Link>
                <Link to="/crm/forecasts" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                    <div style={{ fontSize: '28px' }}>🔮</div>
                    <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.sales_forecasts', 'التنبؤات')}</div>
                </Link>

                {getIndustryFeature('crm.campaigns') && hasPermission('crm.campaign_view') && (
                    <Link to="/crm/campaigns" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                        <div style={{ fontSize: '28px' }}>📣</div>
                        <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.campaigns.title', 'الحملات')}</div>
                    </Link>
                )}

                {getIndustryFeature('crm.knowledge_base') && (
                    <Link to="/crm/knowledge-base" className="crm-module-card" style={{ padding: '20px 12px', textAlign: 'center', textDecoration: 'none', color: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                        <div style={{ fontSize: '28px' }}>📚</div>
                        <div style={{ fontSize: '13px', fontWeight: '600' }}>{t('crm.knowledge_base.title', 'المعرفة')}</div>
                    </Link>
                )}
            </div>

            {/* Tabs */}
            <div className="tabs mt-4">
                {['overview', 'opportunities', 'tickets'].map(tab => (
                    <button
                        key={tab}
                        className={`tab ${activeTab === tab ? 'active' : ''}`}
                        onClick={() => setActiveTab(tab)}
                    >
                        {tab === 'overview' && t('crm.tab_overview', 'نظرة عامة')}
                        {tab === 'opportunities' && t('crm.tab_opportunities', 'الفرص')}
                        {tab === 'tickets' && t('crm.tab_tickets', 'تذاكر الدعم')}
                    </button>
                ))}
            </div>



            {/* ── Overview Tab ───────────────────────────────────────────────── */}
            {activeTab === 'overview' && (
                <div className="mt-4">
                    {overviewLoading ? (
                        <PageLoading />
                    ) : dashboardData ? (
                        <>

                            <div className="crm-dashboard-summary" style={{ display: 'block', marginTop: '24px' }}>
                                <div>
                                    {/* Pipeline by Stage */}
                                    {dashboardData.pipeline_by_stage && dashboardData.pipeline_by_stage.length > 0 && (
                                        <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
                                            <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--border-color, #e5e7eb)', background: 'var(--bg-secondary, #fafafa)' }}>
                                                <h3 className="section-title" style={{ margin: 0, fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    <span style={{ color: '#3b82f6' }}>📈</span> {t('crm.pipeline_by_stage', 'خط الأنابيب حسب المرحلة')}
                                                </h3>
                                            </div>
                                            <div className="data-table-container" style={{ margin: 0, border: 'none', borderRadius: 0 }}>
                                                <table className="data-table">
                                                    <thead>
                                                        <tr>
                                                            <th style={{ paddingLeft: '24px' }}>{t('common.stage', 'المرحلة')}</th>
                                                            <th style={{ textAlign: 'center' }}>{t('common.count', 'العدد')}</th>
                                                            <th style={{ textAlign: 'left', paddingRight: '24px' }}>{t('common.value', 'القيمة')}</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {dashboardData.pipeline_by_stage.map((s, i) => (
                                                            <tr key={i}>
                                                                <td style={{ paddingLeft: '24px' }}>
                                                                    <span className={`badge ${s.stage === 'won' ? 'badge-success' : s.stage === 'lost' ? 'badge-danger' : 'badge-primary'}`} style={{ padding: '6px 12px', fontSize: '0.85rem' }}>
                                                                        {t(`crm.stage_${s.stage}`, s.stage)}
                                                                    </span>
                                                                </td>
                                                                <td style={{ textAlign: 'center', fontWeight: 'bold' }}>{s.count}</td>
                                                                <td style={{ textAlign: 'left', paddingRight: '24px', fontWeight: 'bold', color: 'var(--text-main)' }}>
                                                                    {formatNumber(s.total_value)} <span style={{ fontSize: '0.8em', color: 'var(--text-muted)' }}>{currency}</span>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* Lead Score Distribution */}
                                {dashboardData.lead_score_distribution && dashboardData.lead_score_distribution.length > 0 && (
                                    <div className="card" style={{ padding: '24px', marginTop: '24px' }}>
                                        <h3 className="section-title" style={{ marginBottom: '20px', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <span style={{ color: '#eab308' }}>⭐</span> {t('crm.lead_score_distribution', 'توزيع التقييم للعملاء المحتملين')}
                                        </h3>
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
                                            {dashboardData.lead_score_distribution.map((d, i) => {
                                                const color = d.grade === 'A' ? '#22c55e' : d.grade === 'B' ? '#3b82f6' : d.grade === 'C' ? '#f97316' : '#ef4444'
                                                const percentage = Math.max(4, Math.min(100, (d.count / Math.max(...dashboardData.lead_score_distribution.map(x => x.count || 0), 1)) * 100))

                                                return (
                                                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                                        <div style={{
                                                            width: '40px', height: '40px', borderRadius: '10px',
                                                            background: `${color}15`, color: color,
                                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                            fontWeight: 'bold', fontSize: '1.1rem'
                                                        }}>
                                                            {d.grade}
                                                        </div>
                                                        <div style={{ flex: 1 }}>
                                                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '0.85rem', fontWeight: '600' }}>
                                                                <span>{t(`crm.grade_title_${d.grade}`, `تصنيف ${d.grade}`)}</span>
                                                                <span style={{ color: 'var(--text-main)' }}>{d.count}</span>
                                                            </div>
                                                            <div style={{ height: '8px', borderRadius: '4px', background: 'var(--bg-hover)', overflow: 'hidden' }}>
                                                                <div style={{
                                                                    width: `${percentage}%`, height: '100%',
                                                                    background: color, borderRadius: '4px',
                                                                    transition: 'width 1s cubic-bezier(0.4, 0, 0.2, 1)'
                                                                }} />
                                                            </div>
                                                        </div>
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="empty-state">{t('common.no_data')}</div>
                    )}
                </div>
            )}

            {/* ── Opportunities Tab ───────────────────────────────────────────── */}
            {activeTab === 'opportunities' && (
                <div className="mt-4">
                    <div className="card">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <h3 className="section-title" style={{ margin: 0 }}>{t('crm.tab_opportunities')}</h3>
                                <select className="form-input" style={{ width: '180px' }} value={filterStage} onChange={e => setFilterStage(e.target.value)}>
                                    <option value="">{t('crm.all_stages')}</option>
                                    {stageOptions.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                                </select>
                            </div>
                            <button className="btn btn-primary btn-sm" onClick={openCreateOpp}>+ {t('crm.new_opportunity')}</button>
                        </div>

                        {oppLoading ? (
                            <PageLoading />
                        ) : opportunities.length === 0 ? (
                            <div className="empty-state">{t('crm.no_opportunities')}</div>
                        ) : (
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('crm.title_label')}</th>
                                            <th>{t('common.customer')}</th>
                                            <th>{t('crm.stage')}</th>
                                            <th>{t('crm.probability')}</th>
                                            <th>{t('crm.expected_value')}</th>
                                            <th>{t('crm.expected_close')}</th>
                                            <th>{t('crm.responsible')}</th>
                                            <th>{t('common.actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {opportunities.map(opp => (
                                            <tr key={opp.id}>
                                                <td>{opp.title}</td>
                                                <td>{opp.customer_name || '-'}</td>
                                                <td><span className="badge" style={stageBadgeColors[opp.stage] || {}}>{getStageLabel(opp.stage)}</span></td>
                                                <td>{opp.probability}%</td>
                                                <td>{formatNumber(opp.expected_value)} {currency}</td>
                                                <td>{opp.expected_close_date || '-'}</td>
                                                <td>{opp.assigned_name || '-'}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: 6 }}>
                                                        <button className="btn btn-secondary btn-sm" onClick={() => openEditOpp(opp)}>{t('crm.edit')}</button>
                                                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteOppConfirm(opp.id)}>{t('common.delete')}</button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {deleteOppConfirm && (
                            <div className="modal-backdrop" onClick={() => setDeleteOppConfirm(null)}>
                                <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
                                    <div className="modal-header"><h3>{t('crm.confirm_delete')}</h3></div>
                                    <div className="modal-body"><p>{t('crm.confirm_delete_opportunity')}</p></div>
                                    <div className="modal-footer">
                                        <button className="btn btn-danger" onClick={() => handleDeleteOpp(deleteOppConfirm)}>{t('common.delete')}</button>
                                        <button className="btn btn-secondary" onClick={() => setDeleteOppConfirm(null)}>{t('common.cancel')}</button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {showOppModal && (
                            <div className="modal-overlay" onClick={() => setShowOppModal(false)}>
                                <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
                                    <div className="modal-header">
                                        <h2 className="modal-title">{isOppEdit ? t('crm.edit_opportunity') : t('crm.new_opportunity')}</h2>
                                        <button type="button" className="btn-icon" onClick={() => setShowOppModal(false)}>✕</button>
                                    </div>
                                    <div className="modal-body">
                                        <form id="opp-form" onSubmit={handleOppSubmit}>
                                            <div className="form-section">
                                                <div className="form-grid">
                                                    <div className="form-group">
                                                        <label className="form-label">{t('crm.title_label')}</label>
                                                        <input type="text" className="form-input" value={oppForm.title} onChange={e => setOppForm(p => ({ ...p, title: e.target.value }))} required />
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">{t('common.customer')}</label>
                                                        <select className="form-select" value={oppForm.customer_id} onChange={e => setOppForm(p => ({ ...p, customer_id: e.target.value }))}>
                                                            <option value="">{t('crm.select_customer')}</option>
                                                            {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                                        </select>
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">{t('crm.stage')}</label>
                                                        <select className="form-select" value={oppForm.stage} onChange={e => setOppForm(p => ({ ...p, stage: e.target.value }))} required>
                                                            {stageOptions.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                                                        </select>
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">{t('crm.probability')} (%)</label>
                                                        <input type="number" className="form-input" min="0" max="100" value={oppForm.probability} onChange={e => setOppForm(p => ({ ...p, probability: e.target.value }))} />
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">{t('crm.expected_value')}</label>
                                                        <input type="number" className="form-input" min="0" step="0.01" value={oppForm.expected_value} onChange={e => setOppForm(p => ({ ...p, expected_value: e.target.value }))} />
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">{t('crm.expected_close')}</label>
                                                        <DateInput className="form-input" value={oppForm.expected_close_date} onChange={e => setOppForm(p => ({ ...p, expected_close_date: e.target.value }))} />
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">{t('crm.source')}</label>
                                                        <input type="text" className="form-input" value={oppForm.source} onChange={e => setOppForm(p => ({ ...p, source: e.target.value }))} />
                                                    </div>
                                                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                                        <label className="form-label">{t('common.notes')}</label>
                                                        <textarea className="form-input" rows={3} value={oppForm.notes} onChange={e => setOppForm(p => ({ ...p, notes: e.target.value }))} />
                                                    </div>
                                                </div>
                                            </div>
                                        </form>
                                    </div>
                                    <div className="modal-footer">
                                        <button type="submit" form="opp-form" className="btn btn-primary">{isOppEdit ? t('common.update') : t('common.create')}</button>
                                        <button type="button" className="btn btn-secondary" onClick={() => setShowOppModal(false)}>{t('common.cancel')}</button>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* ── Support Tickets Tab ─────────────────────────────────────────── */}
            {activeTab === 'tickets' && (
                <div className="card mt-4">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <h3 className="section-title" style={{ margin: 0 }}>{t('crm.tab_tickets')}</h3>
                            <select className="form-input" style={{ width: '160px' }} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                                <option value="">{t('common.all_statuses')}</option>
                                {statusOptions.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                            </select>
                            <select className="form-input" style={{ width: '150px' }} value={filterPriority} onChange={e => setFilterPriority(e.target.value)}>
                                <option value="">{t('crm.all_priorities')}</option>
                                {priorityOptions.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                            </select>
                        </div>
                        <button className="btn btn-primary btn-sm" onClick={openCreateTicket}>+ {t('crm.new_ticket')}</button>
                    </div>

                    {ticketsLoading ? (
                        <PageLoading />
                    ) : tickets.length === 0 ? (
                        <div className="empty-state">{t('crm.no_tickets')}</div>
                    ) : (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('crm.ticket_number')}</th>
                                        <th>{t('crm.subject')}</th>
                                        <th>{t('common.customer')}</th>
                                        <th>{t('common.status_title')}</th>
                                        <th>{t('crm.priority')}</th>
                                        <th>{t('crm.responsible')}</th>
                                        <th>{t('crm.created_date')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {tickets.map(ticket => (
                                        <React.Fragment key={ticket.id}>
                                            <tr onClick={() => toggleExpand(ticket.id)} style={{ cursor: 'pointer' }}>
                                                <td>{ticket.ticket_number}</td>
                                                <td>{ticket.subject}</td>
                                                <td>{ticket.customer_name || '-'}</td>
                                                <td><span className="badge" style={statusBadgeStyles[ticket.status] || {}}>{getStatusLabel(ticket.status)}</span></td>
                                                <td><span className="badge" style={priorityBadgeStyles[ticket.priority] || {}}>{getPriorityLabel(ticket.priority)}</span></td>
                                                <td>{ticket.assigned_name || '-'}</td>
                                                <td>{formatDate(ticket.created_at)}</td>
                                            </tr>
                                            {expandedId === ticket.id && (
                                                <tr>
                                                    <td colSpan={7} style={{ padding: 0 }}>
                                                        <div style={detailPanelStyle}>
                                                            {detailLoading ? (
                                                                <div style={{ padding: 20, textAlign: 'center' }}>{t('common.loading')}</div>
                                                            ) : ticketDetail ? (
                                                                <>
                                                                    <div style={{ marginBottom: 16 }}>
                                                                        <h4 style={{ marginBottom: 8 }}>{t('crm.ticket_details')}</h4>
                                                                        <p><strong>{t('common.description')}:</strong> {ticketDetail.description || t('crm.no_description')}</p>
                                                                        <p><strong>{t('crm.category')}:</strong> {ticketDetail.category || '-'}</p>
                                                                        <p><strong>{t('crm.sla_hours')}:</strong> {ticketDetail.sla_hours || '-'}</p>
                                                                        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                                                                            <span>{t('crm.change_status')}:</span>
                                                                            {statusOptions.map(s => (
                                                                                <button
                                                                                    key={s.value}
                                                                                    className={`btn ${ticketDetail.status === s.value ? 'btn-primary' : 'btn-secondary'}`}
                                                                                    style={{ fontSize: 12, padding: '4px 10px' }}
                                                                                    onClick={e => { e.stopPropagation(); handleStatusChange(ticket.id, s.value) }}
                                                                                >{s.label}</button>
                                                                            ))}
                                                                        </div>
                                                                    </div>
                                                                    <div style={{ borderTop: '1px solid var(--border-color,#e5e7eb)', paddingTop: 12 }}>
                                                                        <h4 style={{ marginBottom: 8 }}>{t('crm.comments')} ({(ticketDetail.comments || []).length})</h4>
                                                                        {(ticketDetail.comments || []).length === 0 ? (
                                                                            <p style={{ color: '#9ca3af' }}>{t('crm.no_comments')}</p>
                                                                        ) : (
                                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                                                                                {ticketDetail.comments.map((comment, idx) => (
                                                                                    <div key={idx} style={commentStyle(comment.is_internal)}>
                                                                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                                                                                            <strong>{comment.author_name || t('crm.user')}</strong>
                                                                                            <span style={{ fontSize: 12, color: '#9ca3af' }}>
                                                                                                {formatDate(comment.created_at)}
                                                                                                {comment.is_internal && <span className="badge badge-warning" style={{ marginRight: 6, fontSize: 10 }}>{t('crm.internal')}</span>}
                                                                                            </span>
                                                                                        </div>
                                                                                        <p style={{ margin: 0 }}>{comment.comment}</p>
                                                                                    </div>
                                                                                ))}
                                                                            </div>
                                                                        )}
                                                                        <form onSubmit={handleAddComment} style={{ marginTop: 8 }}>
                                                                            <div className="form-group">
                                                                                <textarea className="form-input" rows={3} placeholder={t('crm.add_comment_placeholder')} value={commentText} onChange={e => setCommentText(e.target.value)} required style={{ width: '100%' }} />
                                                                            </div>
                                                                            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
                                                                                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                                                                                    <input type="checkbox" checked={isInternal} onChange={e => setIsInternal(e.target.checked)} />
                                                                                    {t('crm.internal_comment')}
                                                                                </label>
                                                                                <button type="submit" className="btn btn-primary" style={{ fontSize: 13, padding: '6px 16px' }}>{t('common.submit')}</button>
                                                                            </div>
                                                                        </form>
                                                                    </div>
                                                                </>
                                                            ) : null}
                                                        </div>
                                                    </td>
                                                </tr>
                                            )}
                                        </React.Fragment>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {showTicketModal && (
                        <div className="modal-overlay" onClick={() => setShowTicketModal(false)}>
                            <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
                                <div className="modal-header">
                                    <h2 className="modal-title">{t('crm.new_ticket')}</h2>
                                    <button type="button" className="btn-icon" onClick={() => setShowTicketModal(false)}>✕</button>
                                </div>
                                <div className="modal-body">
                                    <form id="ticket-form" onSubmit={handleTicketSubmit}>
                                        <div className="form-section">
                                            <div className="form-grid">
                                                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                                    <label className="form-label">{t('crm.subject')}</label>
                                                    <input type="text" className="form-input" value={ticketForm.subject} onChange={e => setTicketForm(p => ({ ...p, subject: e.target.value }))} required />
                                                </div>
                                                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                                    <label className="form-label">{t('common.description')}</label>
                                                    <textarea className="form-input" rows={4} value={ticketForm.description} onChange={e => setTicketForm(p => ({ ...p, description: e.target.value }))} />
                                                </div>
                                                <div className="form-group">
                                                    <label className="form-label">{t('common.customer')}</label>
                                                    <select className="form-select" value={ticketForm.customer_id} onChange={e => setTicketForm(p => ({ ...p, customer_id: e.target.value }))}>
                                                        <option value="">{t('crm.select_customer')}</option>
                                                        {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                                    </select>
                                                </div>
                                                <div className="form-group">
                                                    <label className="form-label">{t('crm.priority')}</label>
                                                    <select className="form-select" value={ticketForm.priority} onChange={e => setTicketForm(p => ({ ...p, priority: e.target.value }))} required>
                                                        {priorityOptions.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                                                    </select>
                                                </div>
                                                <div className="form-group">
                                                    <label className="form-label">{t('crm.category')}</label>
                                                    <input type="text" className="form-input" value={ticketForm.category} onChange={e => setTicketForm(p => ({ ...p, category: e.target.value }))} />
                                                </div>
                                                <div className="form-group">
                                                    <label className="form-label">{t('crm.sla_hours')}</label>
                                                    <input type="number" className="form-input" min="1" value={ticketForm.sla_hours} onChange={e => setTicketForm(p => ({ ...p, sla_hours: e.target.value }))} />
                                                </div>
                                            </div>
                                        </div>
                                    </form>
                                </div>
                                <div className="modal-footer">
                                    <button type="submit" form="ticket-form" className="btn btn-primary">{t('common.create')}</button>
                                    <button type="button" className="btn btn-secondary" onClick={() => setShowTicketModal(false)}>{t('common.cancel')}</button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default CRMHome
