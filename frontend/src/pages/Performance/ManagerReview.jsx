import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { hrAdvancedAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { Star, Send, CheckCircle, Plus, Trash2 } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const ManagerReview = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const { id } = useParams();
    const [review, setReview] = useState(null);
    const [goals, setGoals] = useState([]);
    const [scores, setScores] = useState({});
    const [comments, setComments] = useState({});
    const [overallComments, setOverallComments] = useState('');
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [showGoalModal, setShowGoalModal] = useState(false);
    const [goalForm, setGoalForm] = useState({ title: '', description: '', weight: '', target: '' });

    const fetchReview = async () => {
        try {
            const res = await hrAdvancedAPI.getReviewDetail(id);
            const data = res.data;
            setReview(data);
            setGoals(data.goals || []);
            if (data.manager_assessment) {
                const sc = {}; const cm = {};
                data.manager_assessment.forEach(s => {
                    sc[s.goal_id] = s.score;
                    cm[s.goal_id] = s.comments || '';
                });
                setScores(sc);
                setComments(cm);
                setOverallComments(data.manager_comments || '');
            }
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
        setLoading(false);
    };

    useEffect(() => { fetchReview(); }, [id]);

    const setScore = (goalId, score) => setScores(s => ({ ...s, [goalId]: score }));
    const setComment = (goalId, text) => setComments(c => ({ ...c, [goalId]: text }));

    const handleSubmitAssessment = async () => {
        const scoreEntries = goals.map(g => ({
            goal_id: g.id,
            score: scores[g.id] || 0,
            comments: comments[g.id] || '',
        }));

        if (scoreEntries.some(s => s.score === 0)) {
            alert(t('performance.score_all_goals'));
            return;
        }

        setSubmitting(true);
        try {
            await hrAdvancedAPI.submitManagerAssessment(id, {
                scores: scoreEntries,
                overall_comments: overallComments,
            });
            alert(t('performance.manager_submitted'));
            fetchReview();
        } catch (e) {
            alert(e.response?.data?.detail || 'Error');
        }
        setSubmitting(false);
    };

    const handleFinalize = async () => {
        if (!window.confirm(t('performance.confirm_finalize'))) return;
        try {
            const res = await hrAdvancedAPI.finalizeReview(id);
            alert(`${t('performance.finalized')} — ${t('performance.composite_score')}: ${res.data.composite_score}`);
            fetchReview();
        } catch (e) {
            alert(e.response?.data?.detail || 'Error');
        }
    };

    const handleAddGoal = async () => {
        if (!goalForm.title || !goalForm.weight) return;
        try {
            await hrAdvancedAPI.addGoal(id, {
                title: goalForm.title,
                description: goalForm.description || null,
                weight: goalForm.weight,
                target: goalForm.target || null,
            });
            setGoalForm({ title: '', description: '', weight: '', target: '' });
            setShowGoalModal(false);
            fetchReview();
        } catch (e) {
            alert(e.response?.data?.detail || 'Error');
        }
    };

    const handleDeleteGoal = async (goalId) => {
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await hrAdvancedAPI.deleteGoal(goalId);
            fetchReview();
        } catch (e) { alert(e.response?.data?.detail || 'Error'); }
    };

    const renderStars = (goalId, readOnly = false) => {
        const current = scores[goalId] || 0;
        return (
            <div style={{ display: 'flex', gap: 4 }}>
                {[1, 2, 3, 4, 5].map(n => (
                    <Star key={n} size={20}
                        style={{ cursor: readOnly ? 'default' : 'pointer' }}
                        fill={n <= current ? '#f59e0b' : 'none'}
                        color={n <= current ? '#f59e0b' : '#d1d5db'}
                        onClick={() => !readOnly && setScore(goalId, n)} />
                ))}
            </div>
        );
    };

    if (loading) return <PageLoading />;
    if (!review) return <div className="empty-state">{t('performance.review_not_found')}</div>;

    const canAddGoals = review.status === 'pending_self' || review.status === 'pending_manager';
    const canAssess = review.status === 'pending_manager';
    const canFinalize = review.manager_assessment && review.status !== 'completed';

    // Build self-assessment lookup
    const selfScores = {};
    if (review.self_assessment) {
        review.self_assessment.forEach(s => { selfScores[s.goal_id] = s; });
    }

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <div>
                    <h1>{t('performance.manager_review')}</h1>
                    <p style={{ color: '#6b7280' }}>
                        {review.employee_name} {review.cycle_name ? `— ${review.cycle_name}` : ''}
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                    {canAddGoals && (
                        <button className="btn btn-outline" onClick={() => setShowGoalModal(true)}>
                            <Plus size={16} /> {t('performance.add_goal')}
                        </button>
                    )}
                    {canFinalize && (
                        <button className="btn btn-success" onClick={handleFinalize}>
                            <CheckCircle size={16} /> {t('performance.finalize')}
                        </button>
                    )}
                </div>
            </div>

            {review.status === 'completed' && (
                <div style={{ padding: '12px 20px', background: '#dcfce7', borderRadius: 8, marginBottom: 16, color: '#166534', fontWeight: 600 }}>
                    {t('performance.review_completed')} — {t('performance.composite_score')}: {review.composite_score}
                </div>
            )}

            {/* Goals with side-by-side assessments */}
            {goals.length === 0 ? (
                <div className="empty-state">
                    {t('performance.no_goals')}
                    {canAddGoals && <p>{t('performance.add_goals_hint')}</p>}
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                    {goals.map((g, idx) => {
                        const selfEntry = selfScores[g.id];
                        return (
                            <div key={g.id} style={{ background: '#f9fafb', padding: 20, borderRadius: 12, border: '1px solid #e5e7eb' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                    <h3 style={{ margin: 0 }}>{idx + 1}. {g.title}</h3>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                        <span style={{ fontSize: 13, color: '#6b7280' }}>{t('performance.weight')}: {g.weight}%</span>
                                        {canAddGoals && (
                                            <button className="btn btn-sm btn-danger" onClick={() => handleDeleteGoal(g.id)}>
                                                <Trash2 size={14} />
                                            </button>
                                        )}
                                    </div>
                                </div>
                                {g.description && <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 4 }}>{g.description}</p>}
                                {g.target && <p style={{ fontSize: 13, color: '#374151' }}><strong>{t('performance.target')}:</strong> {g.target}</p>}

                                {/* Side-by-side: Self (read-only) | Manager */}
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginTop: 16 }}>
                                    {/* Self Assessment Column */}
                                    <div style={{ padding: 12, background: '#eff6ff', borderRadius: 8 }}>
                                        <h4 style={{ margin: '0 0 8px', fontSize: 14 }}>{t('performance.self_assessment')}</h4>
                                        {selfEntry ? (
                                            <>
                                                <div style={{ display: 'flex', gap: 4 }}>
                                                    {[1, 2, 3, 4, 5].map(n => (
                                                        <Star key={n} size={18}
                                                            fill={n <= (selfEntry.score || 0) ? '#3b82f6' : 'none'}
                                                            color={n <= (selfEntry.score || 0) ? '#3b82f6' : '#d1d5db'} />
                                                    ))}
                                                </div>
                                                {selfEntry.comments && <p style={{ fontSize: 13, marginTop: 4, color: '#374151' }}>{selfEntry.comments}</p>}
                                            </>
                                        ) : (
                                            <span style={{ color: '#9ca3af', fontSize: 13 }}>{t('performance.not_submitted')}</span>
                                        )}
                                    </div>

                                    {/* Manager Assessment Column */}
                                    <div style={{ padding: 12, background: '#fef3c7', borderRadius: 8 }}>
                                        <h4 style={{ margin: '0 0 8px', fontSize: 14 }}>{t('performance.manager_assessment')}</h4>
                                        {canAssess ? (
                                            <>
                                                {renderStars(g.id)}
                                                <textarea className="form-control" rows={2} style={{ marginTop: 8, fontSize: 13 }}
                                                    value={comments[g.id] || ''}
                                                    onChange={e => setComment(g.id, e.target.value)}
                                                    placeholder={t('performance.comments_placeholder')} />
                                            </>
                                        ) : (
                                            <>
                                                <div style={{ display: 'flex', gap: 4 }}>
                                                    {[1, 2, 3, 4, 5].map(n => (
                                                        <Star key={n} size={18}
                                                            fill={n <= (scores[g.id] || 0) ? '#f59e0b' : 'none'}
                                                            color={n <= (scores[g.id] || 0) ? '#f59e0b' : '#d1d5db'} />
                                                    ))}
                                                </div>
                                                {comments[g.id] && <p style={{ fontSize: 13, marginTop: 4 }}>{comments[g.id]}</p>}
                                                {!scores[g.id] && <span style={{ color: '#9ca3af', fontSize: 13 }}>{t('performance.not_submitted')}</span>}
                                            </>
                                        )}
                                    </div>
                                </div>
                            </div>
                        );
                    })}

                    {/* Overall comments + Submit */}
                    {canAssess && (
                        <>
                            <div className="form-group">
                                <label style={{ fontWeight: 600 }}>{t('performance.overall_comments')}</label>
                                <textarea className="form-control" rows={3}
                                    value={overallComments}
                                    onChange={e => setOverallComments(e.target.value)}
                                    placeholder={t('performance.overall_comments_placeholder')} />
                            </div>
                            <button className="btn btn-primary" onClick={handleSubmitAssessment} disabled={submitting}
                                style={{ alignSelf: 'flex-start' }}>
                                <Send size={16} /> {submitting ? t('common.saving') : t('performance.submit_manager')}
                            </button>
                        </>
                    )}
                </div>
            )}

            {/* Add Goal Modal */}
            {showGoalModal && (
                <div className="modal-overlay" onClick={() => setShowGoalModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h2>{t('performance.add_goal')}</h2>
                        <div className="form-group">
                            <label>{t('performance.goal_title')} *</label>
                            <input className="form-control" value={goalForm.title}
                                onChange={e => setGoalForm(f => ({ ...f, title: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label>{t('performance.goal_description')}</label>
                            <textarea className="form-control" rows={2} value={goalForm.description}
                                onChange={e => setGoalForm(f => ({ ...f, description: e.target.value }))} />
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                            <div className="form-group">
                                <label>{t('performance.weight')} (%) *</label>
                                <input type="number" className="form-control" value={goalForm.weight}
                                    onChange={e => setGoalForm(f => ({ ...f, weight: e.target.value }))}
                                    min="0" max="100" step="0.01" />
                            </div>
                            <div className="form-group">
                                <label>{t('performance.target')}</label>
                                <input className="form-control" value={goalForm.target}
                                    onChange={e => setGoalForm(f => ({ ...f, target: e.target.value }))} />
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
                            <button className="btn btn-primary" onClick={handleAddGoal}>{t('common.save')}</button>
                            <button className="btn btn-secondary" onClick={() => setShowGoalModal(false)}>{t('common.cancel')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default ManagerReview;
