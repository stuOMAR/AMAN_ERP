import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { crmAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import '../../components/ModuleStyles.css';

const EMPTY_FORM = {
    name: '',
    campaign_type: 'email',
    segment_id: '',
    subject: '',
    content: '',
    scheduled_date: '',
    estimated_cost: '',
    description: '',
};

export default function CampaignForm() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const [form, setForm] = useState({ ...EMPTY_FORM });
    const [segments, setSegments] = useState([]);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        crmAPI.listSegments().then(r => setSegments(r.data || [])).catch(() => {});
    }, []);

    const set = (field, value) => setForm(prev => ({ ...prev, [field]: value }));

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (submitting) return;
        setSubmitting(true);
        try {
            const payload = {
                name: form.name,
                campaign_type: form.campaign_type,
                segment_id: form.segment_id ? parseInt(form.segment_id) : null,
                subject: form.subject || null,
                content: form.content || null,
                scheduled_date: form.scheduled_date || null,
                estimated_cost: form.estimated_cost || null,
                description: form.description || null,
                status: form.scheduled_date ? 'scheduled' : 'draft',
            };
            const res = await crmAPI.createCampaign(payload);
            showToast(t('campaign.created_success', 'Campaign created'), 'success');
            navigate(`/crm/campaigns/${res.data.id}`);
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('campaign.new', 'New Campaign')}</h1>
                    <p className="workspace-subtitle">{t('campaign.form_subtitle', 'Create a targeted marketing campaign')}</p>
                </div>
            </div>

            <div className="card section-card">
                <form onSubmit={handleSubmit} className="p-4">
                    {/* Section: Basic Info */}
                    <h3 className="section-title">{t('campaign.basic_info', 'Campaign Details')}</h3>
                    <div className="form-grid" style={{ marginBottom: 24 }}>
                        <div className="form-group">
                            <label className="form-label">{t('campaign.name', 'Campaign Name')} *</label>
                            <input className="form-input" required value={form.name}
                                onChange={e => set('name', e.target.value)}
                                placeholder={t('campaign.name_placeholder', 'e.g., Summer Sale 2026')} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('campaign.type', 'Channel')} *</label>
                            <select className="form-input" value={form.campaign_type}
                                onChange={e => set('campaign_type', e.target.value)}>
                                <option value="email">{t('campaign.type_email', 'Email')}</option>
                                <option value="sms">{t('campaign.type_sms', 'SMS')}</option>
                                <option value="both">{t('campaign.type_both', 'Email + SMS')}</option>
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('campaign.segment', 'Target Segment')}</label>
                            <select className="form-input" value={form.segment_id}
                                onChange={e => set('segment_id', e.target.value)}>
                                <option value="">{t('campaign.no_segment', '-- All Contacts --')}</option>
                                {segments.map(s => (
                                    <option key={s.id} value={s.id}>{s.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('campaign.scheduled_date', 'Schedule Date')}</label>
                            <DateInput value={form.scheduled_date}
                                onChange={e => set('scheduled_date', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('campaign.estimated_cost', 'Estimated Cost')}</label>
                            <input type="number" className="form-input" min="0" step="0.01"
                                value={form.estimated_cost}
                                onChange={e => set('estimated_cost', e.target.value)}
                                placeholder="0.00" />
                        </div>
                    </div>

                    {/* Section: Content */}
                    <h3 className="section-title">{t('campaign.content_section', 'Message Content')}</h3>
                    <div className="form-grid" style={{ marginBottom: 24 }}>
                        <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                            <label className="form-label">{t('campaign.subject', 'Subject / Header')}</label>
                            <input className="form-input" value={form.subject}
                                onChange={e => set('subject', e.target.value)}
                                placeholder={t('campaign.subject_placeholder', 'Email subject or SMS header')} />
                        </div>
                        <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                            <label className="form-label">{t('campaign.content', 'Content / Template')}</label>
                            <textarea className="form-input" rows={6} value={form.content}
                                onChange={e => set('content', e.target.value)}
                                placeholder={t('campaign.content_placeholder', 'Use {{name}}, {{company}} for merge fields')} />
                            <span style={{ fontSize: 11, color: '#64748b' }}>
                                {t('campaign.merge_hint', 'Supported merge fields: {{name}}, {{email}}, {{phone}}')}
                            </span>
                        </div>
                        <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                            <label className="form-label">{t('common.description', 'Internal Notes')}</label>
                            <textarea className="form-input" rows={2} value={form.description}
                                onChange={e => set('description', e.target.value)} />
                        </div>
                    </div>

                    <div className="form-actions">
                        <button type="button" className="btn btn-secondary"
                            onClick={() => navigate(-1)}>
                            {t('common.cancel', 'Cancel')}
                        </button>
                        <button type="submit" className="btn btn-primary" disabled={submitting}>
                            {submitting ? t('common.saving', 'Saving...') : t('campaign.create', 'Create Campaign')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
