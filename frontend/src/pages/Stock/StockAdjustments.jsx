
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import { inventoryAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';

const StockAdjustments = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [adjustments, setAdjustments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchAdjustments();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchAdjustments = async () => {
        setLoading(true);
        try {
            const response = await inventoryAPI.listAdjustments({ branch_id: currentBranch?.id });
            setAdjustments(response.data || []);
        } catch (err) {
            showToast(t('stock.adjustments.validation.error_fetch'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const filteredAdjustments = adjustments.filter(adj =>
        adj.adjustment_number?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        adj.product_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        adj.warehouse_name?.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('stock.adjustments.title')}</h1>
                            <p className="workspace-subtitle">{t('stock.adjustments.subtitle')}</p>
                        </div>
                    </div>
                    <button
                        onClick={() => navigate('/stock/adjustments/new')}
                        className="btn btn-primary"
                    >
                        <span style={{ marginLeft: '8px' }}>+</span>
                        {t('stock.adjustments.new_adjustment')}
                    </button>
                </div>
            </div>

            <div className="mb-4" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div className="search-box">
                    <Search size={16} />
                    <input
                        type="text"
                        name="search"
                        id="search"
                        placeholder={t('common.search')}
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        autoComplete="off"
                    />
                </div>
            </div>

            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th style={{ width: '15%' }}>{t('stock.adjustments.table.number')}</th>
                            <th style={{ width: '15%' }}>{t('stock.adjustments.table.date')}</th>
                            <th style={{ width: '20%' }}>{t('stock.adjustments.table.warehouse')}</th>
                            <th style={{ width: '25%' }}>{t('stock.adjustments.table.product')}</th>
                            <th style={{ width: '10%' }}>{t('stock.adjustments.table.difference')}</th>
                            <th style={{ width: '15%' }}>{t('stock.adjustments.table.type')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="6" className="text-center py-4">{t('common.loading')}</td></tr>
                        ) : filteredAdjustments.length === 0 ? (
                            <tr>
                                <td colSpan="6" className="text-center py-5">
                                    <div style={{ padding: '40px' }}>
                                        <div style={{ fontSize: '48px', marginBottom: '16px' }}>📋</div>
                                        <div className="text-muted">{t('stock.adjustments.empty')}</div>
                                    </div>
                                </td>
                            </tr>
                        ) : (
                            filteredAdjustments.map((adj) => (
                                <tr key={adj.id}>
                                    <td className="fw-medium text-primary">#{adj.adjustment_number}</td>
                                    <td className="text-muted small">
                                        {formatShortDate(adj.created_at)}
                                    </td>
                                    <td>
                                        <div style={{ fontSize: '14px', fontWeight: '500' }}>{adj.warehouse_name}</div>
                                    </td>
                                    <td>
                                        <div style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>{adj.product_name}</div>
                                        {adj.product_code && <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{adj.product_code}</div>}
                                    </td>
                                    <td className={`fw-bold ${adj.difference > 0 ? 'text-success' : 'text-danger'}`}>
                                        {adj.difference > 0 ? '+' : ''}{adj.difference}
                                    </td>
                                    <td>
                                        <span className={`badge ${adj.type === 'increase' ? 'badge-success' : 'badge-danger'}`}>
                                            {adj.type === 'increase' ? t('stock.adjustments.types.increase') : t('stock.adjustments.types.decrease')}
                                        </span>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default StockAdjustments;
