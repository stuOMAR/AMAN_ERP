import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { branchesAPI, currenciesAPI } from '../../utils/api';
import SimpleModal from '../../components/common/SimpleModal';
import { useBranch } from '../../context/BranchContext';
import { Plus, Edit, Trash, MapPin } from 'lucide-react';
import { hasPermission } from '../../utils/auth';
import { toastEmitter } from '../../utils/toastEmitter';
import '../../index.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const COUNTRIES = [
    { code: 'SA', name: 'المملكة العربية السعودية', name_en: 'Saudi Arabia', currency: 'SAR', currencyName: 'ريال سعودي', flag: '🇸🇦' },
    { code: 'SY', name: 'سوريا', name_en: 'Syria', currency: 'SYP', currencyName: 'ليرة سورية', flag: '🇸🇾' },
    { code: 'AE', name: 'الإمارات', name_en: 'UAE', currency: 'AED', currencyName: 'درهم إماراتي', flag: '🇦🇪' },
    { code: 'EG', name: 'مصر', name_en: 'Egypt', currency: 'EGP', currencyName: 'جنيه مصري', flag: '🇪🇬' },
    { code: 'KW', name: 'الكويت', name_en: 'Kuwait', currency: 'KWD', currencyName: 'دينار كويتي', flag: '🇰🇼' },
    { code: 'TR', name: 'تركيا', name_en: 'Turkey', currency: 'TRY', currencyName: 'ليرة تركية', flag: '🇹🇷' },
];

// All available currencies: from countries + common extras, deduped
const ALL_CURRENCIES = [
    ...COUNTRIES.map(c => ({ code: c.currency, name: c.currencyName })),
    { code: 'USD', name: 'دولار أمريكي' },
    { code: 'EUR', name: 'يورو' },
].reduce((acc, cur) => {
    if (!acc.find(x => x.code === cur.code)) acc.push(cur);
    return acc;
}, []);

