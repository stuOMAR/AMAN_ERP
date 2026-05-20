import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { assetsAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { AlertTriangle, Play, DollarSign, TrendingDown, FileText } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const ImpairmentTest = () => {
    const { t, i18n } = useTranslation();
    const { showToast } = useToast();
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const [assets, setAssets] = useState([]);
    const [selectedAsset, setSelectedAsset] = useState('');
    const [impairments, setImpairments] = useState([]);
    const [testResult, setTestResult] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [testing, setTesting] = useState(false);
    const [form, setForm] = useState({
        recoverable_amount: '',
        fair_value_less_costs: '',
        value_in_use: '',
        discount_rate: '10',
        notes: ''
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchAssets()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);
    useEffect(() => { if (selectedAsset) fetchImpairments(); }, [selectedAsset]);

    const fetchAssets = async () => {
        try {
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await assetsAPI.list(params);
            const list = res.data?.assets || res.data || [];
            setAssets(list);
            if (list.length > 0) setSelectedAsset(list[0].id);
        } catch (err) { console.error(err); } finally { setLoading(false); setInitialLoad(false); }
    };

    const fetchImpairments = async () => {
        try {
            setLoading(true);
            const res = await assetsAPI.listImpairments(selectedAsset);
            setImpairments(res.data || []);
        } catch (err) { console.error(err); } finally { setLoading(false); }
    };

    const runTest = async () => {
        if (!selectedAsset) return;
        try {
            setTesting(true);
            // Send raw string values — backend computes recoverable_amount = MAX(fv, viu) per IAS 36.18
            const payload = {
                recoverable_amount: form.recoverable_amount || null,
                fair_value_less_costs: form.fair_value_less_costs || null,
                value_in_use: form.value_in_use || null,
                discount_rate: form.discount_rate || null,
                notes: form.notes
            };
            const res = await assetsAPI.runImpairmentTest(selectedAsset, payload);
            setTestResult(res.data);
            showToast(t('impairment_test.test_completed', 'تم إجراء اختبار الانخفاض'), 'success');
            fetchImpairments();
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'خطأ'), 'error');
        } finally { setTesting(false); }
    };

    const selectedAssetData = assets.find(a => a.id == selectedAsset);
    const carryingAmount = selectedAssetData?.net_book_value || selectedAssetData?.carrying_amount || '0';

    const formatCurrency = (val) => {
        if (!val && val !== 0) return '—';
        return `${formatNumber(val)} ${currency}`;
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        <AlertTriangle size={24} className="me-2" />
                        {t('impairment_test.title', 'اختبار انخفاض القيمة (IAS 36)')}
                    </h1>
                    <p className="workspace-subtitle">
                        {t('impairment_test.subtitle', 'مقارنة المبلغ القابل للاسترداد بالقيمة الدفترية وتسجيل خسائر الانخفاض')}
                    </p>
                </div>
            </div>

            {/* Asset Selector */}
            <div className="d-flex gap-3 mb-4 align-items-center flex-wrap">
                <label className="form-label mb-0" style={{ whiteSpace: 'nowrap' }}>{t('impairment_test.asset_label', 'الأصل:')}</label>
                <select className="form-input" style={{ maxWidth: 400 }} value={selectedAsset}
                    onChange={e => setSelectedAsset(e.target.value)}>
                    {assets.map(a => <option key={a.id} value={a.id}>{a.name || a.asset_name} — {formatCurrency(a.net_book_value || a.carrying_amount || a.cost)}</option>)}
                </select>
                {selectedAssetData && (
                    <span className="badge bg-primary" style={{ fontSize: '0.9rem' }}>
                        {t('impairment_test.carrying_amount', 'القيمة الدفترية') + ': '}{formatCurrency(carryingAmount)}
                    </span>
                )}
            </div>

            {/* IAS 36 Methodology */}
            <div className="section-card mb-4" style={{ background: '#fffde7', border: '1px solid #fff9c4' }}>
                <h5 style={{ color: '#f57f17' }}>{t('impairment_test.methodology', 'منهجية IAS 36')}</h5>
                <div style={{ fontSize: '0.9rem', lineHeight: 1.8 }}>
                    <p style={{ margin: 0, fontFamily: 'monospace', direction: 'ltr' }}>
                        <strong>Recoverable Amount = MAX(Fair Value Less Costs to Sell, Value in Use)</strong><br />
                        <strong>Impairment Loss = Carrying Amount − Recoverable Amount</strong> (if positive)<br /><br />
                    </p>
                    <div className="row">
                        <div className="col-md-6">
                            <strong>{t('impairment_test.fair_value_label', 'القيمة العادلة ناقص تكاليف البيع:')}</strong>
                            <p className="text-muted mb-1">{t('impairment_test.fair_value_desc', 'سعر السوق النشط − تكاليف التصرف المباشرة')}</p>
                        </div>
                        <div className="col-md-6">
                            <strong>{t('impairment_test.viu_label', 'القيمة الاستخدامية (VIU):')}</strong>
                            <p className="text-muted mb-1">{t('impairment_test.viu_desc', 'القيمة الحالية للتدفقات النقدية المستقبلية المخصومة')}</p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Impairment Test Form */}
            <div className="section-card mb-4">
                <h4 className="mb-3">{t('impairment_test.run_test_title', 'إجراء اختبار انخفاض القيمة')}</h4>
                <div className="row g-3">
                    <div className="col-md-3">
                        <div className="form-group">
                            <label className="form-label">{t('impairment_test.fair_value_input', 'القيمة العادلة − تكاليف البيع')}</label>
                            <input className="form-input" type="number" value={form.fair_value_less_costs}
                                onChange={e => setForm(p => ({ ...p, fair_value_less_costs: e.target.value }))} placeholder="0" />
                        </div>
                    </div>
                    <div className="col-md-3">
                        <div className="form-group">
                            <label className="form-label">{t('impairment_test.viu_input', 'القيمة الاستخدامية (VIU)')}</label>
                            <input className="form-input" type="number" value={form.value_in_use}
                                onChange={e => setForm(p => ({ ...p, value_in_use: e.target.value }))} placeholder="0" />
                        </div>
                    </div>
                    <div className="col-md-2">
                        <div className="form-group">
                            <label className="form-label">{t('impairment_test.discount_rate', 'معدل الخصم %')}</label>
                            <input className="form-input" type="number" step="0.5" value={form.discount_rate}
                                onChange={e => setForm(p => ({ ...p, discount_rate: e.target.value }))} />
                        </div>
                    </div>
                    <div className="col-md-4">
                        <div className="form-group">
                            <label className="form-label">{t('impairment_test.recoverable_auto', 'المبلغ القابل للاسترداد (تلقائي)')}</label>
                            <input className="form-input" type="text" value={
                                form.recoverable_amount || t('impairment_test.auto_calculated', 'يُحسب تلقائياً')
                            } readOnly style={{ background: '#f8f9fa', fontWeight: 700 }} />
                        </div>
                    </div>
                    <div className="col-md-12">
                        <div className="form-group">
                            <label className="form-label">{t('impairment_test.notes', 'ملاحظات')}</label>
                            <textarea className="form-input" rows={2} value={form.notes}
                                onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
                        </div>
                    </div>
                </div>

                {/* Live Preview */}
                {(form.fair_value_less_costs || form.value_in_use) && (
                    <div className="mt-3 p-3 rounded" style={{
                        background: '#e3f2fd',
                        border: '1px solid #90caf9'
                    }}>
                        <strong style={{ color: '#1565c0', fontSize: '1.0rem' }}>
                            ℹ️ {t('impairment_test.preview_hint', 'سيتم حساب خسارة الانخفاض تلقائياً عند تنفيذ الاختبار')}
                        </strong>
                    </div>
                )}

                <div className="mt-3">
                    <button className="btn btn-primary" onClick={runTest} disabled={testing}>
                        <Play size={16} className="me-1" /> {testing ? (t('impairment_test.testing', 'جاري الاختبار...')) : (t('impairment_test.run_test', 'تنفيذ الاختبار'))}
                    </button>
                </div>
            </div>

            {/* Test Result */}
            {testResult && (
                <div className="section-card mb-4" style={{ borderLeft: `4px solid ${testResult.impairment_loss > 0 ? '#c62828' : '#2e7d32'}` }}>
                    <h4>{t('impairment_test.test_result', 'نتيجة الاختبار')}</h4>
                    <div className="metrics-grid mt-3">
                        <div className="metric-card">
                            <div className="metric-icon" style={{ background: '#e3f2fd' }}><DollarSign size={20} color="#1565c0" /></div>
                            <div className="metric-info">
                                <span className="metric-value">{formatCurrency(testResult.carrying_amount)}</span>
                                <span className="metric-label">{t('impairment_test.carrying_amount', 'القيمة الدفترية')}</span>
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-icon" style={{ background: '#e8f5e9' }}><TrendingDown size={20} color="#2e7d32" /></div>
                            <div className="metric-info">
                                <span className="metric-value">{formatCurrency(testResult.recoverable_amount)}</span>
                                <span className="metric-label">{t('impairment_test.recoverable_amount', 'المبلغ القابل للاسترداد')}</span>
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-icon" style={{ background: testResult.impairment_loss > 0 ? '#fce4ec' : '#e8f5e9' }}>
                                <AlertTriangle size={20} color={testResult.impairment_loss > 0 ? '#c62828' : '#2e7d32'} />
                            </div>
                            <div className="metric-info">
                                <span className="metric-value" style={{ color: testResult.impairment_loss > 0 ? '#c62828' : '#2e7d32' }}>
                                    {formatCurrency(testResult.impairment_loss || 0)}
                                </span>
                                <span className="metric-label">{t('impairment_test.loss', 'خسارة الانخفاض')}</span>
                            </div>
                        </div>
                    </div>
                    {testResult.journal_entry_id && (
                        <div className="mt-3 p-2" style={{ background: '#f0f7ff', borderRadius: 6, fontSize: '0.85rem' }}>
                            <FileText size={14} className="me-1" />
                            {`${t('impairment_test.journal_entry', 'تم إنشاء قيد محاسبي رقم')}: #${testResult.journal_entry_id}`}
                        </div>
                    )}
                </div>
            )}

            {/* History */}
            <div className="section-card">
                <h4 className="mb-3">{t('impairment_test.history', 'سجل اختبارات الانخفاض')}</h4>
                <div className="data-table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('impairment_test.date', 'التاريخ')}</th>
                                <th>{t('impairment_test.carrying_amount', 'القيمة الدفترية')}</th>
                                <th>{t('impairment_test.recoverable_amount', 'القابل للاسترداد')}</th>
                                <th>{t('impairment_test.loss', 'خسارة الانخفاض')}</th>
                                <th>{t('impairment_test.notes', 'ملاحظات')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {impairments.length === 0 ? (
                                <tr><td colSpan={5} className="text-center p-4">{t('impairment_test.no_previous_tests', 'لا توجد اختبارات سابقة')}</td></tr>
                            ) : impairments.map(imp => (
                                <tr key={imp.id}>
                                    <td>{new Date(imp.test_date || imp.created_at).toLocaleDateString()}</td>
                                    <td>{formatCurrency(imp.carrying_amount)}</td>
                                    <td>{formatCurrency(imp.recoverable_amount)}</td>
                                    <td style={{ color: imp.impairment_loss > 0 ? '#c62828' : '#2e7d32', fontWeight: 600 }}>
                                        {formatCurrency(imp.impairment_loss || 0)}
                                    </td>
                                    <td>{imp.notes || '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

export default ImpairmentTest;
