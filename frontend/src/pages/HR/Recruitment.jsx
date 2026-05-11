import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { hrImprovementsAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';
import { Briefcase, Users, Plus, ArrowRight, X, CheckCircle, ExternalLink } from 'lucide-react';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
const Recruitment = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [activeTab, setActiveTab] = useState('openings');
    const [openings, setOpenings] = useState([]);
    const [applications, setApplications] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalType, setModalType] = useState('opening');
    const [filterStatus, setFilterStatus] = useState('all');
    const [showDetailModal, setShowDetailModal] = useState(false);
    const [selectedApp, setSelectedApp] = useState(null);

    const [openingForm, setOpeningForm] = useState({ title: '', department: '', positions: 1, requirements: '', deadline: '', description: '', employment_type: 'full_time' });
    const [appForm, setAppForm] = useState({ job_opening_id: '', applicant_name: '', email: '', phone: '', resume_url: '', cover_letter: '' });

    const [filterStage, setFilterStage] = useState('all');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);
    useEffect(() => { if (activeTab === 'applications' && applications.length === 0) fetchApplications(); }, [activeTab]);

    const fetchData = async () => {
        try {
            setLoading(true);
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const [openRes, appRes] = await Promise.all([
                hrImprovementsAPI.listJobOpenings(params),
                hrImprovementsAPI.listAllApplications(params)
            ]);
            setOpenings(openRes.data || []);
            setApplications(appRes.data || []);
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); } finally { setLoading(false); setInitialLoad(false); }
    };

    const fetchApplications = async () => {
        try {
            setLoading(true);
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await hrImprovementsAPI.listAllApplications(params);
            setApplications(res.data || []);
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const handleCreateOpening = async (e) => {
        e.preventDefault();
        try {
            await hrImprovementsAPI.createJobOpening({ ...openingForm, positions: parseInt(openingForm.positions) });
            toastEmitter.emit(t('hr.job_opening_created'), 'success');
            setShowModal(false);
            setOpeningForm({ title: '', department: '', positions: 1, requirements: '', deadline: '', description: '', employment_type: 'full_time' });
            fetchData();
        } catch (err) { toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleCreateApplication = async (e) => {
        e.preventDefault();
        try {
            await hrImprovementsAPI.createApplication({ ...appForm, job_opening_id: parseInt(appForm.job_opening_id) });
            toastEmitter.emit(t('hr.application_submitted'), 'success');
            setShowModal(false);
            setAppForm({ job_opening_id: '', applicant_name: '', email: '', phone: '', resume_url: '', cover_letter: '' });
            fetchData();
        } catch (err) { toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleUpdateStage = async (appId, stage) => {
        try {
            await hrImprovementsAPI.updateApplicationStage(appId, { stage });
            toastEmitter.emit(t('hr.stage_updated'), 'success');
            fetchData();
            if (selectedApp && selectedApp.id === appId) setSelectedApp({ ...selectedApp, stage });
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    const handleCloseOpening = async (openingId) => {
        try {
            await hrImprovementsAPI.updateJobOpening(openingId, { status: 'closed' });
            toastEmitter.emit(t('hr.opening_closed'), 'success');
            fetchData();
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    const statusBadge = (status) => {
        const map = {
            open: { cls: 'bg-green-100 text-green-700', label: t('hr.status_open') },
            closed: { cls: 'bg-gray-100 text-gray-700', label: t('hr.status_closed') },
            new: { cls: 'bg-blue-100 text-blue-700', label: t('hr.stage_new') },
            screening: { cls: 'bg-yellow-100 text-yellow-700', label: t('hr.stage_screening') },
            interview: { cls: 'bg-purple-100 text-purple-700', label: t('hr.stage_interview') },
            offer: { cls: 'bg-orange-100 text-orange-700', label: t('hr.stage_offer') },
            hired: { cls: 'bg-green-100 text-green-700', label: t('hr.stage_hired') },
            rejected: { cls: 'bg-red-100 text-red-700', label: t('hr.stage_rejected') },
        };
        const conf = map[status] || { cls: 'bg-gray-100 text-gray-700', label: status };
        return <span className={`badge ${conf.cls}`}>{conf.label}</span>;
    };

    const stages = ['new', 'screening', 'interview', 'offer', 'hired', 'rejected'];
    const stageLabels = {
        new: t('hr.stage_new'), screening: t('hr.stage_screening'), interview: t('hr.stage_interview'),
        offer: t('hr.stage_offer'), hired: t('hr.stage_hired'), rejected: t('hr.stage_rejected')
    };

    const empTypeLabels = {
        full_time: t('hr.emp_type_full_time'),
        part_time: t('hr.emp_type_part_time'),
        contract: t('hr.emp_type_contract'),
        intern: t('hr.emp_type_intern'),
    };

    // Summary stats
    const openCount = openings.filter(o => o.status !== 'closed').length;
    const totalPositions = openings.filter(o => o.status !== 'closed').reduce((s, o) => s + (o.positions || 0), 0);
    const hiredCount = applications.filter(a => a.stage === 'hired').length;

    // Filtered openings
    const filteredOpenings = filterStatus === 'all' ? openings : openings.filter(o => (o.status || 'open') === filterStatus);

    // Filtered applications
    const filteredApplications = filterStage === 'all' ? applications : applications.filter(a => (a.stage || 'new') === filterStage);

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-indigo-50 text-indigo-600"><Briefcase size={24} /></span> {t('hr.recruitment_title')}</h1>
                        <p className="workspace-subtitle">{t('hr.recruitment_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => { setModalType(activeTab === 'openings' ? 'opening' : 'application'); setShowModal(true); }}>
                        <Plus size={18} /> {activeTab === 'openings' ? t('hr.new_opening') : t('hr.new_application')}
                    </button>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', marginBottom: 24 }}>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.rec_open_positions')}</div>
                    <div className="metric-value" style={{ color: '#16a34a' }}>{openCount}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.rec_total_vacancies')}</div>
                    <div className="metric-value" style={{ color: '#2563eb' }}>{totalPositions}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.rec_total_applications')}</div>
                    <div className="metric-value" style={{ color: '#7c3aed' }}>{applications.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.rec_hired')}</div>
                    <div className="metric-value" style={{ color: '#d97706' }}>{hiredCount}</div>
                </div>
            </div>

            {/* Tabs */}
            <div className="d-flex gap-2 mb-4" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
                <div className="d-flex gap-2">
                    <button onClick={() => setActiveTab('openings')} className={`btn ${activeTab === 'openings' ? 'btn-primary' : 'btn-secondary'}`}><Briefcase size={16} /> {t('hr.tab_openings')}</button>
                    <button onClick={() => setActiveTab('applications')} className={`btn ${activeTab === 'applications' ? 'btn-primary' : 'btn-secondary'}`}><Users size={16} /> {t('hr.tab_applications')}</button>
                </div>
                {activeTab === 'openings' && (
                    <select className="form-input" style={{ width: 'auto', minWidth: 140 }} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                        <option value="all">{t('hr.filter_all')}</option>
                        <option value="open">{t('hr.status_open')}</option>
                        <option value="closed">{t('hr.status_closed')}</option>
                    </select>
                )}
                {activeTab === 'applications' && (
                    <select className="form-input" style={{ width: 'auto', minWidth: 160 }} value={filterStage} onChange={e => setFilterStage(e.target.value)}>
                        <option value="all">{t('hr.filter_all')}</option>
                        {stages.map(s => <option key={s} value={s}>{stageLabels[s]}</option>)}
                    </select>
                )}
            </div>

            <div className="card section-card">
                {initialLoad && !openings.length ? <PageLoading /> : activeTab === 'openings' ? (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('hr.col_title')}</th>
                                <th>{t('hr.col_department')}</th>
                                <th>{t('hr.col_emp_type')}</th>
                                <th style={{ textAlign: 'center' }}>{t('hr.col_positions')}</th>
                                <th style={{ textAlign: 'center' }}>{t('hr.rec_applications_count')}</th>
                                <th>{t('hr.col_deadline')}</th>
                                <th>{t('hr.col_status')}</th>
                                <th>{t('hr.col_actions')}</th>
                            </tr></thead>
                            <tbody>
                                {filteredOpenings.map(o => (
                                    <tr key={o.id}>
                                        <td className="font-medium">{o.title}</td>
                                        <td>{o.department || '—'}</td>
                                        <td><span className="badge bg-blue-50 text-blue-700">{empTypeLabels[o.employment_type] || o.employment_type || '—'}</span></td>
                                        <td style={{ textAlign: 'center' }}>{o.positions}</td>
                                        <td style={{ textAlign: 'center' }}>
                                            <span className={`badge ${(o.applications_count || 0) > 0 ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-500'}`}>
                                                {o.applications_count || 0}
                                            </span>
                                        </td>
                                        <td>{o.deadline || '—'}</td>
                                        <td>{statusBadge(o.status || 'open')}</td>
                                        <td>
                                            {(o.status || 'open') === 'open' && (
                                                <button className="btn btn-sm btn-secondary" onClick={() => handleCloseOpening(o.id)} title={t('hr.close_opening')}>
                                                    <X size={12} />
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                                {filteredOpenings.length === 0 && <tr><td colSpan="8" className="text-center text-muted p-4">{t('hr.no_openings')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('hr.col_applicant')}</th>
                                <th>{t('hr.col_email')}</th>
                                <th>{t('hr.phone')}</th>
                                <th>{t('hr.col_job')}</th>
                                <th>{t('hr.col_stage')}</th>
                                <th>{t('hr.col_actions')}</th>
                            </tr></thead>
                            <tbody>
                                {filteredApplications.map(a => (
                                    <tr key={a.id}>
                                        <td className="font-medium" style={{ cursor: 'pointer' }} onClick={() => { setSelectedApp(a); setShowDetailModal(true); }}>
                                            {a.applicant_name}
                                        </td>
                                        <td>{a.email || '—'}</td>
                                        <td>{a.phone || '—'}</td>
                                        <td>{a.opening_title || `#${a.job_opening_id}`}</td>
                                        <td>{statusBadge(a.stage || 'new')}</td>
                                        <td>
                                            <div className="d-flex gap-1 flex-wrap">
                                                {stages.filter(s => s !== a.stage).slice(0, 3).map(s => (
                                                    <button key={s} className="btn btn-sm btn-secondary" title={stageLabels[s]} onClick={() => handleUpdateStage(a.id, s)}>
                                                        {s === 'hired' ? <CheckCircle size={12} /> : s === 'rejected' ? <X size={12} /> : <ArrowRight size={12} />}
                                                        <span className="text-xs" style={{ marginInlineStart: 2 }}>{stageLabels[s]}</span>
                                                    </button>
                                                ))}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {filteredApplications.length === 0 && <tr><td colSpan="6" className="text-center text-muted p-4">{applications.length === 0 ? t('hr.no_applications') : t('common.no_data')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}

            {/* Application Detail Modal */}
            {showDetailModal && selectedApp && (
                <div className="modal-overlay" onClick={() => setShowDetailModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}>{t('hr.application_detail')}</h3>
                            <button type="button" onClick={() => setShowDetailModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: 'var(--text-muted)' }}>✕</button>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                            <div>
                                <div style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.col_applicant')}</div>
                                <div style={{ fontWeight: 600 }}>{selectedApp.applicant_name}</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.col_job')}</div>
                                <div>{selectedApp.opening_title || `#${selectedApp.job_opening_id}`}</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.col_email')}</div>
                                <div>{selectedApp.email || '—'}</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.phone')}</div>
                                <div>{selectedApp.phone || '—'}</div>
                            </div>
                        </div>

                        {selectedApp.cover_letter && (
                            <div style={{ marginBottom: 16 }}>
                                <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>{t('hr.cover_letter')}</div>
                                <div style={{ background: '#f8fafc', padding: 12, borderRadius: 8, fontSize: 13 }}>{selectedApp.cover_letter}</div>
                            </div>
                        )}

                        {selectedApp.resume_url && (
                            <a href={selectedApp.resume_url} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-secondary" style={{ marginBottom: 16, display: 'inline-flex', gap: 4 }}>
                                <ExternalLink size={14} /> {t('hr.view_resume')}
                            </a>
                        )}

                        <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>{t('hr.col_stage')}: {statusBadge(selectedApp.stage || 'new')}</div>

                        {/* Stage Pipeline */}
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                            {stages.map(s => (
                                <button key={s} disabled={s === selectedApp.stage}
                                    className={`btn btn-sm ${s === selectedApp.stage ? 'btn-primary' : 'btn-secondary'}`}
                                    onClick={() => handleUpdateStage(selectedApp.id, s)}>
                                    {stageLabels[s]}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Job Opening Modal */}
            {showModal && modalType === 'opening' && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}>{t('hr.new_job_opening_modal')}</h3>
                            <button type="button" onClick={() => setShowModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: 'var(--text-muted)' }}>✕</button>
                        </div>
                        <form onSubmit={handleCreateOpening} className="space-y-4">
                            <div className="form-group">
                                <label className="form-label">{t('hr.job_title')}</label>
                                <input className="form-input" required value={openingForm.title} onChange={e => setOpeningForm({ ...openingForm, title: e.target.value })} />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="form-group">
                                    <label className="form-label">{t('hr.col_department')}</label>
                                    <input className="form-input" value={openingForm.department} onChange={e => setOpeningForm({ ...openingForm, department: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('hr.col_emp_type')}</label>
                                    <select className="form-input" value={openingForm.employment_type} onChange={e => setOpeningForm({ ...openingForm, employment_type: e.target.value })}>
                                        <option value="full_time">{t('hr.emp_type_full_time')}</option>
                                        <option value="part_time">{t('hr.emp_type_part_time')}</option>
                                        <option value="contract">{t('hr.emp_type_contract')}</option>
                                        <option value="intern">{t('hr.emp_type_intern')}</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.positions_count')}</label>
                                <input type="number" className="form-input" min="1" required value={openingForm.positions} onChange={e => setOpeningForm({ ...openingForm, positions: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.description')}</label>
                                <textarea className="form-input" rows="2" value={openingForm.description} onChange={e => setOpeningForm({ ...openingForm, description: e.target.value })} placeholder={t('hr.description_placeholder')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.requirements')}</label>
                                <textarea className="form-input" rows="3" value={openingForm.requirements} onChange={e => setOpeningForm({ ...openingForm, requirements: e.target.value })} placeholder={t('hr.requirements_placeholder')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.deadline')}</label>
                                <DateInput value={openingForm.deadline} onChange={e => setOpeningForm({ ...openingForm, deadline: e.target.value })} />
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('hr.create')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('hr.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Application Modal */}
            {showModal && modalType === 'application' && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}>{t('hr.new_application_modal')}</h3>
                            <button type="button" onClick={() => setShowModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: 'var(--text-muted)' }}>✕</button>
                        </div>
                        <form onSubmit={handleCreateApplication} className="space-y-4">
                            <div className="form-group">
                                <label className="form-label">{t('hr.col_job')}</label>
                                <select className="form-input" required value={appForm.job_opening_id} onChange={e => setAppForm({ ...appForm, job_opening_id: e.target.value })}>
                                    <option value="">{t('hr.select_opening')}</option>
                                    {openings.filter(o => (o.status || 'open') === 'open').map(o => (
                                        <option key={o.id} value={o.id}>{o.title} — {o.department || ''}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.applicant_name')}</label>
                                <input className="form-input" required value={appForm.applicant_name} onChange={e => setAppForm({ ...appForm, applicant_name: e.target.value })} />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="form-group">
                                    <label className="form-label">{t('hr.col_email')}</label>
                                    <input type="email" className="form-input" value={appForm.email} onChange={e => setAppForm({ ...appForm, email: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('hr.phone')}</label>
                                    <input className="form-input" value={appForm.phone} onChange={e => setAppForm({ ...appForm, phone: e.target.value })} />
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.resume_url')}</label>
                                <input className="form-input" value={appForm.resume_url} onChange={e => setAppForm({ ...appForm, resume_url: e.target.value })} placeholder="https://..." />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.cover_letter')}</label>
                                <textarea className="form-input" rows="3" value={appForm.cover_letter} onChange={e => setAppForm({ ...appForm, cover_letter: e.target.value })} />
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('hr.submit')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('hr.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Recruitment;
