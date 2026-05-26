import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { crmAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { formatShortDate } from '../../utils/dateUtils';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'

const typeColors = {
    email: { bg: '#dbeafe', color: '#1d4ed8' },
    sms: { bg: '#dcfce7', color: '#16a34a' },
    social: { bg: '#fce7f3', color: '#db2777' },
    event: { bg: '#fef3c7', color: '#d97706' }
};

const statusColors = {
    draft: 'status-pending',
    active: 'status-active',
    paused: 'status-partial',
    completed: 'status-completed'
};

function MarketingCampaigns() {
    const { t } = useTranslation();
  const { showToast } = useToast()
    const [campaigns, setCampaigns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [editId, setEditId] = useState(null);
    const [filterStatus, setFilterStatus] = useState('');
    const [filterType, setFilterType] = useState('');
    const [summary, setSummary] = useState({ total_campaigns: 0, active_campaigns: 0, total_budget: '0.00', total_conversions: 0 });

    const emptyForm = { name: '', campaign_type: 'email', status: 'draft', start_date: '', end_date: '', budget: '0.00', target_audience: '', description: '' };
    const [form, setForm] = useState({ ...emptyForm });

    useEffect(() => { fetchData(); }, [filterStatus, filterType]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const params = {};
            if (filterStatus) params.status = filterStatus;
            if (filterType) params.campaign_type = filterType;
            const [listRes, summaryRes] = await Promise.all([
                crmAPI.listCampaigns(params),
                crmAPI.getCampaignSummary(params)
            ]);
            setCampaigns(listRes.data || []);
            setSummary(summaryRes.data || { total_campaigns: 0, active_campaigns: 0, total_budget: '0.00', total_conversions: 0 });
        } catch (e) { console.error(e); }
        finally { setLoading(false); }
    };

    const openCreate = () => { setForm({ ...emptyForm }); setIsEdit(false); setEditId(null); setShowModal(true); };
    const openEdit = (c) => {
        setForm({ name: c.name, campaign_type: c.campaign_type, status: c.status, start_date: c.start_date || '', end_date: c.end_date || '', budget: c.budget || '0.00', target_audience: c.target_audience || '', description: c.description || '' });
        setIsEdit(true); setEditId(c.id); setShowModal(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const payload = { ...form, budget: form.budget || '0.00' };
            if (isEdit) await crmAPI.updateCampaign(editId, payload);
            else await crmAPI.createCampaign(payload);
            setShowModal(false); fetchData();
        } catch (err) { showToast(err.response?.data?.detail || 'Error', 'error'); }
    };

    const handleDelete = async (id) => {
        if (!window.confirm(t('common.confirm_delete', 'هل أنت متأكد؟'))) return;
        try { await crmAPI.deleteCampaign(id); fetchData(); } catch (e) { console.error(e); }
    };

    const typeLabel = (v) => t(`crm.campaign_type_${v}`, v);
    const statusLabel = (v) => t(`crm.campaign_status_${v}`, v);

    // Summary stats
    const totalCampaigns = summary.total_campaigns || 0;
    const totalBudget = summary.total_budget || '0.00';
    const activeCampaigns = summary.active_campaigns || 0;
    const totalConversions = summary.total_conversions || 0;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📢 {t('crm.campaigns_title', 'الحملات التسويقية')}</h1>
                    <p className="workspace-subtitle">{t('crm.campaigns_subtitle', 'إدارة الحملات التسويقية وتتبع الأداء')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={openCreate}>+ {t('crm.new_campaign', 'حملة جديدة')}</button>
                </div>
            </div>

            {/* Summary */}
            <div className="metrics-grid" style={{ marginBottom: 16 }}>
                <div className="metric-card"><div className="metric-label">{t('crm.total_campaigns', 'إجمالي الحملات')}</div><div className="metric-value text-primary">{totalCampaigns}</div></div>
                <div className="metric-card"><div className="metric-label">{t('crm.active_campaigns', 'الحملات النشطة')}</div><div className="metric-value text-success">{activeCampaigns}</div></div>
                <div className="metric-card"><div className="metric-label">{t('crm.total_budget', 'إجمالي الميزانية')}</div><div className="metric-value text-warning">{formatNumber(totalBudget)}</div></div>
                <div className="metric-card"><div className="metric-label">{t('crm.total_conversions', 'التحويلات')}</div><div className="metric-value text-info">{totalConversions}</div></div>
            </div>

            {/* Filters */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                <select className="form-input" style={{ maxWidth: 180 }} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                    <option value="">{t('common.all_statuses', 'كل الحالات')}</option>
                    {['draft', 'active', 'paused', 'completed'].map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
                </select>
                <select className="form-input" style={{ maxWidth: 180 }} value={filterType} onChange={e => setFilterType(e.target.value)}>
                    <option value="">{t('common.all_types', 'كل الأنواع')}</option>
                    {['email', 'sms', 'social', 'event'].map(s => <option key={s} value={s}>{typeLabel(s)}</option>)}
                </select>
            </div>

            {/* Table */}
            {loading ? <PageLoading /> :
            campaigns.length === 0 ? <div className="empty-state">{t('crm.no_campaigns', 'لا توجد حملات')}</div> : (
                <div className="data-table-container">
                    <table className="data-table">
                        <thead><tr>
                            <th>{t('crm.campaign_name', 'اسم الحملة')}</th>
                            <th>{t('crm.type', 'النوع')}</th>
                            <th>{t('common.status_title', 'الحالة')}</th>
                            <th>{t('crm.period', 'الفترة')}</th>
                            <th>{t('crm.budget', 'الميزانية')}</th>
                            <th>{t('crm.sent', 'مرسل')}</th>
                            <th>{t('crm.opens', 'فتح')}</th>
                            <th>{t('crm.clicks', 'نقرات')}</th>
                            <th>{t('crm.conversions', 'تحويلات')}</th>
                            <th>{t('common.actions', 'إجراءات')}</th>
                        </tr></thead>
                        <tbody>
                            {campaigns.map(c => (
                                <tr key={c.id}>
                                    <td style={{ fontWeight: 600 }}>{c.name}</td>
                                    <td><span className="badge" style={typeColors[c.campaign_type] || {}}>{typeLabel(c.campaign_type)}</span></td>
                                    <td><span className={`status-badge ${statusColors[c.status] || ''}`}>{statusLabel(c.status)}</span></td>
                                    <td style={{ fontSize: 12 }}>{c.start_date ? formatShortDate(c.start_date) : '-'} → {c.end_date ? formatShortDate(c.end_date) : '-'}</td>
                                    <td>{formatNumber(c.budget)}</td>
                                    <td>{c.total_sent || 0}</td>
                                    <td>{c.total_opened || 0}</td>
                                    <td>{c.total_clicked || 0}</td>
                                    <td>{c.total_responded || 0}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: 4 }}>
                                            <button className="btn btn-secondary btn-sm" onClick={() => openEdit(c)}>{t('crm.edit', 'تعديل')}</button>
                                            <button className="btn btn-danger btn-sm" onClick={() => handleDelete(c.id)}>{t('common.delete', 'حذف')}</button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Create/Edit Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
                        <div className="modal-header"><h3>{isEdit ? t('crm.edit_campaign', 'تعديل الحملة') : t('crm.new_campaign', 'حملة جديدة')}</h3></div>
                        <div className="modal-body">
                            <form id="campaign-form" onSubmit={handleSubmit}>
                                <div className="form-section"><div className="form-grid">
                                    <div className="form-group">
                                        <label className="form-label">{t('crm.campaign_name', 'اسم الحملة')}</label>
                                        <input className="form-input" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} required />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">{t('crm.type', 'النوع')}</label>
                                        <select className="form-input" value={form.campaign_type} onChange={e => setForm(p => ({ ...p, campaign_type: e.target.value }))}>
                                            {['email', 'sms', 'social', 'event'].map(t2 => <option key={t2} value={t2}>{typeLabel(t2)}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">{t('common.status_title', 'الحالة')}</label>
                                        <select className="form-input" value={form.status} onChange={e => setForm(p => ({ ...p, status: e.target.value }))}>
                                            {['draft', 'active', 'paused', 'completed'].map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">{t('crm.budget', 'الميزانية')}</label>
                                        <input type="number" className="form-input" value={form.budget} onChange={e => setForm(p => ({ ...p, budget: e.target.value }))} min="0" step="0.01" />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">{t('common.start_date', 'تاريخ البدء')}</label>
                                        <DateInput className="form-input" value={form.start_date} onChange={e => setForm(p => ({ ...p, start_date: e.target.value }))} />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">{t('common.end_date', 'تاريخ الانتهاء')}</label>
                                        <DateInput className="form-input" value={form.end_date} onChange={e => setForm(p => ({ ...p, end_date: e.target.value }))} />
                                    </div>
                                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                        <label className="form-label">{t('crm.target_audience', 'الجمهور المستهدف')}</label>
                                        <input className="form-input" value={form.target_audience} onChange={e => setForm(p => ({ ...p, target_audience: e.target.value }))} placeholder={t('crm.target_audience_placeholder', 'مثال: عملاء VIP، عملاء جدد...')} />
                                    </div>
                                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                        <label className="form-label">{t('common.description', 'الوصف')}</label>
                                        <textarea className="form-input" rows={3} value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
                                    </div>
                                </div></div>
                            </form>
                        </div>
                        <div className="modal-footer">
                            <button type="submit" form="campaign-form" className="btn btn-primary">{isEdit ? t('common.update', 'تحديث') : t('common.create', 'إنشاء')}</button>
                            <button className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('common.cancel', 'إلغاء')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

export default MarketingCampaigns;
