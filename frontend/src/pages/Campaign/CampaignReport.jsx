import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { crmAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { formatShortDate } from '../../utils/dateUtils';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';
import { PageLoading } from '../../components/common/LoadingStates'

const STATUS_CLASSES = {
    draft: 'status-pending',
    scheduled: 'status-partial',
    executing: 'status-partial',
    completed: 'status-completed',
    cancelled: 'status-danger',
};

const DELIVERY_CLASSES = {
    pending: 'status-pending',
    sent: 'status-partial',
    delivered: 'status-completed',
    bounced: 'status-danger',
    failed: 'status-danger',
};

function MetricBar({ label, value, rate, color }) {
    const rateValue = rate || '0.0000';
    return (
        <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, color: '#64748b' }}>{label}</span>
                <span style={{ fontSize: 13, fontWeight: 600 }}>
                    {formatNumber(value)} ({formatNumber(rateValue)}%)
                </span>
            </div>
            <div style={{ height: 8, background: '#e2e8f0', borderRadius: 4 }}>
                <div style={{ height: '100%', width: `${rateValue}%`, background: color, borderRadius: 4, transition: 'width 0.4s' }} />
            </div>
        </div>
    );
}

export default function CampaignReport() {
    const { id } = useParams();
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [campaign, setCampaign] = useState(null);
    const [recipients, setRecipients] = useState([]);
    const [leads, setLeads] = useState([]);
    const [loading, setLoading] = useState(true);
    const [recipientFilter, setRecipientFilter] = useState('');
    const [executing, setExecuting] = useState(false);
    const [attributeLeadId, setAttributeLeadId] = useState('');
    const [showAttributeModal, setShowAttributeModal] = useState(false);
    const [opportunities, setOpportunities] = useState([]);
    const [opportunitySearch, setOpportunitySearch] = useState('');

    useEffect(() => { fetchAll(); }, [id]);

    const fetchAll = async () => {
        setLoading(true);
        try {
            const [campRes, recipRes, metricsRes] = await Promise.all([
                crmAPI.getCampaign(id),
                crmAPI.getCampaignRecipients(id, { limit: 100 }),
                crmAPI.getCampaignMetrics(id),
            ]);
            setCampaign({ ...campRes.data, ...metricsRes.data });
            setRecipients(recipRes.data?.recipients || []);
            setLeads(metricsRes.data?.attributed_leads || []);
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleExecute = async () => {
        if (!window.confirm(t('campaign.confirm_execute'))) return;
        setExecuting(true);
        try {
            const res = await crmAPI.executeCampaign(id);
            showToast(t('campaign.executed_success', `Sent to ${res.data?.total_recipients || 0} recipients`), 'success');
            fetchAll();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setExecuting(false);
        }
    };

    const fetchOpportunities = async () => {
        try {
            const res = await crmAPI.listOpportunities({ limit: 200 });
            setOpportunities(res.data || []);
        } catch (err) {
            console.error('Failed to fetch opportunities', err);
        }
    };

    const handleAttributeLead = async () => {
        if (!attributeLeadId) return;
        try {
            await crmAPI.attributeLead(id, parseInt(attributeLeadId));
            showToast(t('campaign.lead_attributed', 'Lead attributed'), 'success');
            setShowAttributeModal(false);
            setAttributeLeadId('');
            setOpportunitySearch('');
            fetchAll();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        }
    };

    if (loading) return <div className="workspace"><PageLoading /></div>;
    if (!campaign) return <div className="workspace"><div className="empty-state">{t('campaign.not_found', 'Campaign not found')}</div></div>;

    const filteredRecipients = recipientFilter
        ? recipients.filter(r => r.delivery_status === recipientFilter)
        : recipients;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{campaign.name}</h1>
                    <p className="workspace-subtitle">
                        <span className={`status-badge ${STATUS_CLASSES[campaign.status] || ''}`}>
                            {t(`campaign.status_${campaign.status}`, campaign.status)}
                        </span>
                        {campaign.segment_name && (
                            <span style={{ marginLeft: 8, fontSize: 13, color: '#64748b' }}>
                                {t('campaign.segment', 'Segment')}: {campaign.segment_name}
                            </span>
                        )}
                    </p>
                </div>
                <div className="header-actions">
                    {['draft', 'scheduled'].includes(campaign.status) && (
                        <button className="btn btn-primary" onClick={handleExecute} disabled={executing}>
                            {executing ? t('common.loading') : t('campaign.execute', 'Execute Campaign')}
                        </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => { setShowAttributeModal(true); fetchOpportunities(); }}>
                        {t('campaign.attribute_lead', 'Attribute Lead')}
                    </button>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="metrics-grid" style={{ marginBottom: 24 }}>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.sent', 'Sent')}</div>
                    <div className="metric-value text-primary">{formatNumber(campaign.total_sent || 0)}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.delivered', 'Delivered')}</div>
                    <div className="metric-value text-success">{formatNumber(campaign.total_delivered || 0)}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{campaign.delivery_rate || 0}%</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.opened', 'Opened')}</div>
                    <div className="metric-value text-info">{formatNumber(campaign.total_opened || 0)}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{campaign.open_rate || 0}%</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.clicked', 'Clicked')}</div>
                    <div className="metric-value text-warning">{formatNumber(campaign.total_clicked || 0)}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{campaign.click_rate || 0}%</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.responded', 'Responded')}</div>
                    <div className="metric-value" style={{ color: '#7c3aed' }}>{formatNumber(campaign.total_responded || 0)}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{campaign.response_rate || 0}%</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.cost_per_lead', 'Cost / Lead')}</div>
                    <div className="metric-value" style={{ color: '#dc2626' }}>
                        {campaign.cost_per_lead ? formatNumber(campaign.cost_per_lead) : '-'}
                    </div>
                </div>
            </div>

            {/* Engagement Funnel */}
            <div className="card section-card" style={{ marginBottom: 24, padding: 20 }}>
                <h3 className="section-title">{t('campaign.funnel', 'Engagement Funnel')}</h3>
                <MetricBar label={t('campaign.delivered', 'Delivered')} value={campaign.total_delivered || 0} rate={campaign.delivery_rate} color="#22c55e" />
                <MetricBar label={t('campaign.opened', 'Opened')} value={campaign.total_opened || 0} rate={campaign.open_rate} color="#3b82f6" />
                <MetricBar label={t('campaign.clicked', 'Clicked')} value={campaign.total_clicked || 0} rate={campaign.click_rate} color="#f59e0b" />
                <MetricBar label={t('campaign.responded', 'Responded')} value={campaign.total_responded || 0} rate={campaign.response_rate} color="#7c3aed" />
            </div>

            {/* Cost Summary */}
            <div className="card section-card" style={{ marginBottom: 24, padding: 20 }}>
                <h3 className="section-title">{t('campaign.costs', 'Cost Tracking')}</h3>
                <div className="form-grid">
                    <div>
                        <span className="form-label">{t('campaign.estimated_cost', 'Estimated Cost')}</span>
                        <p style={{ fontWeight: 600 }}>{campaign.estimated_cost ? formatNumber(campaign.estimated_cost) : '-'}</p>
                    </div>
                    <div>
                        <span className="form-label">{t('campaign.actual_cost', 'Actual Cost')}</span>
                        <p style={{ fontWeight: 600 }}>{campaign.actual_cost ? formatNumber(campaign.actual_cost) : '-'}</p>
                    </div>
                    <div>
                        <span className="form-label">{t('campaign.attributed_leads_count', 'Attributed Leads')}</span>
                        <p style={{ fontWeight: 600 }}>{campaign.total_attributed_leads || 0}</p>
                    </div>
                    <div>
                        <span className="form-label">{t('campaign.cost_per_lead', 'Cost / Lead')}</span>
                        <p style={{ fontWeight: 600, color: '#dc2626' }}>
                            {campaign.cost_per_lead ? formatNumber(campaign.cost_per_lead) : '-'}
                        </p>
                    </div>
                </div>
            </div>

            {/* Attributed Leads */}
            {leads.length > 0 && (
                <div className="card section-card" style={{ marginBottom: 24 }}>
                    <div className="card-header">
                        <h3 className="section-title">{t('campaign.attributed_leads', 'Attributed Leads')} ({leads.length})</h3>
                    </div>
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('crm.opportunity', 'Opportunity')}</th>
                                    <th>{t('crm.stage', 'Stage')}</th>
                                    <th>{t('crm.value', 'Value')}</th>
                                    <th>{t('campaign.attributed_at', 'Attributed At')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {leads.map(l => (
                                    <tr key={l.id}>
                                        <td>{l.lead_title}</td>
                                        <td>{l.stage}</td>
                                        <td>{l.expected_value ? formatNumber(l.expected_value) : '-'}</td>
                                        <td>{l.attributed_at ? formatShortDate(l.attributed_at) : '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Recipients Table */}
            <div className="card section-card">
                <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px' }}>
                    <h3 className="section-title" style={{ margin: 0 }}>{t('campaign.recipients', 'Recipients')} ({recipients.length})</h3>
                    <select className="form-input" style={{ maxWidth: 160 }}
                        value={recipientFilter} onChange={e => setRecipientFilter(e.target.value)}>
                        <option value="">{t('common.all_statuses', 'All')}</option>
                        {['pending', 'sent', 'delivered', 'bounced', 'failed'].map(s =>
                            <option key={s} value={s}>{t(`campaign.delivery_${s}`, s)}</option>)}
                    </select>
                </div>
                {filteredRecipients.length === 0
                    ? <div className="empty-state" style={{ padding: 24 }}>{t('campaign.no_recipients', 'No recipients yet')}</div>
                    : (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('common.name', 'Name')}</th>
                                        <th>{t('common.email', 'Email')}</th>
                                        <th>{t('campaign.channel', 'Channel')}</th>
                                        <th>{t('campaign.delivery_status', 'Status')}</th>
                                        <th>{t('campaign.opened', 'Opened')}</th>
                                        <th>{t('campaign.clicked', 'Clicked')}</th>
                                        <th>{t('campaign.responded', 'Responded')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredRecipients.map(r => (
                                        <tr key={r.id}>
                                            <td>{r.contact_name}</td>
                                            <td>{r.contact_email || '-'}</td>
                                            <td>{r.channel}</td>
                                            <td>
                                                <span className={`status-badge ${DELIVERY_CLASSES[r.delivery_status] || ''}`}>
                                                    {t(`campaign.delivery_${r.delivery_status}`, r.delivery_status)}
                                                </span>
                                            </td>
                                            <td>{r.opened_at ? formatShortDate(r.opened_at) : '-'}</td>
                                            <td>{r.clicked_at ? formatShortDate(r.clicked_at) : '-'}</td>
                                            <td>{r.responded_at ? formatShortDate(r.responded_at) : '-'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
            </div>

            {showAttributeModal && (
                <div className="modal-overlay" onClick={() => { setShowAttributeModal(false); setOpportunitySearch(''); }}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
                        <div className="modal-header">
                            <h3>{t('campaign.attribute_lead', 'Attribute Lead to Campaign')}</h3>
                        </div>
                        <div className="modal-body">
                            <div className="form-group">
                                <label className="form-label">{t('crm.opportunity', 'Lead / Opportunity')}</label>
                                <input
                                    className="form-input"
                                    placeholder={t('common.search', 'بحث باسم الفرصة...')}
                                    value={opportunitySearch}
                                    onChange={e => setOpportunitySearch(e.target.value)}
                                    style={{ marginBottom: 4 }}
                                />
                                {opportunities.length === 0 ? (
                                    <p style={{ fontSize: 12, color: '#9ca3af', margin: '4px 0 0' }}>
                                        {t('common.loading', 'جارٍ التحميل...')}
                                    </p>
                                ) : (
                                    <select
                                        className="form-input"
                                        value={attributeLeadId}
                                        onChange={e => setAttributeLeadId(e.target.value)}
                                    >
                                        <option value="">{t('crm.select_opportunity', '-- اختر الفرصة --')}</option>
                                        {opportunities
                                            .filter(o => !opportunitySearch ||
                                                (o.title || '').toLowerCase().includes(opportunitySearch.toLowerCase()) ||
                                                (o.customer_name || '').toLowerCase().includes(opportunitySearch.toLowerCase()))
                                            .map(o => (
                                                <option key={o.id} value={o.id}>
                                                    {o.title}{o.customer_name ? ` — ${o.customer_name}` : ''}
                                                </option>
                                            ))}
                                    </select>
                                )}
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-primary" onClick={handleAttributeLead}
                                disabled={!attributeLeadId}>
                                {t('campaign.attribute', 'Attribute')}
                            </button>
                            <button className="btn btn-secondary" onClick={() => { setShowAttributeModal(false); setOpportunitySearch(''); }}>
                                {t('common.cancel', 'Cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
