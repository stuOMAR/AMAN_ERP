
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { treasuryAPI } from '../../utils/api';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { Layout, Store, Calculator, Info, ArrowLeft, Play, Wallet } from 'lucide-react';
import { getIndustryFeature } from '../../hooks/useIndustryType';
import { useBranch } from '../../context/BranchContext';

const POSHome = () => {
    const { t, i18n } = useTranslation();
    const { showToast } = useToast();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const isRTL = i18n.dir() === 'rtl';

    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [openingBalance, setOpeningBalance] = useState('');
    const [warehouses, setWarehouses] = useState([]);
    const [selectedWarehouse, setSelectedWarehouse] = useState('');
    const [treasuryAccounts, setTreasuryAccounts] = useState([]);
    const [selectedTreasury, setSelectedTreasury] = useState('');
    const [notes, setNotes] = useState('');

    const isRestaurant        = getIndustryFeature('pos.table_management');
    const showCustomerDisplay = getIndustryFeature('pos.customer_display');
    const showLoyalty         = getIndustryFeature('pos.loyalty');
    const showPromotions      = getIndustryFeature('pos.promotions');

    useEffect(() => {
        const timer = setTimeout(() => {
            const init = async () => {
                await checkActiveSession();
                await fetchWarehouses();
                await fetchTreasuryAccounts();
            };
            init();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch?.id]);

    const checkActiveSession = async () => {
        try {
            const response = await api.get('/pos/sessions/active');
            if (response.data) {
                navigate('/pos/interface');
            } else {
                setLoading(false);
                setInitialLoad(false);
            }
        } catch (error) {
            showToast(t('common.error_occurred'), 'error');
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const fetchWarehouses = async () => {
        try {
            // Use POS-specific endpoint that doesn't require stock.view permission
            const response = await api.get('/pos/warehouses');
            setWarehouses(response.data);
            if (response.data.length > 0) setSelectedWarehouse(response.data[0].id);
        } catch (error) {
            showToast(t('common.error_occurred'), 'error');
        }
    }

    const fetchTreasuryAccounts = async () => {
        try {
            const response = await treasuryAPI.listAccounts(currentBranch?.id);
            // Filter only Cash/Bank accounts if needed, but for now show all active
            const activeAccounts = response.data.filter(acc => acc.is_active);
            setTreasuryAccounts(activeAccounts);
            if (activeAccounts.length > 0) setSelectedTreasury(activeAccounts[0].id);
        } catch (error) {
            showToast(t('common.error_occurred'), 'error');
        }
    }

    const handleOpenSession = async (e) => {
        e.preventDefault();
        if (!openingBalance || !selectedWarehouse || !selectedTreasury) {
            showToast(t('pos.fill_required'), 'error');
            return;
        }

        try {
            await api.post('/pos/sessions/open', {
                opening_balance: String(openingBalance),
                warehouse_id: parseInt(selectedWarehouse),
                treasury_account_id: parseInt(selectedTreasury),
                notes: notes
            });

            showToast(t('pos.session_opened'), 'success');
            navigate('/pos/interface');
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error_occurred'), 'error');
        }
    };

    if (initialLoad && loading) {
        return (
            <div className="workspace flex items-center justify-center fade-in">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
                    <p className="text-slate-500">{t('common.loading')}...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title flex items-center gap-2">
                            <span className="p-2 rounded-lg bg-blue-50 text-blue-600">
                                <Layout size={24} />
                            </span>
                            {t('pos.title')}
                        </h1>
                        <p className="workspace-subtitle">
                            {t('pos.open_new_session')}
                        </p>
                    </div>
                </div>
            </div>

            <div className="flex justify-center mt-10">
                <div className="card shadow-lg max-w-2xl w-full p-10">
                    <div className="flex items-center gap-4 mb-8">
                        <div className="w-16 h-16 bg-blue-50 text-blue-600 rounded-3xl flex items-center justify-center text-3xl">
                            <Store />
                        </div>
                        <div>
                            <h2 className="text-2xl font-black text-slate-800">{t('pos.open_session')}</h2>
                            <p className="text-slate-500">{t('pos.open_new_session')}</p>
                        </div>
                    </div>

                    <form onSubmit={handleOpenSession} className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="form-group">
                                <label className="form-label flex items-center gap-2">
                                    <Store size={16} className="text-slate-400" />
                                    {t('pos.warehouse')}
                                </label>
                                <select
                                    value={selectedWarehouse}
                                    onChange={(e) => setSelectedWarehouse(e.target.value)}
                                    className="form-input"
                                    required
                                >
                                    <option value="">{t('common.select')}</option>
                                    {warehouses.map(wh => (
                                        <option key={wh.id} value={wh.id}>{wh.name || wh.warehouse_name}</option>
                                    ))}
                                </select>
                            </div>

                            <div className="form-group">
                                <label className="form-label flex items-center gap-2">
                                    <Calculator size={16} className="text-slate-400" />
                                    {t('pos.opening_balance')}
                                </label>
                                <input
                                    type="number"
                                    value={openingBalance}
                                    onChange={(e) => setOpeningBalance(e.target.value)}
                                    className="form-input text-lg font-bold"
                                    placeholder="0.00"
                                    min="0"
                                    step="0.01"
                                    required
                                />
                            </div>
                        </div>

                        <div className="form-group">
                            <label className="form-label flex items-center gap-2">
                                <Wallet size={16} className="text-slate-400" />
                                {t('pos.treasury_account') || "حساب الخزينة"}
                            </label>
                            <select
                                value={selectedTreasury}
                                onChange={(e) => setSelectedTreasury(e.target.value)}
                                className="form-input"
                                required
                            >
                                <option value="">{t('common.select')}</option>
                                {treasuryAccounts.map(acc => (
                                    <option key={acc.id} value={acc.id}>{acc.name}</option>
                                ))}
                            </select>
                        </div>

                        <div className="form-group">
                            <label className="form-label flex items-center gap-2">
                                <Info size={16} className="text-slate-400" />
                                {t('common.notes')}
                            </label>
                            <textarea
                                value={notes}
                                onChange={(e) => setNotes(e.target.value)}
                                className="form-input no-padding"
                                style={{ paddingTop: '12px' }}
                                rows="3"
                                placeholder={t('common.notes_placeholder') || "..."}
                            />
                        </div>

                        <div className="flex flex-col sm:flex-row gap-4 pt-4">
                            <button
                                type="submit"
                                className="btn btn-primary flex-1 py-4 text-lg"
                                style={{ borderRadius: '1rem' }}
                            >
                                <Play size={20} fill="currentColor" />
                                {t('pos.open_session')}
                            </button>
                            <button
                                type="button"
                                onClick={() => navigate('/dashboard')}
                                className="btn btn-secondary py-4 px-8 text-lg"
                                style={{ borderRadius: '1rem' }}
                            >
                                <ArrowLeft size={20} className={isRTL ? "rotate-180" : ""} />
                                {t('common.back')}
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            {/* POS Features */}
            <div className="modules-grid" style={{ maxWidth: '800px', margin: '2rem auto' }}>
                <div className="card section-card">
                    <h3 className="section-title">{t('pos.home.pos_features')}</h3>
                    <div className="links-list">
                        {showPromotions && (
                            <div className="link-item" onClick={() => navigate('/pos/promotions')}>
                                <span className="link-icon">🎁</span>
                                {t('pos.home.promotions_discounts')}
                                <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                            </div>
                        )}
                        {showLoyalty && (
                            <div className="link-item" onClick={() => navigate('/pos/loyalty')}>
                                <span className="link-icon">⭐</span>
                                {t('pos.home.loyalty_programs')}
                                <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                            </div>
                        )}
                        {isRestaurant && (
                            <div className="link-item" onClick={() => navigate('/pos/tables')}>
                                <span className="link-icon">🪑</span>
                                {t('pos.home.table_management')}
                                <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                            </div>
                        )}
                        {isRestaurant && (
                            <div className="link-item" onClick={() => navigate('/pos/kitchen')}>
                                <span className="link-icon">👨‍🍳</span>
                                {t('pos.home.kitchen_display')}
                                <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                            </div>
                        )}
                        <div className="link-item" onClick={() => navigate('/pos/offline')}>
                            <span className="link-icon">📴</span>
                            {t('pos.home.offline_mode', 'وضع عدم الاتصال')}
                            <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/pos/thermal')}>
                            <span className="link-icon">🖨️</span>
                            {t('pos.home.thermal_print', 'إعدادات الطباعة الحرارية')}
                            <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                        </div>
                        {showCustomerDisplay && (
                            <div className="link-item" onClick={() => navigate('/pos/customer-display')}>
                                <span className="link-icon">🖥️</span>
                                {t('pos.home.customer_display', 'شاشة العميل')}
                                <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                            </div>
                        )}
                        <div className="link-item" onClick={() => navigate('/pos/kpi')} style={{ background: 'linear-gradient(135deg, rgba(13,148,136,0.06), rgba(13,148,136,0.12))', borderRight: isRTL ? '3px solid #0d9488' : 'none', borderLeft: !isRTL ? '3px solid #0d9488' : 'none' }}>
                            <span className="link-icon">📈</span>
                            <span style={{ fontWeight: 600, color: '#0d9488' }}>{t('kpi.pos_kpi_dashboard')}</span>
                            <span className="link-arrow">{isRTL ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default POSHome;

