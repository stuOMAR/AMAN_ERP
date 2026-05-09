
import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Edit2, Trash2, X } from 'lucide-react';
import { costCentersAPI } from '../../../utils/api';
import { useBranch } from '../../../context/BranchContext';
import { getCurrency } from '../../../utils/auth';
import { toastEmitter } from '../../../utils/toastEmitter';
import BackButton from '../../../components/common/BackButton';
import DataTable from '../../../components/common/DataTable';
import SearchFilter from '../../../components/common/SearchFilter';

const CostCenterList = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const currency = getCurrency();
    const [costCenters, setCostCenters] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [editingId, setEditingId] = useState(null);
    const [filterValues, setFilterValues] = useState({});

    const [formData, setFormData] = useState({
        center_code: '',
        center_name: '',
        center_name_en: '',
        is_active: true
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchCostCenters();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchCostCenters = async () => {
        try {
            setLoading(true);
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const response = await costCentersAPI.list(params);
            setCostCenters(response.data);
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingId) {
                await costCentersAPI.update(editingId, formData);
                toastEmitter.emit(t('cost_centers.updated'), 'success');
            } else {
                await costCentersAPI.create(formData);
                toastEmitter.emit(t('cost_centers.created'), 'success');
            }
            setShowModal(false);
            fetchCostCenters();
            resetForm();
        } catch (error) {
            console.error(error);
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await costCentersAPI.delete(id);
            toastEmitter.emit(t('cost_centers.deleted'), 'success');
            fetchCostCenters();
        } catch (error) {
            console.error(error);
        }
    };

    const handleEdit = (center) => {
        setEditingId(center.id);
        setFormData({
            center_code: center.center_code || '',
            center_name: center.center_name,
            center_name_en: center.center_name_en || '',
            is_active: center.is_active
        });
        setShowModal(true);
    };

    const resetForm = () => {
        setEditingId(null);
        setFormData({
            center_code: '',
            center_name: '',
            center_name_en: '',
            is_active: true
        });
    };

    const filteredCenters = useMemo(() => {
        let result = costCenters.filter(c =>
            c.center_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            (c.center_code && c.center_code.toLowerCase().includes(searchTerm.toLowerCase()))
        );
        if (filterValues.status === 'active') {
            result = result.filter(c => c.is_active);
        } else if (filterValues.status === 'inactive') {
            result = result.filter(c => !c.is_active);
        }
        return result;
    }, [costCenters, searchTerm, filterValues]);

    const columns = useMemo(() => [
        {
            key: 'center_code',
            label: t('cost_centers.code'),
            width: '20%',
            render: (val) => <span className="fw-medium">{val || '-'}</span>,
        },
        {
            key: 'center_name',
            label: t('cost_centers.name'),
            width: '40%',
            render: (val, row) => (
                <div>
                    <div style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{val}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{row.center_name_en}</div>
                </div>
            ),
        },
        {
            key: 'is_active',
            label: t('cost_centers.status'),
            width: '20%',
            render: (val) => (
                <span className={`badge ${val ? 'badge-success' : 'badge-danger'}`}>
                    {val ? t('common.active') : t('common.inactive')}
                </span>
            ),
        },
        {
            key: '_actions',
            label: t('common.actions'),
            width: '20%',
            render: (_, row) => (
                <div className="d-flex gap-2">
                    <button
                        onClick={(e) => { e.stopPropagation(); handleEdit(row); }}
                        className="table-action-btn"
                        title={t('common.edit')}
                    >
                        <Edit2 size={16} />
                    </button>
                    <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(row.id); }}
                        className="table-action-btn"
                        style={{ color: 'var(--danger)' }}
                        title={t('common.delete')}
                    >
                        <Trash2 size={16} />
                    </button>
                </div>
            ),
        },
    ], [t]);

    const filters = useMemo(() => [
        {
            key: 'status',
            label: t('cost_centers.status'),
            options: [
                { value: 'active', label: t('common.active') },
                { value: 'inactive', label: t('common.inactive') },
            ],
        },
    ], [t]);

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('cost_centers.title')}</h1>
                            <p className="workspace-subtitle">{t('cost_centers.subtitle')}</p>
                        </div>
                    </div>
                    <button
                        onClick={() => { resetForm(); setShowModal(true); }}
                        className="btn btn-primary"
                    >
                        <span style={{ marginLeft: '8px' }}>+</span>
                        {t('cost_centers.add')}
                    </button>
                </div>
            </div>

            <SearchFilter
                value={searchTerm}
                onChange={setSearchTerm}
                placeholder={t('common.search')}
                filters={filters}
                filterValues={filterValues}
                onFilterChange={(key, value) => setFilterValues(prev => ({ ...prev, [key]: value }))}
            />

            <DataTable
                columns={columns}
                data={filteredCenters}
                loading={loading}
                emptyTitle={t('common.no_data')}
                rowKey="id"
                paginate={true}
            />

            {showModal && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h2 className="modal-title">
                                {editingId ? t('cost_centers.edit') : t('cost_centers.new')}
                            </h2>
                            <button onClick={() => setShowModal(false)} className="btn-icon" style={{ background: 'transparent' }}>
                                <X size={20} />
                            </button>
                        </div>
                        <form onSubmit={handleSubmit}>
                            <div className="modal-body">
                                <div className="form-group">
                                    <label className="form-label" htmlFor="center_code">{t('cost_centers.code')}</label>
                                    <input
                                        type="text"
                                        id="center_code"
                                        name="center_code"
                                        value={formData.center_code}
                                        onChange={(e) => setFormData({ ...formData, center_code: e.target.value })}
                                        className="form-input"
                                        autoComplete="off"
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label" htmlFor="center_name">{t('cost_centers.name_ar')} <span className="text-danger">*</span></label>
                                    <input
                                        type="text"
                                        id="center_name"
                                        name="center_name"
                                        required
                                        value={formData.center_name}
                                        onChange={(e) => setFormData({ ...formData, center_name: e.target.value })}
                                        className="form-input"
                                        autoComplete="off"
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label" htmlFor="center_name_en">{t('cost_centers.name_en')}</label>
                                    <input
                                        type="text"
                                        id="center_name_en"
                                        name="center_name_en"
                                        value={formData.center_name_en}
                                        onChange={(e) => setFormData({ ...formData, center_name_en: e.target.value })}
                                        className="form-input"
                                        autoComplete="off"
                                    />
                                </div>
                                <div className="d-flex align-items-center gap-2 mt-4">
                                    <input
                                        type="checkbox"
                                        id="is_active"
                                        checked={formData.is_active}
                                        onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                                        style={{ width: '18px', height: '18px' }}
                                    />
                                    <label htmlFor="is_active" className="mb-0" style={{ cursor: 'pointer' }}>{t('common.active')}</label>
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" onClick={() => setShowModal(false)} className="btn" style={{ background: 'var(--bg-hover)' }}>
                                    {t('common.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary">
                                    {t('common.save')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default CostCenterList;
