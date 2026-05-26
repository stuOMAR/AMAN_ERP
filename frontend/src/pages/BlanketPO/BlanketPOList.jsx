import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { purchasesAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { formatDate } from '../../utils/dateUtils';
import { Plus, FileText } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const BlanketPOList = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const currency = getCurrency();
    const [blanketPOs, setBlanketPOs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('');

    useEffect(() => { fetchBlanketPOs(); }, [statusFilter]);

    const fetchBlanketPOs = async () => {
        try {
            setLoading(true);
            const params = {};
            if (statusFilter) params.status_filter = statusFilter;
            const res = await purchasesAPI.listBlanketPOs(params);
            setBlanketPOs(res.data?.blanket_pos || []);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const statusBadge = (s) => {
        const map = {
            draft: 'bg-gray-100 text-gray-600',
            active: 'bg-green-100 text-green-700',
            expired: 'bg-red-100 text-red-600',
            completed: 'bg-blue-100 text-blue-700',
            cancelled: 'bg-orange-100 text-orange-600',
        };
        return <span className={`badge ${map[s] || 'bg-gray-100'}`}>{t(`blanket_po.status_${s}`) || s}</span>;
    };

    const progressBar = (bpo) => {
        const pct = bpo.consumption_progress_pct || '0';
        return (
            <div className="d-flex align-items-center gap-2">
                <div style={{ width: 80, height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: bpo.is_fully_released ? '#3b82f6' : '#22c55e', borderRadius: 3 }} />
                </div>
                <span className="text-sm text-muted">{formatNumber(pct, 0)}%</span>
            </div>
        );
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <span className="p-2 rounded-lg bg-purple-50 text-purple-600"><FileText size={24} /></span>
                            {t('blanket_po.title')}
                        </h1>
                        <p className="workspace-subtitle">{t('blanket_po.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate('/buying/blanket-po/new')}>
                        <Plus size={18} /> {t('blanket_po.new')}
                    </button>
                </div>
            </div>

            <div className="card section-card mb-3">
                <div className="d-flex gap-2 p-3">
                    {['', 'draft', 'active', 'completed', 'expired'].map(s => (
                        <button key={s} className={`btn btn-sm ${statusFilter === s ? 'btn-primary' : 'btn-outline'}`}
                            onClick={() => setStatusFilter(s)}>
                            {s ? t(`blanket_po.status_${s}`) : t('common.all')}
                        </button>
                    ))}
                </div>
            </div>

            <div className="card section-card">
                {loading ? (
                    <div className="text-center p-4">{t('common.loading')}</div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('blanket_po.agreement_number')}</th>
                                    <th>{t('blanket_po.supplier')}</th>
                                    <th>{t('blanket_po.total_qty')}</th>
                                    <th>{t('blanket_po.unit_price')}</th>
                                    <th>{t('blanket_po.total_amount')}</th>
                                    <th>{t('blanket_po.remaining')}</th>
                                    <th>{t('blanket_po.progress')}</th>
                                    <th>{t('blanket_po.validity')}</th>
                                    <th>{t('blanket_po.status')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {blanketPOs.map(bpo => (
                                    <tr key={bpo.id} className="cursor-pointer hover:bg-gray-50"
                                        onClick={() => navigate(`/buying/blanket-po/${bpo.id}`)}>
                                        <td className="font-semibold text-primary">{bpo.agreement_number}</td>
                                        <td>{bpo.supplier_name || `#${bpo.supplier_id}`}</td>
                                        <td>{formatNumber(bpo.total_quantity)}</td>
                                        <td>{formatNumber(bpo.unit_price)} {currency}</td>
                                        <td>{formatNumber(bpo.total_amount)} {currency}</td>
                                        <td>
                                            <span className="text-sm">{formatNumber(bpo.remaining_quantity)} / {formatNumber(bpo.remaining_amount)} {currency}</span>
                                        </td>
                                        <td>{progressBar(bpo)}</td>
                                        <td className="text-sm">{formatDate(bpo.valid_from)} → {formatDate(bpo.valid_to)}</td>
                                        <td>{statusBadge(bpo.status)}</td>
                                    </tr>
                                ))}
                                {blanketPOs.length === 0 && (
                                    <tr><td colSpan="9" className="text-center text-muted p-4">{t('blanket_po.no_records')}</td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
};

export default BlanketPOList;
