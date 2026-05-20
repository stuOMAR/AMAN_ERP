import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import Decimal from 'decimal.js';
import { resourceAPI } from '../../utils/api';
import { Trash2, Edit, UserPlus } from 'lucide-react';
import { formatNumber } from '../../utils/format';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const ProjectResources = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const { projectId } = useParams();
    const navigate = useNavigate();

    const [allocations, setAllocations] = useState([]);
    const [loading, setLoading] = useState(true);

    const load = () => {
        setLoading(true);
        resourceAPI.getProjectResources(projectId)
            .then(res => setAllocations(res.data?.allocations || res.data || []))
            .catch(e => console.error(e))
            .finally(() => setLoading(false));
    };

    useEffect(() => { load(); }, [projectId]);

    const handleDelete = async (allocId) => {
        if (!window.confirm(t('resource.confirm_delete'))) return;
        try {
            await resourceAPI.deleteAllocation(allocId);
            load();
        } catch (e) {
            console.error(e);
        }
    };

    const totalPercent = allocations.reduce((s, a) => s.plus(new Decimal(a.allocation_percent || '0')), new Decimal('0'));

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{t('resource.project_resources')}</h1>
                <button className="btn btn-primary" onClick={() => navigate('/projects/resources/allocate')}>
                    <UserPlus size={16} style={{ marginRight: isRTL ? 0 : 6, marginLeft: isRTL ? 6 : 0 }} />
                    {t('resource.new_allocation')}
                </button>
            </div>

            {/* Summary cards */}
            <div className="kpi-grid" style={{ marginBottom: 16 }}>
                <div className="kpi-card">
                    <div className="kpi-label">{t('resource.team_members')}</div>
                    <div className="kpi-value">{allocations.length}</div>
                </div>
                <div className="kpi-card">
                    <div className="kpi-label">{t('resource.total_allocation')}</div>
                    <div className="kpi-value" style={{ color: totalPercent > 100 ? '#dc3545' : '#28a745' }}>
                        {totalPercent.toFixed(0)}%
                    </div>
                </div>
            </div>

            {loading ? (
                <PageLoading />
            ) : allocations.length === 0 ? (
                <div className="empty-state">{t('resource.no_allocations')}</div>
            ) : (
                <div style={{ overflowX: 'auto' }}>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('resource.employee')}</th>
                                <th>{t('resource.role')}</th>
                                <th>{t('resource.allocation_percent')}</th>
                                <th>{t('resource.start_date')}</th>
                                <th>{t('resource.end_date')}</th>
                                <th style={{ width: 100 }}>{t('common.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {allocations.map(a => (
                                <tr key={a.id}>
                                    <td>{a.employee_name}</td>
                                    <td>{a.role || '—'}</td>
                                    <td>
                                        <span className={`badge ${
                                            new Decimal(a.allocation_percent || '0').gt(100) ? 'badge-danger' :
                                            new Decimal(a.allocation_percent || '0').gt(80) ? 'badge-warning' :
                                            'badge-success'
                                        }`}>
                                            {formatNumber(a.allocation_percent || '0')}%
                                        </span>
                                    </td>
                                    <td>{new Date(a.start_date + 'T00:00:00').toLocaleDateString(i18n.language)}</td>
                                    <td>{new Date(a.end_date + 'T00:00:00').toLocaleDateString(i18n.language)}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: 6 }}>
                                            <button className="btn btn-sm btn-secondary"
                                                    onClick={() => navigate(`/projects/resources/allocate/${a.id}`)}
                                                    title={t('common.edit')}>
                                                <Edit size={14} />
                                            </button>
                                            <button className="btn btn-sm btn-danger"
                                                    onClick={() => handleDelete(a.id)}
                                                    title={t('common.delete')}>
                                                <Trash2 size={14} />
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
};

export default ProjectResources;
