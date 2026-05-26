import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
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

const TYPE_STYLES = {
    email: { background: '#dbeafe', color: '#1d4ed8' },
    sms: { background: '#dcfce7', color: '#16a34a' },
    both: { background: '#fce7f3', color: '#db2777' },
};

export default function CampaignList() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const [campaigns, setCampaigns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filterStatus, setFilterStatus] = useState('');
    const [filterType, setFilterType] = useState('');
    const [executing, setExecuting] = useState(null);
    const [summary, setSummary] = useState({
        total_campaigns: 0,
        active_or_scheduled_campaigns: 0,
        total_sent: 0,
        total_opened: 0,
        total_clicked: 0,
    });

    useEffect(() => { fetchData(); }, [filterStatus, filterType]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const params = {};
            if (filterStatus) params.status = filterStatus;
            if (filterType) params.campaign_type = filterType;
            const [listRes, summaryRes] = await Promise.all([
                crmAPI.listCampaigns(params),
                crmAPI.getCampaignSummary(params),
            ]);
            setCampaigns(listRes.data || []);
            setSummary(summaryRes.data || {
                total_campaigns: 0,
                active_or_scheduled_campaigns: 0,
                total_sent: 0,
                total_opened: 0,
                total_clicked: 0,
            });
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const handleExecute = async (e, campaign) => {
        e.stopPropagation();
        if (!window.confirm(t('campaign.confirm_execute', 'Execute this campaign for all segment contacts?'))) return;
        setExecuting(campaign.id);
        try {
            const res = await crmAPI.executeCampaign(campaign.id);
            showToast(t('campaign.executed_success', `Sent to ${res.data?.total_recipients || 0} recipients`), 'success');
            fetchData();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setExecuting(null);
        }
    };

    const handleDelete = async (e, id) => {
        e.stopPropagation();
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await crmAPI.deleteCampaign(id);
            fetchData();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('campaign.title', 'Campaign Management')}</h1>
                    <p className="workspace-subtitle">{t('campaign.subtitle', 'Create, execute, and track marketing campaigns')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={() => navigate('/crm/campaign-new')}>
                        + {t('campaign.new', 'New Campaign')}
                    </button>
                </div>
            </div>

            {/* KPI cards */}
            <div className="metrics-grid" style={{ marginBottom: 16 }}>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.total_campaigns', 'Total Campaigns')}</div>
                    <div className="metric-value text-primary">{summary.total_campaigns || 0}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.active_campaigns', 'Active / Scheduled')}</div>
                    <div className="metric-value text-warning">{summary.active_or_scheduled_campaigns || 0}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.total_sent', 'Total Sent')}</div>
                    <div className="metric-value text-info">{formatNumber(summary.total_sent || 0)}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('campaign.open_rate', 'Opens / Clicks')}</div>
                    <div className="metric-value text-success">{formatNumber(summary.total_opened || 0)} / {formatNumber(summary.total_clicked || 0)}</div>
                </div>
            </div>

            {/* Filters */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                <select className="form-input" style={{ maxWidth: 180 }}
                    value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                    <option value="">{t('common.all_statuses', 'All Statuses')}</option>
                    {['draft', 'scheduled', 'executing', 'completed', 'cancelled'].map(s =>
                        <option key={s} value={s}>{t(`campaign.status_${s}`, s)}</option>)}
                </select>
                <select className="form-input" style={{ maxWidth: 180 }}
                    value={filterType} onChange={e => setFilterType(e.target.value)}>
                    <option value="">{t('common.all_types', 'All Types')}</option>
                    {['email', 'sms', 'both'].map(s =>
                        <option key={s} value={s}>{t(`campaign.type_${s}`, s)}</option>)}
                </select>
            </div>

            {loading ? <PageLoading /> :
                campaigns.length === 0
                    ? <div className="empty-state">{t('campaign.no_campaigns', 'No campaigns found')}</div>
                    : (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('campaign.name', 'Name')}</th>
                                        <th>{t('campaign.type', 'Type')}</th>
                                        <th>{t('campaign.segment', 'Segment')}</th>
                                        <th>{t('common.status_title', 'Status')}</th>
                                        <th>{t('campaign.sent', 'Sent')}</th>
                                        <th>{t('campaign.opened', 'Opened')}</th>
                                        <th>{t('campaign.clicked', 'Clicked')}</th>
                                        <th>{t('campaign.responded', 'Responded')}</th>
                                        <th>{t('campaign.scheduled_date', 'Scheduled')}</th>
                                        <th>{t('common.actions', 'Actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {campaigns.map(c => (
                                        <tr key={c.id} style={{ cursor: 'pointer' }}
                                            onClick={() => navigate(`/crm/campaigns/${c.id}`)}>
                                            <td style={{ fontWeight: 600 }}>{c.name}</td>
                                            <td>
                                                <span className="badge" style={TYPE_STYLES[c.campaign_type] || {}}>
                                                    {t(`campaign.type_${c.campaign_type}`, c.campaign_type || '-')}
                                                </span>
                                            </td>
                                            <td>{c.segment_name || '-'}</td>
                                            <td>
                                                <span className={`status-badge ${STATUS_CLASSES[c.status] || ''}`}>
                                                    {t(`campaign.status_${c.status}`, c.status)}
                                                </span>
                                            </td>
                                            <td>{c.total_sent || 0}</td>
                                            <td>{c.total_opened || 0}</td>
                                            <td>{c.total_clicked || 0}</td>
                                            <td>{c.total_responded || 0}</td>
                                            <td style={{ fontSize: 12 }}>
                                                {c.scheduled_date ? formatShortDate(c.scheduled_date) : '-'}
                                            </td>
                                            <td onClick={e => e.stopPropagation()}>
                                                <div style={{ display: 'flex', gap: 4 }}>
                                                    {['draft', 'scheduled'].includes(c.status) && (
                                                        <button
                                                            className="btn btn-primary btn-sm"
                                                            onClick={e => handleExecute(e, c)}
                                                            disabled={executing === c.id}
                                                        >
                                                            {executing === c.id ? '...' : t('campaign.execute', 'Execute')}
                                                        </button>
                                                    )}
                                                    <button className="btn btn-secondary btn-sm"
                                                        onClick={e => { e.stopPropagation(); navigate(`/crm/campaigns/${c.id}/report`); }}>
                                                        {t('campaign.report', 'Report')}
                                                    </button>
                                                    <button className="btn btn-danger btn-sm"
                                                        onClick={e => handleDelete(e, c.id)}>
                                                        {t('common.delete', 'Delete')}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
        </div>
    );
}
