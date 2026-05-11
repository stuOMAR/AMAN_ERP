import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { assetsAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { Building2, Plus, Calendar, DollarSign, TrendingDown, FileText, Save, X } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

const LeaseContracts = () => {
    const { t, i18n } = useTranslation();
    const { showToast } = useToast();
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const [activeTab, setActiveTab] = useState('list');
    const [leases, setLeases] = useState([]);
    const [assets, setAssets] = useState([]);
    const [schedule, setSchedule] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState({
        asset_id: '', description: '', lessor_name: '', lease_type: 'operating',
        start_date: '', end_date: '', monthly_payment: '', total_payments: '',
        discount_rate: '5', status: 'active'
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchData = async () => {
        try {
            setLoading(true);
            const assetParams = { limit: 5000 };
            if (currentBranch?.id) {
                assetParams.branch_id = currentBranch.id;
            }
            const [lRes, aRes] = await Promise.all([
                assetsAPI.listLeaseContracts(),
                assetsAPI.list(assetParams)
            ]);
            setLeases(lRes.data || []);
            setAssets(aRes.data?.assets || aRes.data || []);
        } catch (err) {
            console.error(err);
            showToast(err.response?.data?.detail || t('common.error_occurred', 'حدث خطأ'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const res = await assetsAPI.createLeaseContract(form);
            showToast(`${t('lease_contracts.lease_created', 'تم إنشاء عقد الإيجار')} — ${t('lease_contracts.rou_created', 'قيمة حق الاستخدام')}: ${formatNumber(res.data.right_of_use_value)} ${currency}`, 'success');
            setShowForm(false);
            fetchData();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'خطأ'), 'error');
        }
    };

    const viewSchedule = async (leaseId) => {
        try {
            const res = await assetsAPI.getLeaseSchedule(leaseId);
            setSchedule(res.data);
            setActiveTab('schedule');
        } catch (err) {
            showToast(t('lease_contracts.schedule_failed', 'فشل تحميل الجدول'), 'error');
        }
    };

    const totalROU = leases.reduce((s, l) => s + parseFloat(l.right_of_use_value || 0), 0);
    const totalLiability = leases.reduce((s, l) => s + parseFloat(l.lease_liability || 0), 0);
    const activeLeases = leases.filter(l => l.status === 'active');

    const formatDate = (d) => d ? new Date(d).toLocaleDateString(i18n.language === 'ar' ? 'ar-SA' : 'en-US') : '—';

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div>
                        <h1 className="workspace-title">
                            <Building2 size={24} className="me-2" />
                            {t('lease_contracts.title', 'عقود الإيجار (IFRS 16)')}
                        </h1>
                        <p className="workspace-subtitle">
                            {t('lease_contracts.subtitle', 'إدارة أصول حق الاستخدام والتزامات الإيجار')}
                        </p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowForm(true)}>
                        <Plus size={16} className="me-1" /> {t('lease_contracts.new_lease', 'عقد إيجار جديد')}
                    </button>
                </div>
            </div>

            {/* IFRS 16 Summary Metrics */}
            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#e3f2fd' }}><Building2 size={22} color="#1565c0" /></div>
                    <div className="metric-info">
                        <span className="metric-value">{activeLeases.length}</span>
                        <span className="metric-label">{t('lease_contracts.active_leases', 'عقود نشطة')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#e8f5e9' }}><DollarSign size={22} color="#2e7d32" /></div>
                    <div className="metric-info">
                        <span className="metric-value">{formatNumber(totalROU)}</span>
                        <span className="metric-label">{t('lease_contracts.rou_value', 'قيمة أصل حق الاستخدام')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#fce4ec' }}><TrendingDown size={22} color="#c62828" /></div>
                    <div className="metric-info">
                        <span className="metric-value">{formatNumber(totalLiability)}</span>
                        <span className="metric-label">{t('lease_contracts.lease_liability', 'التزام الإيجار')}</span>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div className="tabs mb-3">
                <button className={`tab ${activeTab === 'list' ? 'active' : ''}`} onClick={() => setActiveTab('list')}>
                    <FileText size={16} /> <span className="ms-1">{t('lease_contracts.contracts', 'العقود')}</span>
                </button>
                {schedule && (
                    <button className={`tab ${activeTab === 'schedule' ? 'active' : ''}`} onClick={() => setActiveTab('schedule')}>
                        <Calendar size={16} /> <span className="ms-1">{t('lease_contracts.amortization', 'جدول الاستهلاك')}</span>
                    </button>
                )}
            </div>

            {/* New Lease Form */}
            {showForm && (
                <div className="section-card mb-4">
                    <h3 className="mb-3">{t('lease_contracts.new_lease_ifrs16', 'عقد إيجار جديد — حساب IFRS 16')}</h3>
                    <form onSubmit={handleSubmit}>
                        <div className="row g-3">
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.asset_optional', 'الأصل (اختياري)')}</label>
                                    <select className="form-input" value={form.asset_id}
                                        onChange={e => setForm(p => ({ ...p, asset_id: e.target.value }))}>
                                        <option value="">{t('lease_contracts.none_linked', 'بدون ربط')}</option>
                                        {assets.map(a => <option key={a.id} value={a.id}>{a.name} ({a.code})</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.lessor', 'المؤجر')} *</label>
                                    <input className="form-input" required value={form.lessor_name}
                                        onChange={e => setForm(p => ({ ...p, lessor_name: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.lease_type', 'نوع الإيجار')}</label>
                                    <select className="form-input" value={form.lease_type}
                                        onChange={e => setForm(p => ({ ...p, lease_type: e.target.value }))}>
                                        <option value="operating">{t('lease_contracts.operating', 'تشغيلي')}</option>
                                        <option value="finance">{t('lease_contracts.finance', 'تمويلي')}</option>
                                    </select>
                                </div>
                            </div>
                            <div className="col-md-6">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.description', 'الوصف')}</label>
                                    <input className="form-input" value={form.description}
                                        onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.start_date', 'تاريخ البدء')} *</label>
                                    <DateInput className="form-input" required value={form.start_date}
                                        onChange={e => setForm(p => ({ ...p, start_date: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.end_date', 'تاريخ الانتهاء')} *</label>
                                    <DateInput className="form-input" required value={form.end_date}
                                        onChange={e => setForm(p => ({ ...p, end_date: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.monthly_payment', 'الدفعة الشهرية')} ({currency}) *</label>
                                    <input className="form-input" type="number" step="0.01" required value={form.monthly_payment}
                                        onChange={e => setForm(p => ({ ...p, monthly_payment: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.total_payments', 'عدد الدفعات')} *</label>
                                    <input className="form-input" type="number" required value={form.total_payments}
                                        onChange={e => setForm(p => ({ ...p, total_payments: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('lease_contracts.discount_rate', 'معدل الخصم') + ' %'}</label>
                                    <input className="form-input" type="number" step="0.01" value={form.discount_rate}
                                        onChange={e => setForm(p => ({ ...p, discount_rate: e.target.value }))} />
                                </div>
                            </div>
                        </div>
                        <div className="alert alert-info mt-3" style={{ fontSize: '0.85rem' }}>
                            💡 {t('lease_contracts.ifrs16_info', 'سيتم حساب قيمة حق الاستخدام (ROU) والتزام الإيجار تلقائياً وفق IFRS 16')}
                        </div>
                        <div className="d-flex gap-2 mt-3">
                            <button type="submit" className="btn btn-primary"><Save size={16} className="me-1" /> {t('lease_contracts.save_calculate', 'حفظ وحساب')}</button>
                            <button type="button" className="btn btn-outline-secondary" onClick={() => setShowForm(false)}><X size={16} className="me-1" /> {t('common.cancel', 'إلغاء')}</button>
                        </div>
                    </form>
                </div>
            )}

            {/* Content */}
            <div className="section-card">
                {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
                {initialLoad && loading ? (
                    <PageLoading />
                ) : activeTab === 'list' ? (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>{t('lease_contracts.description', 'الوصف')}</th>
                                    <th>{t('lease_contracts.lessor', 'المؤجر')}</th>
                                    <th>{t('lease_contracts.type', 'النوع')}</th>
                                    <th>{t('lease_contracts.start', 'البداية')}</th>
                                    <th>{t('lease_contracts.end', 'النهاية')}</th>
                                    <th>{t('lease_contracts.payment', 'الدفعة')}</th>
                                    <th>{t('lease_contracts.rou_value', 'حق الاستخدام')}</th>
                                    <th>{t('lease_contracts.lease_liability', 'الالتزام')}</th>
                                    <th>{t('lease_contracts.status', 'الحالة')}</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {leases.length === 0 ? (
                                    <tr><td colSpan={11} className="text-center p-4">{t('lease_contracts.no_leases', 'لا توجد عقود إيجار')}</td></tr>
                                ) : leases.map((l, idx) => (
                                    <tr key={l.id}>
                                        <td>{idx + 1}</td>
                                        <td>{l.description || l.asset_name || '—'}</td>
                                        <td>{l.lessor_name}</td>
                                        <td><span className="badge bg-info">{l.lease_type === 'finance' ? t('lease_contracts.finance', 'تمويلي') : t('lease_contracts.operating', 'تشغيلي')}</span></td>
                                        <td>{formatDate(l.start_date)}</td>
                                        <td>{formatDate(l.end_date)}</td>
                                        <td>{formatNumber(l.monthly_payment)} {currency}</td>
                                        <td style={{ color: '#1565c0', fontWeight: 600 }}>{formatNumber(l.right_of_use_value)} {currency}</td>
                                        <td style={{ color: '#c62828', fontWeight: 600 }}>{formatNumber(l.lease_liability)} {currency}</td>
                                        <td>
                                            <span className={`badge ${l.status === 'active' ? 'bg-success' : 'bg-secondary'}`}>
                                                {l.status === 'active' ? (t('lease_contracts.active', 'نشط')) : l.status}
                                            </span>
                                        </td>
                                        <td>
                                            <button className="btn btn-sm btn-outline-primary" onClick={() => viewSchedule(l.id)}>
                                                <Calendar size={14} className="me-1" /> {t('lease_contracts.schedule', 'الجدول')}
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : schedule ? (
                    <div>
                        <h4 className="mb-3">
                            {t('lease_contracts.schedule_title', 'جدول استهلاك عقد الإيجار')}
                            {schedule.lease?.description && ` — ${schedule.lease.description}`}
                        </h4>
                        <div className="alert alert-info mb-3" style={{ fontSize: '0.85rem' }}>
                            📐 {t('lease_contracts.accounting_treatment', 'المعالجة المحاسبية: مدين: مصروف فائدة + مصروف إهلاك | دائن: التزام إيجار + إهلاك متراكم حق الاستخدام')}
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('lease_contracts.period', 'الفترة')}</th>
                                        <th>{t('lease_contracts.payment', 'الدفعة')}</th>
                                        <th>{t('lease_contracts.interest', 'الفائدة')}</th>
                                        <th>{t('lease_contracts.principal', 'الأصل')}</th>
                                        <th>{t('lease_contracts.balance', 'الرصيد المتبقي')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(schedule.schedule || []).map(s => (
                                        <tr key={s.period}>
                                            <td>{s.period}</td>
                                            <td>{formatNumber(s.payment)} {currency}</td>
                                            <td style={{ color: '#ef6c00' }}>{formatNumber(s.interest)} {currency}</td>
                                            <td style={{ color: '#2e7d32' }}>{formatNumber(s.principal)} {currency}</td>
                                            <td style={{ fontWeight: 600 }}>{formatNumber(s.balance)} {currency}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    );
};

export default LeaseContracts;