const Branches = () => {
    const { t } = useTranslation();
    const { branches, loading, refreshBranches } = useBranch();
    const [showModal, setShowModal] = useState(false);
    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({
        branch_name: '',
        branch_name_en: '',
        branch_code: '',
        address: '',
        city: '',
        country: '',
        country_code: '',
        default_currency: '',
        phone: '',
        email: '',
        is_active: true
    });
    const [currencies, setCurrencies] = useState([]);
    const [saving, setSaving] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const canManageBranches = hasPermission('branches.manage');

    const refreshCurrencies = () => {
        currenciesAPI.list().then(res => setCurrencies(res.data || [])).catch(() => {});
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            refreshBranches();
            refreshCurrencies();
            setInitialLoad(false);
        }, 300)
        return () => clearTimeout(timer)
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!canManageBranches) {
            toastEmitter.emit(t('branches.no_manage_permission', 'ليس لديك صلاحية لإدارة الفروع'), 'warning');
            return;
        }
        setSaving(true);
        try {
            if (isEditing) {
                await branchesAPI.update(formData.id, formData);
                toastEmitter.emit(t('branches.update_success', 'تم تحديث الفرع بنجاح'), 'success');
            } else {
                await branchesAPI.create(formData);
                toastEmitter.emit(t('branches.create_success', 'تم إنشاء الفرع بنجاح'), 'success');
            }
            setShowModal(false);
            refreshBranches();
            refreshCurrencies();
            resetForm();
        } catch (error) {
            console.error('Error saving branch:', error);
            const detail = error.response?.data?.detail;
            const message = typeof detail === 'string'
                ? detail
                : Array.isArray(detail)
                    ? detail.map(item => item.msg).join(', ')
                    : t('branches.save_error', 'تعذر حفظ الفرع. راجع البيانات والصلاحيات.');
            toastEmitter.emit(message, 'error');
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (id) => {
        if (!canManageBranches) {
            toastEmitter.emit(t('branches.no_manage_permission', 'ليس لديك صلاحية لإدارة الفروع'), 'warning');
            return;
        }
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await branchesAPI.delete(id);
            toastEmitter.emit(t('branches.delete_success', 'تم حذف الفرع بنجاح'), 'success');
            refreshBranches();
        } catch (error) {
            console.error('Error deleting branch:', error);
            // The global api interceptor in apiClient.js will handle showing the toast for 400 and 500 errors
            // So we don't emit another one here to avoid duplicates.
        }
    };

    const resetForm = () => {
        setFormData({
            branch_name: '',
            branch_name_en: '',
            branch_code: '',
            address: '',
            city: '',
            country: '',
            country_code: '',
            default_currency: '',
            phone: '',
            email: '',
            is_active: true
        });
        setIsEditing(false);
    };

    const handleCountryChange = (code) => {
        const c = COUNTRIES.find(c => c.code === code);
        if (c) {
            // Always auto-set the official currency of the selected country
            setFormData(prev => ({
                ...prev,
                country_code: c.code,
                country: c.name,
                default_currency: c.currency
            }));
        } else {
            setFormData(prev => ({ ...prev, country_code: code }));
        }
    };

    const openEdit = (branch) => {
        setFormData(branch);
        setIsEditing(true);
        setShowModal(true);
    };

    if (initialLoad && loading) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🏢 {t('branches.title')}</h1>
                    <p className="workspace-subtitle">{t('branches.subtitle')}</p>
                </div>
                <div className="header-actions">
                    {canManageBranches && (
                        <button className="btn btn-primary" onClick={() => { resetForm(); setShowModal(true); }}>
                            <Plus size={16} className="ms-2" />
                            {t('branches.add_new')}
                        </button>
                    )}
                </div>
            </div>

            <div className="metrics-grid">
                <div className="metric-card">
                    <div className="metric-label">{t('branches.total_branches')}</div>
                    <div className="metric-value text-primary">
                        {hasPermission('reports.view') ? branches.length : '***'}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('branches.active_branches')}</div>
                    <div className="metric-value text-success">
                        {hasPermission('reports.view') ? branches.filter(b => b.is_active).length : '***'}
                    </div>
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('branches.name')}</th>
                            <th>{t('branches.code')}</th>
                            <th>{t('branches.country')}</th>
                            <th>{t('branches.currency')}</th>
                            <th>{t('branches.city')}</th>
                            <th>{t('branches.status')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {branches.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="text-center py-5 text-muted">{t('branches.no_branches')}</td>
                            </tr>
                        ) : (
                            branches.map(branch => (
                                <tr key={branch.id}>
                                    <td>
                                        <div className="font-medium text-primary">{branch.branch_name}</div>
                                        <div className="text-sm text-muted">{branch.branch_name_en}</div>
                                    </td>
                                    <td>{branch.branch_code || '-'}</td>
                                    <td>
                                        {branch.country_code ? (
                                            <div className="d-flex align-items-center gap-1">
                                                <span>{COUNTRIES.find(c => c.code === branch.country_code)?.flag || '🌍'}</span>
                                                <span>{branch.country || branch.country_code}</span>
                                            </div>
                                        ) : (branch.country || '-')}
                                    </td>
                                    <td>
                                        {branch.default_currency ? (
                                            <span className="badge badge-info">{branch.default_currency}</span>
                                        ) : '-'}
                                    </td>
                                    <td>
                                        {branch.city && (
                                            <div className="d-flex align-items-center gap-1">
                                                <MapPin size={12} /> {branch.city}
                                            </div>
                                        )}
                                    </td>
                                    <td>
                                        {branch.is_active ?
                                            <span className="badge badge-success">{t('common.active')}</span> :
                                            <span className="badge badge-danger">{t('common.inactive')}</span>
                                        }
                                        {branch.is_default && <span className="badge badge-warning ms-1">{t('common.default')}</span>}
                                    </td>
                                    <td>
                                        <div className="action-buttons">
                                            {canManageBranches && (
                                                <button className="btn-icon" onClick={() => openEdit(branch)} title={t('common.edit')}>
                                                    <Edit size={16} />
                                                </button>
                                            )}
                                            {canManageBranches && !branch.is_default && (
                                                <button className="btn-icon text-danger" onClick={() => handleDelete(branch.id)} title={t('common.delete')}>
                                                    <Trash size={16} />
                                                </button>
                                            )}
                                            {!canManageBranches && '-'}
                                        </div>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            <SimpleModal
                isOpen={showModal}
                onClose={() => setShowModal(false)}
                title={isEditing ? t('branches.edit_branch') : t('branches.new_branch')}
                size="md"
            >
                <form onSubmit={handleSubmit}>
                    <div className="form-group mb-3">
                        <label className="form-label">{t('branches.name')} *</label>
                        <input
                            type="text"
                            className="form-input"
                            value={formData.branch_name}
                            onChange={e => setFormData({ ...formData, branch_name: e.target.value })}
                            required
                        />
                    </div>
                    <div className="form-group mb-3">
                        <label className="form-label">{t('branches.name_en')}</label>
                        <input
                            type="text"
                            className="form-input"
                            value={formData.branch_name_en || ''}
                            onChange={e => setFormData({ ...formData, branch_name_en: e.target.value })}
                        />
                    </div>
                    <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px' }}>
                        <div className="form-group">
                            <label className="form-label">{t('branches.code')}</label>
                            <input
                                type="text"
                                className="form-input"
                                value={formData.branch_code || ''}
                                onChange={e => setFormData({ ...formData, branch_code: e.target.value })}
                            />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('branches.country')} *</label>
                            <select
                                className="form-input"
                                value={formData.country_code || ''}
                                onChange={e => handleCountryChange(e.target.value)}
                                required
                            >
                                <option value="">{t('common.select')}</option>
                                {COUNTRIES.map(c => (
                                    <option key={c.code} value={c.code}>{c.flag} {c.name} ({c.name_en})</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('branches.currency')}</label>
                            <select
                                className="form-input"
                                value={formData.default_currency || ''}
                                onChange={e => setFormData({ ...formData, default_currency: e.target.value })}
                            >
                                <option value="">{t('common.select')}</option>
                                {[
                                    ...ALL_CURRENCIES,
                                    ...currencies.filter(c => !ALL_CURRENCIES.find(x => x.code === c.code))
                                        .map(c => ({ code: c.code, name: c.name || c.code }))
                                ].map(c => (
                                    <option key={c.code} value={c.code}>{c.name} ({c.code})</option>
                                ))}
                            </select>
                        </div>
                    </div>
                    <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px' }}>
                        <div className="form-group">
                            <label className="form-label">{t('branches.city')}</label>
                            <input
                                type="text"
                                className="form-input"
                                value={formData.city || ''}
                                onChange={e => setFormData({ ...formData, city: e.target.value })}
                            />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('branches.phone')}</label>
                            <input
                                type="text"
                                className="form-input"
                                value={formData.phone || ''}
                                onChange={e => setFormData({ ...formData, phone: e.target.value })}
                            />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('branches.email')}</label>
                            <input
                                type="email"
                                className="form-input"
                                value={formData.email || ''}
                                onChange={e => setFormData({ ...formData, email: e.target.value })}
                            />
                        </div>
                    </div>
                    <div className="form-group mb-3">
                        <label className="form-label">{t('branches.address')}</label>
                        <textarea
                            className="form-textarea"
                            value={formData.address || ''}
                            onChange={e => setFormData({ ...formData, address: e.target.value })}
                            rows="2"
                        />
                    </div>

                    <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <input
                            type="checkbox"
                            checked={formData.is_active}
                            onChange={e => setFormData({ ...formData, is_active: e.target.checked })}
                            id="isActive"
                            className="checkbox checkbox-primary"
                        />
                        <label htmlFor="isActive" style={{ marginBottom: 0 }}>{t('common.active')}</label>
                    </div>

                    <div className="modal-footer">
                        <button type="button" className="btn btn-outline" onClick={() => setShowModal(false)} disabled={saving}>{t('common.cancel')}</button>
                        <button type="submit" className="btn btn-primary" disabled={saving}>
                            {saving ? t('common.saving', 'جاري الحفظ...') : t('common.save')}
                        </button>
                    </div>
                </form>
            </SimpleModal>
        </div>
    );
};

export default Branches;
